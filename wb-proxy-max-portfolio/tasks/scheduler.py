# -*- coding: utf-8 -*-
"""tasks/scheduler.py —— 自动化任务调度器（二开骨架 + 注册表驱动）

排程形态照二开：
- 每个任务独立开关 + 独立整点数组，互不混跑；
- `_fired` 按 (任务, 日, 时) 记账：30 秒轮询漂移不漏跑、也不重复；
- 启动巡检只做保活（安全且幂等），不刚起服务就打上游全量任务；
- 手动触发与整点排程都只进任务队列，单个工作线程串行消费：用户连点多次
  就是多次排队接续执行，不会互斥拒绝、也不需要等上一轮跑完再点；
- 单账号单任务独立异常兜底；所有结果落 taskstore。

渠道无关：任务清单来自 integrations 注册表（适配器声明），本模块不硬编码
任何任务 id，也不认识任何渠道的账号对象——它只按适配器给的 ready/action/
classify 回调执行。

账号间随机错峰 2~5 秒（上游 issue #394 的保守做法），任务内写操作仍由各任务
模块自己保持 ≥1.0s 间隔。
"""
import collections
import random
import threading
import time

from integrations import registry
from tasks import taskstore

#: 账号之间的随机错峰区间（秒）
ACCOUNT_GAP = (2.0, 5.0)
#: 轮询间隔（秒）
TICK_SECONDS = 30
#: 启动后等待主服务就绪的秒数
STARTUP_DELAY = 10


class Scheduler(object):
    def __init__(self, ctx, log=None):
        self.ctx = ctx
        self._log_fn = log or getattr(ctx, "log", None)
        self._stop_event = threading.Event()
        self._thread = None
        self.last_run_time = None
        self.next_run_time = None
        self.logs = []
        # 并发任务（如网页活跃）会同时写日志；list 的 append/切片不是原子的。
        self._log_lock = threading.Lock()
        self._fired = {}         # (task_id, day, hour) -> ts
        self.last_results = {}   # task_id -> {"ts", "iso", "level", "msg"}
        # 任务队列：手动点击与整点排程都入队，工作线程（wb-task-worker）串行
        # 消费。同名任务在队列里去重；任务执行中再次点击会重新入队（本轮跑完
        # 接续执行），用户不必等上一轮结束才敢点。
        self._queue = collections.deque()   # [(task_id, reason, source)]
        self._queue_cond = threading.Condition()
        self._pending = set()    # 队列中待执行的 task_id（去重）
        self._worker = None

    # ------------------------------------------------------------ 任务清单
    def task_specs(self):
        """[(task_id, label, handler, defaults)]：内置任务 + 注册表渠道任务。"""
        specs = list(registry.scheduler_tasks(self.ctx))
        seen = {spec[0] for spec in specs}
        for task_id, label, handler, defaults in _builtin_specs(self.ctx):
            if task_id not in seen:
                specs.append((task_id, label, handler, defaults))
        return specs

    def task_ids(self):
        return [spec[0] for spec in self.task_specs()]

    def task_labels(self):
        return {spec[0]: spec[1] for spec in self.task_specs()}

    def task_defaults(self):
        return {spec[0]: spec[3] for spec in self.task_specs()}

    # ------------------------------------------------------------ 日志
    def log(self, msg):
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        with self._log_lock:
            self.logs.append("[%s] %s" % (ts, msg))
            if len(self.logs) > 120:
                self.logs = self.logs[-120:]
        if self._log_fn:
            try:
                self._log_fn(msg)
            except Exception:
                pass

    # ------------------------------------------------------------ 生命周期
    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True,
                                        name="wb-scheduler")
        self._thread.start()
        if self._worker is None or not self._worker.is_alive():
            self._worker = threading.Thread(target=self._queue_loop, daemon=True,
                                            name="wb-task-worker")
            self._worker.start()
        self.log("自动化调度器已启动（%d 项任务独立排程）"
                 % len(self.task_specs()))

    def stop(self):
        self._stop_event.set()
        self.log("自动化调度器已暂停")

    def _run_loop(self):
        time.sleep(STARTUP_DELAY)
        # 启动巡检只做保活：安全且幂等，不给上游突然来一整轮写操作
        try:
            self._run_task("keepalive", "启动巡检（仅保活检查）", source="startup")
        except Exception as exc:
            self.log("启动巡检异常: %s" % exc)
        try:
            self._enqueue_startup_tasks()
        except Exception as exc:
            self.log("启动补跑入队异常: %s" % exc)
        while not self._stop_event.is_set():
            try:
                self._tick()
            except Exception as exc:
                self.log("调度轮询异常: %s" % exc)
            self._stop_event.wait(TICK_SECONDS)

    # ------------------------------------------------------------ 任务队列
    def _queue_loop(self):
        """工作线程：串行消费任务队列，同一时刻只跑一个任务。"""
        while True:
            with self._queue_cond:
                while not self._queue:
                    self._queue_cond.wait()
                task_id, reason, source = self._queue.popleft()
            # 先出队再去重集合：任务执行中允许同名任务再次入队（本轮跑完接续）
            self._pending.discard(task_id)
            try:
                if task_id == "all":
                    cfg = self._config()
                    for tid, _label, _handler, _defaults in self.task_specs():
                        if (cfg.get(tid) or {}).get("enabled"):
                            self._run_task(tid, reason, source=source)
                else:
                    self._run_task(task_id, reason, source=source)
            except Exception as exc:
                self.log("任务[%s]执行异常: %s" % (task_id, exc))

    def enqueue(self, task_id, reason, source="manual"):
        """任务入队（队列内同名去重）。返回 True=已入队；False=已在排队。"""
        with self._queue_cond:
            if task_id in self._pending:
                return False
            self._pending.add(task_id)
            self._queue.append((task_id, reason, source))
            self._queue_cond.notify()
        return True

    def _tick(self):
        cfg = self._config()
        now = time.localtime()
        day = time.strftime("%Y-%m-%d", now)
        hour = now.tm_hour
        if cfg.get("enabled"):
            for task_id, _label, _handler, _defaults in self.task_specs():
                task_cfg = cfg.get(task_id) or {}
                if not task_cfg.get("enabled") or hour not in (task_cfg.get("hours") or []):
                    continue
                key = (task_id, day, hour)
                if key in self._fired:
                    continue
                if not self.enqueue(task_id, "排程 %02d:00" % hour, source="auto"):
                    self.log("跳过[%s]排程：队列已有同名任务待执行"
                             % self.task_labels().get(task_id, task_id))
                    continue
                self._fired[key] = time.time()
                self._prune_fired()
        self._calc_next_fire(cfg)

    def _prune_fired(self):
        if len(self._fired) > 500:
            keep = sorted(self._fired.items(), key=lambda kv: kv[1])[-200:]
            self._fired = dict(keep)

    def _enqueue_startup_tasks(self):
        """把声明了 startup 的任务补跑一次；账号级幂等闸门会跳过已完成项。"""
        cfg = self._config()
        if not cfg.get("enabled"):
            return
        for task_id, _label, _handler, _defaults in self.task_specs():
            entry = cfg.get(task_id) or {}
            if not entry.get("enabled") or not entry.get("startup"):
                continue
            if self.enqueue(task_id, "启动补跑", source="startup"):
                self.log("启动补跑：入队[%s]" % self.task_labels().get(task_id, task_id))

    def _config(self):
        cfg = dict(getattr(self.ctx, "automation_config", lambda: {})() or {})
        defaults = self.task_defaults()
        cfg.setdefault("enabled", True)
        for task_id, _label, _handler, default in self.task_specs():
            entry = cfg.get(task_id)
            base = defaults.get(task_id) or default or {}
            if not isinstance(entry, dict):
                entry = dict(base)
            else:
                entry = dict(entry)
                entry.setdefault("enabled", base.get("enabled", True))
                entry.setdefault("hours", list(base.get("hours") or [0]))
                entry.setdefault("startup", bool(base.get("startup")))
            cfg[task_id] = entry
        return cfg

    # ------------------------------------------------------------ 手动触发
    def trigger_now(self, task_id="all"):
        """手动触发：任务进队列由工作线程串行执行，点击立即返回不等待。

        task_id 可为单个任务或 all（all 只跑已启用的任务）。连点多次就是
        多次排队接续执行（队列内同名去重），不互斥拒绝。
        """
        known = set(self.task_ids())
        if task_id != "all" and task_id not in known:
            return {"ok": False, "msg": "未知任务: %s" % task_id}
        reason = "手动全部触发" if task_id == "all" else "手动触发"
        with self._queue_cond:
            ahead = len(self._queue)
        if not self.enqueue(task_id, reason, source="manual"):
            return {"ok": True, "msg": "该任务已在队列中，稍后自动执行"}
        if ahead:
            return {"ok": True,
                    "msg": "已加入执行队列（前面还有 %d 项，将依次执行）" % ahead}
        return {"ok": True, "msg": "已触发后台执行"}

    # ------------------------------------------------------------ 任务执行
    def _run_task(self, task_id, reason, source="auto"):
        label = self.task_labels().get(task_id, task_id)
        self.last_run_time = time.strftime("%Y-%m-%d %H:%M:%S")
        self.log("开始执行[%s] (%s)" % (label, reason))
        handler = None
        for spec_id, _label, spec_handler, _defaults in self.task_specs():
            if spec_id == task_id:
                handler = spec_handler
                break
        if handler is None:
            return None
        try:
            result = handler(reason, source=source)
        except Exception as exc:
            # 整轮兜底：任何异常都不允许杀死调度线程
            self.log("[%s] 整轮异常: %s" % (label, exc))
            taskstore.add_log(kind="summary", source=source, level="error",
                              message="[%s] 执行失败: %s" % (label, exc))
            self._set_last(task_id, "error", "执行失败: %s" % exc)
            return None
        if isinstance(result, dict):
            level = result.get("level") or ("warn" if result.get("fail") else "ok")
            self._set_last(task_id, level, result.get("msg") or "")
        return result

    def _set_last(self, task_id, level, msg):
        self.last_results[task_id] = {
            "ts": int(time.time()),
            "iso": time.strftime("%Y-%m-%d %H:%M:%S"),
            "level": level,
            "msg": msg,
        }

    # ------------------------------------------------------------ 下次执行
    def _calc_next_fire(self, cfg=None):
        try:
            cfg = cfg if cfg is not None else self._config()
            now = time.localtime()
            now_stamp = time.time()
            candidates = []
            for task_id, _label, _handler, _defaults in self.task_specs():
                task_cfg = cfg.get(task_id) or {}
                if not task_cfg.get("enabled"):
                    continue
                for hour in (task_cfg.get("hours") or []):
                    stamp = time.mktime((now.tm_year, now.tm_mon, now.tm_mday,
                                         hour, 0, 0, 0, 0, -1))
                    # 按完整时间戳比较：同一天、整点已过（如 21:20 看 21 点）
                    # 也必须顺延到明天，不能把过去的时刻当成「下次」
                    if stamp <= now_stamp:
                        stamp += 86400
                    candidates.append(stamp)
            if not candidates:
                self.next_run_time = "无已启用的排程任务"
                return
            self.next_run_time = time.strftime("%Y-%m-%d %H:00",
                                               time.localtime(min(candidates)))
        except Exception:
            self.next_run_time = "待调度"

    # ------------------------------------------------------------ 状态
    def status(self):
        cfg = self._config()
        tasks = {}
        for task_id, label, _handler, _defaults in self.task_specs():
            task_cfg = cfg.get(task_id) or {}
            tasks[task_id] = {
                "label": label,
                "enabled": bool(task_cfg.get("enabled")),
                "hours": list(task_cfg.get("hours") or []),
                "count": task_cfg.get("count"),
                "last": self.last_results.get(task_id),
            }
        return {
            "enabled": bool(cfg.get("enabled")),
            "mode": "任务进队列串行执行：手动点击立即入队接续，不必等上一轮跑完"
                    "（各任务的整点时间在设置页按反代修改）",
            "tasks": tasks,
            "queued": self.queue_size(),
            "last_run_time": self.last_run_time or "尚未运行",
            "next_run_time": self.next_run_time or "待调度",
            "logs": self.logs[-20:],
        }

    def queue_size(self):
        """当前排队中的任务数（面板状态展示用）。"""
        with self._queue_cond:
            return len(self._queue)


def _builtin_specs(ctx):
    """核心内置的通用任务（不属于任何渠道）：目前只有积分巡检一项占位。

    业务任务一律由渠道适配器声明——这样加渠道不用改调度器。
    """
    return []


class TaskRunner(object):
    """跨渠道任务的通用执行骨架（供渠道适配器回调）。

    渠道只需要给出：
      ready(account)            这个账号该不该参与本任务
      action(account)           实际动作，返回 dict
      classify(account, result) -> (status, message[, credits])，默认实现见下
      guest_action(account)     可选：本地幂等闸门，返回 "already" 表示跳过
      interval                  账号之间的基础间隔秒数（再叠随机错峰）

    另有可选执行钩子 gap / before_account / after_account / write_summary
    （如成长任务面板作业用它回写 job 进度），契约见 run()。

    每条结果按账号写一行 taskstore；最后写一行 summary。返回 {total, ok,
    already, fail, skip, credits, level, msg}。
    """

    def __init__(self, ctx, log=None):
        self.ctx = ctx
        self.log = log or getattr(ctx, "log", None) or (lambda msg: None)

    def accounts(self, realm=None):
        pool = self.ctx.pool
        try:
            return list(pool.accounts) if pool else []
        except Exception:
            return []

    def run(self, kind, accounts, ready, action, classify=None,
            guest_action=None, interval=1.0, source="auto", realm=None,
            gap=None, before_account=None, after_account=None,
            write_summary=True, concurrency=1, stagger=0.5):
        """跨账号顺序执行；全部钩子可选，缺省即原有行为。

        gap                      callable(index)：账号间休眠秒数；None 用
                                 max(interval, ACCOUNT_GAP 随机错峰)
        before_account(index, account)   每账号动作前回调（ready/guest 检查之前）
        after_account(index, account, result, status, earned, message)
                                 每账号落账后、账号间休眠前回调；result 为
                                 action 原始返回（异常路径为 None）
        write_summary            False 时不写本方法的汇总行（返回 dict 不变）
        concurrency              并发分片数；1 = 顺序执行（默认）。只有不带
                                 gap / before_account / after_account 时才并发，
                                 带钩子的调用保持原顺序语义。
        stagger                  并发分片启动错峰秒数，避免同刻打到上游。
        """
        if (concurrency > 1 and before_account is None
                and after_account is None and gap is None):
            return self._run_concurrent(
                kind, accounts, ready, action, classify=classify,
                guest_action=guest_action, interval=interval, source=source,
                realm=realm, write_summary=write_summary,
                concurrency=concurrency, stagger=stagger)
        classify = classify or default_classify
        total = ok = already = fail = skip = 0
        credits = 0
        last_fail_msg = ""   # 末条失败根因：随汇总行落库，面板不用翻文件日志（T-36）
        for index, account in enumerate(accounts):
            total += 1
            result, status, earned, message = None, "error", 0, ""
            try:
                if before_account is not None:
                    before_account(index, account)
                if not ready(account):
                    skip += 1
                    continue
                if guest_action is not None:
                    gate = guest_action(account)
                    if gate == "already":
                        already += 1
                        # 幂等跳过同样落记录：手动补跑才能在流水里追溯
                        #（对齐原版「调度与手动两条路径可一起追溯」的口径）
                        taskstore.add_log(
                            kind=kind, uid=getattr(account, "uid", "") or "",
                            nickname=getattr(account, "nickname", "") or "",
                            source=source,
                            realm=realm or getattr(account, "realm", "") or "",
                            level="skip", message="今日已完成（幂等跳过）")
                        continue
                result = action(account) or {}
                verdict = classify(account, result)
                status, message = verdict[0], verdict[1]
                earned = int(verdict[2]) if len(verdict) > 2 else int(
                    result.get("credit") or 0)
                if status == "ok":
                    ok += 1
                    credits += earned
                elif status == "already":
                    already += 1
                elif status == "skip":
                    skip += 1
                elif status == "warn":
                    skip += 1
                else:
                    fail += 1
                    if message:
                        last_fail_msg = message
                taskstore.add_log(
                    kind=kind, uid=getattr(account, "uid", "") or "",
                    nickname=getattr(account, "nickname", "") or "",
                    source=source, realm=realm or getattr(account, "realm", "") or "",
                    level=("ok" if status == "ok" else
                           "warn" if status == "warn" else
                           "skip" if status in ("already", "skip") else "error"),
                    credits=earned, message=message or "")
            except Exception as exc:
                fail += 1
                last_fail_msg = "%s 异常: %s" % (kind, exc)
                result, status, earned, message = None, "error", 0, last_fail_msg
                taskstore.add_log(
                    kind=kind, uid=getattr(account, "uid", "?") or "?",
                    nickname=getattr(account, "nickname", "") or "",
                    source=source, realm=realm or getattr(account, "realm", "") or "",
                    level="error", message=last_fail_msg)
            if after_account is not None:
                after_account(index, account, result, status, earned, message)
            if index < len(accounts) - 1:
                # 账号间随机错峰防风控（比固定 1 秒保守）
                if gap is not None:
                    time.sleep(gap(index))
                else:
                    time.sleep(max(interval, random.uniform(*ACCOUNT_GAP)))
        level = "warn" if fail else "ok"
        msg = _summary_text(kind, total, ok, already, fail, skip, credits)
        if fail and last_fail_msg:
            # 失败时根因直接跟在汇总行：排障不依赖运行日志文件（T-36）
            msg += "；末次失败: %s" % last_fail_msg
        if write_summary:
            taskstore.add_log(kind="summary", source=source, realm=realm or "",
                              level=level, message=msg)
        return {"total": total, "ok": ok, "already": already, "fail": fail,
                "skip": skip, "credits": credits, "level": level, "msg": msg,
                "last_fail": last_fail_msg}

    def _run_concurrent(self, kind, accounts, ready, action, classify=None,
                        guest_action=None, interval=1.0, source="auto",
                        realm=None, write_summary=True, concurrency=1,
                        stagger=0.5):
        """把账号按轮转分片后交给多个顺序执行器，最后汇总成一行。

        每个分片内部仍复用 run() 的顺序语义（账号间随机错峰），因此并发只
        改变分片间的重叠，不改单账号的重试/落账行为。分片之间错峰启动。
        """
        from concurrent.futures import ThreadPoolExecutor
        accounts = list(accounts or [])
        if not accounts:
            msg = _summary_text(kind, 0, 0, 0, 0, 0, 0)
            if write_summary:
                taskstore.add_log(kind="summary", source=source,
                                  realm=realm or "", level="ok", message=msg)
            return {"total": 0, "ok": 0, "already": 0, "fail": 0, "skip": 0,
                    "credits": 0, "level": "ok", "msg": msg, "last_fail": ""}
        workers = min(max(1, int(concurrency)), len(accounts))
        chunks = [[] for _ in range(workers)]
        for index, account in enumerate(accounts):
            chunks[index % workers].append(account)

        def _worker(chunk, ordinal):
            if ordinal:
                time.sleep(min(2.0, ordinal * max(0.0, float(stagger))))
            return self.run(
                kind, chunk, ready=ready, action=action, classify=classify,
                guest_action=guest_action, interval=interval, source=source,
                realm=realm, write_summary=False, concurrency=1)

        totals = {"total": 0, "ok": 0, "already": 0, "fail": 0,
                  "skip": 0, "credits": 0}
        last_fail = ""
        with ThreadPoolExecutor(max_workers=workers,
                                thread_name_prefix="task-%s" % kind) as pool:
            futures = [pool.submit(_worker, chunk, index)
                       for index, chunk in enumerate(chunks)]
            for future in futures:
                try:
                    result = future.result()
                except Exception as exc:
                    totals["fail"] += 1
                    last_fail = "%s 并发分片异常: %s" % (kind, exc)
                    taskstore.add_log(
                        kind=kind, source=source, realm=realm or "",
                        level="error", message=last_fail)
                    continue
                for key in totals:
                    totals[key] += int(result.get(key) or 0)
                if result.get("last_fail"):
                    last_fail = result["last_fail"]
        level = "warn" if totals["fail"] else "ok"
        msg = _summary_text(kind, totals["total"], totals["ok"],
                            totals["already"], totals["fail"],
                            totals["skip"], totals["credits"])
        if totals["fail"] and last_fail:
            msg += "；末次失败: %s" % last_fail
        if write_summary:
            taskstore.add_log(kind="summary", source=source,
                              realm=realm or "", level=level, message=msg)
        return {"total": totals["total"], "ok": totals["ok"],
                "already": totals["already"], "fail": totals["fail"],
                "skip": totals["skip"], "credits": totals["credits"],
                "level": level, "msg": msg, "last_fail": last_fail}


def default_classify(account, result):
    """默认分类：result 里 status/ok 字段 -> (status, message)。"""
    result = result or {}
    status = result.get("status")
    if status in ("ok", "already", "skip", "warn", "error"):
        return status, result.get("message") or result.get("msg") or ""
    if result.get("ok"):
        return "ok", result.get("message") or result.get("msg") or ""
    return "error", result.get("message") or result.get("msg") or "执行失败"


def _summary_text(kind, total, ok, already, fail, skip, credits):
    label = taskstore.KIND_LABELS.get(kind, kind)
    parts = ["[%s] 共 %d 个账号：成功 %d" % (label, total, ok)]
    if already:
        parts.append("幂等跳过 %d" % already)
    parts.append("失败 %d" % fail)
    if skip:
        parts.append("不适用/跳过 %d" % skip)
    text = "，".join(parts)
    if credits:
        text += "，收益 +%d 积分" % credits
    return text
