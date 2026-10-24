"""tasks/taskstore.py —— 自动化任务记录存储 (SQLite, WAL)

记录自动签到 / 猫猫旅行 / 活跃上报 / 夜猫任务 / 令牌保活的结构化结果与积分收益，
以及每次积分查询比对出的增量流水，重启不丢、可筛选可统计。

自用部署，保持简单：
- 标准库 sqlite3，单连接 + 线程锁，WAL 模式
- 记录只含账号标识、任务结果与积分数额，不写入任何令牌 / 密钥
- 启动时静默清理一年前的旧记录
"""
import os
import sqlite3
import threading
import time

SCHEMA = """
CREATE TABLE IF NOT EXISTS task_logs (
  id       INTEGER PRIMARY KEY AUTOINCREMENT,
  ts       INTEGER NOT NULL,
  uid      TEXT,
  nickname TEXT,
  kind     TEXT NOT NULL,
  source   TEXT NOT NULL DEFAULT 'auto',
  realm    TEXT NOT NULL DEFAULT '',
  level    TEXT NOT NULL DEFAULT 'ok',
  code     INTEGER,
  credits  INTEGER NOT NULL DEFAULT 0,
  message  TEXT
);
CREATE INDEX IF NOT EXISTS idx_task_logs_ts ON task_logs(ts);
CREATE INDEX IF NOT EXISTS idx_task_logs_kind ON task_logs(kind);
"""

KIND_LABELS = {
    "checkin": "自动签到",
    "travel": "猫猫旅行",
    "activity": "活跃上报",
    "nightcat": "夜猫任务",
    "streak": "连登管家",
    "school": "开学季任务",
    "dailychat": "国际版每日活跃",
    "keepalive": "令牌保活",
    "trae_checkin": "Trae 签到",
    "credit": "积分变动",
    "summary": "轮次汇总",
}

LEVEL_LABELS = {
    "ok": "成功",
    "warn": "警告",
    "error": "失败",
    "skip": "跳过",
    "credit": "积分",
}

# 记录保留天数：启动时静默清理更早的记录
RETENTION_DAYS = 365

_lock = threading.RLock()
_conn = None


def default_path():
    env = os.environ.get("WB_PROXY_TASKS_DB")
    if env:
        return env
    base = os.environ.get("WB_PROXY_USAGE_DIR") \
        or os.path.join(os.path.dirname(os.path.abspath(__file__)), "usage")
    return os.path.join(base, "tasklogs.db")


def init(path=None):
    """打开（或创建）记录库。重复调用无副作用；不传路径用默认位置。"""
    global _conn
    with _lock:
        if _conn is not None:
            return _conn
        target = path or default_path()
        os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
        conn = sqlite3.connect(target, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.executescript(SCHEMA)
        conn.commit()
        _conn = conn
        _prune()
        return _conn


def _db():
    if _conn is None:
        return init()
    return _conn


def _prune():
    try:
        cutoff = int(time.time()) - RETENTION_DAYS * 86400
        _conn.execute("DELETE FROM task_logs WHERE ts < ?", (cutoff,))
        _conn.commit()
    except sqlite3.Error:
        pass


def add_log(kind, uid="", nickname="", source="auto", realm="", level="ok",
            code=None, credits=0, message=""):
    """写一条任务记录。存储不可用时静默放弃——记录永远不能影响任务本身。"""
    try:
        conn = _db()
        with _lock:
            conn.execute(
                "INSERT INTO task_logs(ts, uid, nickname, kind, source, realm, level, code, credits, message) "
                "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (int(time.time()), str(uid or ""), str(nickname or "")[:100],
                 str(kind or ""), str(source or "auto"), str(realm or ""),
                 str(level or "ok"), code, int(credits or 0),
                 str(message or "").replace("\r", " ").replace("\n", " ")[:500]),
            )
            conn.commit()
        return True
    except sqlite3.Error:
        return False


def _where(kind=None, uid=None, days=None, realm=None):
    clauses, args = [], []
    if kind:
        clauses.append("kind = ?")
        args.append(kind)
    if uid:
        clauses.append("uid = ?")
        args.append(uid)
    if days:
        try:
            d = min(3650, max(1, int(days)))
        except (TypeError, ValueError):
            d = 0
        if d:
            clauses.append("ts >= ?")
            args.append(int(time.time()) - d * 86400)
    if realm:
        clauses.append("realm = ?")
        args.append(realm)
    prefix = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    return prefix, args


def list_logs(kind=None, uid=None, days=None, limit=200, offset=0, realm=None):
    clause, args = _where(kind, uid, days, realm)
    try:
        rows = _db().execute(
            f"SELECT * FROM task_logs{clause} ORDER BY ts DESC, id DESC LIMIT ? OFFSET ?",
            (*args, min(2000, max(1, int(limit))), max(0, int(offset))),
        ).fetchall()
    except sqlite3.Error:
        return []
    return [dict(r) for r in rows]


def count_logs(kind=None, uid=None, days=None, realm=None):
    clause, args = _where(kind, uid, days, realm)
    try:
        row = _db().execute(
            f"SELECT COUNT(*) AS n FROM task_logs{clause}", args).fetchone()
        return int(row["n"]) if row else 0
    except sqlite3.Error:
        return 0


def stats(days=None, realm=None):
    """按类型汇总条数与累计积分收益，供面板概览（realm 非空时只统计该出口）。"""
    clause, args = _where(None, None, days, realm)
    by_kind = {}
    total = 0
    total_credits = 0
    try:
        rows = _db().execute(
            f"SELECT kind, COUNT(*) AS n, COALESCE(SUM(credits), 0) AS credits "
            f"FROM task_logs{clause} GROUP BY kind", args).fetchall()
        for r in rows:
            n, credits = int(r["n"]), int(r["credits"])
            by_kind[r["kind"]] = {"count": n, "credits": credits}
            total += n
            total_credits += credits
    except sqlite3.Error:
        pass
    return {"by_kind": by_kind, "total": total, "total_credits": total_credits}
