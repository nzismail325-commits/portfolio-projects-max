# -*- coding: utf-8 -*-
"""infra/privacy.py —— 手机号脱敏（移植自主上游 v1.7.17）

只处理中国大陆 11 位手机号（1[3-9] 开头），容忍 3-4-4 分组间的常见分隔符。
故意不匹配任意 11 位数字：订单号、时间戳、长 ID 不能被误伤。

三个入口：
- mask_phone：整个值恰好是手机号时掩码；
- mask_text：一段文本里出现的手机号就地掩码（日志、拼好的摘要）；
- redact：递归脱敏面板 JSON，copy-on-write，绝不原地改共享缓存对象；
  uid / id / token / loginAccount 等标识符键原样保留（上游 #581）。
"""
import re

_PHONE_EXACT = re.compile(r"^1[3-9]\d{9}$")
_PHONE_SEP = r"[ \t\-.·]?"
# 标识符里可能恰好有一段 3-4-4 数字（如 uid 的 `179-97517476`），左右必须
# 不是标识符字符；中文、空格、标点仍是合法边界。
_PHONE_IN_TEXT = re.compile(
    r"(?<![0-9A-Za-z_])(1[3-9]\d)" + _PHONE_SEP + r"(\d{4})" + _PHONE_SEP
    + r"(\d{4})(?![0-9A-Za-z_])"
)
# 键名本身承载标识符：值里的数字串不是手机号，一律原样返回。
_IDENTITY_KEYS = frozenset((
    "uid", "account", "accountId", "id", "file", "path", "machineId",
    "sessionId", "key", "token", "accessToken", "refreshToken",
    # 登录账号（邮箱/手机号）是要给用户复制去登录的，必须原样返回；
    # 其余字段里的手机号仍按本模块脱敏。
    "loginAccount",
))


def mask_phone(value):
    """整个值就是手机号时掩码成 138****1234；其余原样返回（幂等）。"""
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not _PHONE_EXACT.match(text):
        return value
    return "%s****%s" % (text[:3], text[-4:])


def mask_text(text):
    """把文本中的手机号就地掩码；输出统一为 138****5678（幂等）。"""
    if not isinstance(text, str) or not _PHONE_IN_TEXT.search(text):
        return text
    return _PHONE_IN_TEXT.sub(
        lambda match: match.group(1) + "****" + match.group(3), text)


def redact(obj):
    """递归脱敏面板载荷（昵称与文本值），无命中时返回原对象。

    uid / id / token 等标识符键原样返回：改写 uid 会让面板回传一个池子里
    不存在的 id（上游 #581 的 404 no such account）。loginAccount 同理：
    用户要复制它去登录，脱敏后就无法登录了。
    """
    if isinstance(obj, dict):
        out = None
        for key, value in obj.items():
            if key == "nickname":
                masked = mask_phone(value)
                if masked is value:
                    masked = mask_text(value)
            elif isinstance(value, str) and key in _IDENTITY_KEYS:
                masked = value
            else:
                masked = redact(value)
            if masked is not value:
                if out is None:
                    out = dict(obj)
                out[key] = masked
        return obj if out is None else out
    if isinstance(obj, list):
        out = None
        for index, value in enumerate(obj):
            masked = redact(value)
            if masked is not value:
                if out is None:
                    out = list(obj)
                out[index] = masked
        return obj if out is None else out
    if isinstance(obj, str):
        return mask_text(obj)
    return obj
