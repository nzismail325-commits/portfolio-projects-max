# -*- coding: utf-8 -*-
"""infra/panel_auth.py —— 面板会话与登录限流（限流自上游 v1.7.12 移植）

两件事：
1. PanelSessions：面板登录令牌。持久化策略沿用二开（哈希落 settings.json，
   轮换密码即全员失效）；
2. 登录限流：每「真实客户端 IP」5 次失败 / 60 秒，超出回 429。反代部署下
   socket 对端永远不是真实客户端——对端是回环或显式受信代理时才读
   X-Real-IP / X-Forwarded-For，其余对端一律按对端地址分桶（防伪造头绕过）。
"""
import hashlib
import ipaddress
import os
import threading
import time

from infra import settings

#: 登录失败限流：窗口内允许的失败次数与窗口长度
LOGIN_FAIL_LIMIT = 5
LOGIN_FAIL_WINDOW = 60.0


# ---------------------------------------------------------------- 受信代理
def parse_trusted_proxies(raw):
    """解析 WB_TRUSTED_PROXIES：逗号分隔的 IP 或 CIDR；解析不了的条目丢弃。"""
    entries = []
    for item in str(raw or "").split(","):
        item = item.strip()
        if not item:
            continue
        try:
            entries.append(ipaddress.ip_network(item, strict=False))
        except ValueError:
            continue
    return tuple(entries)


TRUSTED_PROXIES = parse_trusted_proxies(os.environ.get("WB_TRUSTED_PROXIES", ""))


def peer_is_trusted(peer_ip):
    """对端是否有资格代表它的客户端说话：回环（本机反代）或显式配置的代理。"""
    try:
        addr = ipaddress.ip_address(str(peer_ip))
    except ValueError:
        return False
    mapped = addr.ipv4_mapped if addr.version == 6 else None
    if addr.is_loopback or (mapped is not None and mapped.is_loopback):
        return True
    for net in TRUSTED_PROXIES:
        if addr.version == net.version and addr in net:
            return True
    return False


_PROXY_HEADER_IP_MAX = 64


def _proxy_header_ip(value):
    """从代理头里取一个合法 IP 的规范文本；取不到返回 None（绝不抛异常）。"""
    text = str(value or "").strip()
    if not text or len(text) > _PROXY_HEADER_IP_MAX or "," in text:
        return None
    if text.startswith("["):
        end = text.find("]")
        if end == -1:
            return None
        text = text[1:end]
    elif text.count(":") == 1:
        host, _, port = text.partition(":")
        if port.isdigit():
            text = host
    try:
        return str(ipaddress.ip_address(text))
    except ValueError:
        return None


def login_rate_limit_key(peer_ip, headers):
    """限流键：对端可信时取代理头里的真实客户端 IP，否则取对端地址。"""
    if not peer_is_trusted(peer_ip):
        return peer_ip
    real = _proxy_header_ip(headers.get("X-Real-IP") if headers else None)
    if real:
        return real
    forwarded = (headers.get("X-Forwarded-For") if headers else None) or ""
    via_chain = _proxy_header_ip(forwarded.split(",")[0])
    if via_chain:
        return via_chain
    return peer_ip


# ---------------------------------------------------------------- 登录限流
_login_attempts = {}
_login_lock = threading.Lock()


def _prune_login_attempts(now, window=LOGIN_FAIL_WINDOW):
    for ip in list(_login_attempts.keys()):
        recent = [stamp for stamp in _login_attempts[ip] if now - stamp < window]
        if recent:
            _login_attempts[ip] = recent
        else:
            del _login_attempts[ip]


def login_allowed(key, now=None):
    """该来源此刻是否还允许尝试登录。"""
    now = time.time() if now is None else now
    with _login_lock:
        _prune_login_attempts(now)
        attempts = _login_attempts.get(key) or []
        return len(attempts) < LOGIN_FAIL_LIMIT


def login_retry_after(key, now=None):
    """还要等多少秒才能再试（0 = 现在可以）。"""
    now = time.time() if now is None else now
    with _login_lock:
        attempts = _login_attempts.get(key) or []
        if len(attempts) < LOGIN_FAIL_LIMIT:
            return 0
        oldest = min(attempts[:len(attempts) - LOGIN_FAIL_LIMIT + 1])
        return max(1, int(oldest + LOGIN_FAIL_WINDOW - now))


def note_login_failure(key, now=None):
    now = time.time() if now is None else now
    with _login_lock:
        _login_attempts.setdefault(key, []).append(now)
        _prune_login_attempts(now)


def note_login_success(key):
    with _login_lock:
        _login_attempts.pop(key, None)


def reset_login_limits():
    """清空限流状态（测试用）。"""
    with _login_lock:
        _login_attempts.clear()


# ---------------------------------------------------------------- 面板会话
class PanelSessions(object):
    """面板登录令牌：只存 SHA-256 摘要 + 签发时间，轮换密码即全员失效。

    会话有效期 settings.SESSION_TTL（7 天）：摘要在有效期内才被认作登录态，
    过期摘要落盘即清理（下次保存时写回一份不含它的列表）。
    """

    TOKEN_PREFIX = "pwb_"

    def __init__(self):
        self._lock = threading.RLock()

    def _digest(self, token):
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def _stored_digests(self, accounts_dir):
        """[{digest, created_at}] 原样读出；兼容只有摘要字符串的旧数据。"""
        stored = settings.load(accounts_dir).get("panel_tokens") or []
        out = []
        for item in stored:
            if isinstance(item, dict):
                digest = str(item.get("digest") or "")
                created = item.get("created_at") or 0
            else:
                digest, created = str(item), 0
            if digest:
                out.append({"digest": digest, "created_at": created})
        return out

    def _live_digests(self, accounts_dir):
        """有效期内摘要集合；顺带把过期条目从列表里剔除。"""
        now = time.time()
        live = set()
        kept = []
        changed = False
        for item in self._stored_digests(accounts_dir):
            created = item.get("created_at") or 0
            if created and now - created > settings.SESSION_TTL:
                changed = True       # 过期条目：丢弃
                continue
            if not created:
                changed = True       # 无签发时间的旧数据：记为现在，宽限一轮
                created = now
            live.add(item["digest"])
            kept.append({"digest": item["digest"], "created_at": created})
        if changed:
            self._persist_digests(accounts_dir, kept)
        return live

    def create(self, accounts_dir):
        import secrets
        token = self.TOKEN_PREFIX + secrets.token_urlsafe(24)
        with self._lock:
            kept = self._stored_digests(accounts_dir)
            kept.append({"digest": self._digest(token),
                         "created_at": time.time()})
            self._persist_digests(accounts_dir, kept)
        return token

    def valid(self, token, accounts_dir):
        if not token:
            return False
        with self._lock:
            digests = self._live_digests(accounts_dir)
            if not digests:
                return False
            return self._digest(token) in digests

    def revoke(self, token, accounts_dir):
        if not token:
            return
        with self._lock:
            digest = self._digest(token)
            kept = [item for item in self._stored_digests(accounts_dir)
                    if item["digest"] != digest]
            self._persist_digests(accounts_dir, kept)

    def revoke_all(self, accounts_dir):
        with self._lock:
            self._persist_digests(accounts_dir, [])

    def _persist_digests(self, accounts_dir, items):
        data = settings.load(accounts_dir)
        data["panel_tokens"] = sorted(items, key=lambda x: x["digest"])
        settings.save(accounts_dir, data)
