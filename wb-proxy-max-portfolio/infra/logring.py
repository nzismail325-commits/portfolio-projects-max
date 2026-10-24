# -*- coding: utf-8 -*-
"""infra/logring.py —— 进程内日志环与落库分发（本地自研，上游内联在 wb_proxy.py）

职责单一：运行日志先进入有界内存环（面板在落库关闭时也能看最近日志），
落库开关打开时再把同一行交给 LogStore 入队（append 永不阻塞请求）。

级别与模块（tag）的推断规则沿用上游 v1.7.12：调用点显式传了 level/tag 就用
传的，没传才按关键字猜。中文关键字必须收录——本仓大量日志是中文，只认英文
会让「失败/超时」全落成 INFO，面板按级别筛选时找不到。

读取侧（面板 /logs）与 LogStore.query 返回同一形状：
{"total": n, "logs": [...], "max_id": 最新id}
"""

import collections
import threading
import time

from infra import privacy

#: 内存环上限（与上游 LOG_BUFFER 一致）
MAX_ENTRIES = 2000

_ERROR_HINTS = (
    "error", "exception", "failed", "fail:", "reject", "traceback", "errno",
    "fatal", "11-128", "11101", "11140",
    "失败", "异常", "错误", "拒绝", "不可用", "无效",
)
_WARN_HINTS = (
    "warn", "warning", "retry", "timeout", "throttl",
    "重试", "超时", "告警", "警告", "降级", "限流",
)
#: 顺序即优先级，越靠前越先判定；只列本项目在用的模块。
_TAG_HINTS = (
    ("chat", ("chat:", "chat done", "request error", "/v1/chat",
              "/chat/completions", "responses")),
    ("scheduler", ("scheduler", "调度器")),
    ("tasks", ("task", "任务", "打卡", "签到", "猫猫", "travel", "growth")),
    ("accounts", ("account", "账号", "pool", "imported")),
    ("egress", ("egress", "出口", "槽位", "proxy slot", "mihomo")),
    ("upstream", ("upstream", "上游")),
    ("webtools", ("webtool", "web tool", "本地网络工具")),
    ("catalog", ("model", "catalog", "模型")),
    ("auth", ("auth", "token", "oauth")),
    ("settings", ("settings", "设置")),
    ("update", ("更新", "release")),
    ("usage", ("usage", "用量")),
)


def classify(msg, level=None, tag=None):
    """(level, tag)：显式值优先，否则按关键字推断。"""
    text = str(msg or "")
    lower = text.lower()
    if not level:
        if any(k in lower for k in _ERROR_HINTS):
            level = "ERROR"
        elif any(k in lower for k in _WARN_HINTS):
            level = "WARN"
        else:
            level = "INFO"
    if not tag:
        for candidate, hints in _TAG_HINTS:
            if any(k in lower for k in hints):
                tag = candidate
                break
        else:
            tag = "system"
    return str(level).upper(), str(tag)


class LogRing(object):
    """进程内日志环；落库开关由绑定的 LogStore 自己判断。"""

    def __init__(self, max_entries=MAX_ENTRIES):
        self._buffer = collections.deque(maxlen=max_entries)
        self._lock = threading.Lock()
        self._counter = 0
        self._store = None

    def bind_store(self, store):
        """绑定落库实例（AppContext 启动时调用一次）。"""
        self._store = store
        return store

    def append(self, msg, level=None, tag=None):
        """写一行；返回存下来的条目（面板调试用）。"""
        msg = privacy.mask_text(str(msg))
        level, tag = classify(msg, level, tag)
        now = time.localtime()
        with self._lock:
            self._counter += 1
            entry = {
                "id": self._counter,
                "ts": time.strftime("%Y-%m-%d %H:%M:%S", now),
                "time": time.strftime("%H:%M:%S", now),
                "level": level,
                "tag": tag,
                "msg": msg.rstrip(),
            }
            self._buffer.append(entry)
        store = self._store
        if store is not None and store.enabled:
            store.append(entry)
        return entry

    def query(self, limit=200, level="", tag="", search="", since_id=0):
        """按面板筛选条件读内存环（最新在后，与 LogStore 输出对齐）。"""
        with self._lock:
            items = list(self._buffer)
        if since_id and since_id > 0:
            items = [row for row in items if row["id"] > since_id]
        if level:
            wanted = str(level).upper()
            items = [row for row in items if row["level"] == wanted]
        if tag:
            wanted = str(tag).lower()
            items = [row for row in items if row["tag"].lower() == wanted]
        if search:
            needle = str(search).lower()
            items = [row for row in items
                     if needle in row["msg"].lower() or needle in row["tag"].lower()]
        total = len(items)
        if limit and limit > 0 and not since_id:
            items = items[-int(limit):]
        max_id = items[-1]["id"] if items else int(since_id or 0)
        return {"total": total, "logs": items, "max_id": max_id}

    def clear(self):
        with self._lock:
            self._buffer.clear()


#: 进程级单例：入口的 log()、AppContext 与面板读取共用同一条日志流。
RING = LogRing()
