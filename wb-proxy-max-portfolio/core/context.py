# -*- coding: utf-8 -*-
"""core/context.py —— 应用上下文（本地自研，上游无对应）

AppContext 是入口装配出来的运行时对象，承载：
- 账号池、调度器、用量库、日志库、更新检查器；
- 数据目录与设置读取的统一入口；
- 渠道适配器需要的所有回调（automation_config / log / run_task_over_accounts…）。

依赖方向：渠道适配器（integrations）拿 ctx 向下用核心设施；核心设施拿不到
ctx，也就永远不可能反向依赖渠道——这是「核心零改动接渠道」的结构保证。
"""
import json
import os
import threading
import time

from infra import ipintel
from infra import logring
from infra import logstore as logstore_mod
from infra import panel_auth
from infra import settings
from infra import updates
from infra import usage as usage_mod
from integrations import registry
from tasks import scheduler as scheduler_mod
from tasks import taskstore

DEFAULT_LOG_PREFIX = "[wb-proxy-max] "


class AppContext(object):
    def __init__(self, accounts_dir=None, usage_dir=None, log=None):
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.accounts_dir = os.path.abspath(
            accounts_dir or os.path.join(base, "accounts"))
        self.usage_dir = os.path.abspath(
            usage_dir or os.path.join(base, "usage"))
        os.makedirs(self.accounts_dir, exist_ok=True)
        os.makedirs(self.usage_dir, exist_ok=True)
        self.system_prompt = "You are a helpful assistant."
        self.default_realm = os.environ.get("WB_PROXY_DEFAULT_REALM", "intl")

        self.pool = None
        self.scheduler = None
        #: 运行日志环（面板在落库关闭时读它）；落库实例绑定在环上，由环按
        #: 开关分发——入口只负责控制台输出，这里统一负责记录，不会重复入库。
        self.log_ring = logring.RING
        self.log_store = logstore_mod.LogStore(
            os.path.join(self.usage_dir, "logs.sqlite3"))
        self.log_ring.bind_store(self.log_store)
        #: 日志回调：写环（供面板）之后转交入口注入的控制台/文件输出
        _sink = log or (lambda msg: None)

        def _log(msg, level=None, tag=None):
            try:
                self.log_ring.append(msg, level=level, tag=tag)
            except Exception:
                pass
            try:
                _sink(msg)
            except Exception:
                pass

        self.log = _log
        #: 访问日志出口：默认丢弃；入口接上控制台/文件输出（不进日志环）
        self.access_log = None
        self.usage = usage_mod.UsageStore(self.usage_dir, log=self.log)
        self.updates = updates.UpdateChecker(
            current_version=self.version(), settings_dir=self.accounts_dir,
            log=self.log)
        self.panel_sessions = panel_auth.PanelSessions()

        self._realm_lock = threading.Lock()
        self._current_realm = self.default_realm
        self._task_runner = None

    # ------------------------------------------------------------ 基础
    @staticmethod
    def version():
        return "1.0.0-max"

    def boot(self, register_channels=None):
        """注册渠道 → 加载账号池 → 存储 → 调度器。

        register_channels 是入口传入的渠道装配回调（入口层 import 具体渠道并
        在此注册）——core 层不认识任何具体渠道模块，依赖方向保持单向。
        """
        import auth.accounts as accounts_mod

        # 1. 渠道注册（必须在账号池加载前：realm 配置要先生效）
        if register_channels is not None:
            register_channels(self)

        # 2. 账号池
        self.pool = accounts_mod.AccountPool(self.accounts_dir, log=self.log)
        self.pool.load()
        self.load_persisted_realm()
        self.pool.apply_proxy_slots(settings.proxy_slots(self.accounts_dir))

        # 3. 存储：任务流水、活动历史、日志库、更新检查
        try:
            taskstore.init(os.path.join(self.usage_dir, "tasklogs.db"))
        except Exception as exc:
            self.log("task store unavailable: %s" % exc)
        try:
            from infra import activity
            activity.set_data_dir(self.usage_dir)
        except Exception as exc:
            self.log("activity history unavailable: %s" % exc)
        self.configure_log_store()
        self.updates.start()

        # 4. 调度器
        self._task_runner = scheduler_mod.TaskRunner(self, log=self.log)
        self.scheduler = scheduler_mod.Scheduler(self, log=self.log)
        self.scheduler.start()

        # 5. models.dev 预热（异步、失败静默）
        from intel import catalog
        try:
            catalog.warm_modelsdev(log=self.log)
        except Exception:
            pass
        return self

    # ------------------------------------------------------------ 设置
    def task_defaults(self):
        """各调度任务的默认开关注与整点数组（渠道适配器声明）。"""
        if self.scheduler is not None:
            return self.scheduler.task_defaults()
        return {spec[0]: spec[3] for spec in registry.scheduler_tasks(self)}

    def task_labels(self):
        if self.scheduler is not None:
            return self.scheduler.task_labels()
        return {spec[0]: spec[1] for spec in registry.scheduler_tasks(self)}

    def automation_config(self):
        """调度器配置：settings 里的值 + 各任务默认值补齐。"""
        raw = settings.automation_config(self.accounts_dir)
        out = {"enabled": raw.get("enabled", True)}
        for task_id, default in self.task_defaults().items():
            entry = raw.get(task_id)
            if not isinstance(entry, dict):
                entry = dict(default)
            else:
                merged = dict(default)
                merged.update(entry)
                entry = merged
            out[task_id] = entry
        return out

    def upstream_timeouts(self):
        return settings.upstream_timeouts(self.accounts_dir)

    def upstream_connect_timeout(self):
        return settings.upstream_connect_timeout(self.accounts_dir)

    def auto_switch_product(self):
        return settings.auto_switch_product(self.accounts_dir)

    # ------------------------------------------------------------ realm
    @property
    def current_realm(self):
        with self._realm_lock:
            return self._current_realm

    def realm_state_file(self):
        return os.path.join(self.accounts_dir, "active_realm.json")

    def load_persisted_realm(self):
        path = self.realm_state_file()
        if not os.path.isfile(path):
            return self.current_realm
        try:
            with open(path, encoding="utf-8") as fh:
                realm = (json.load(fh) or {}).get("realm")
            if realm and realm in [r for r in registry.all_realms() if r]:
                with self._realm_lock:
                    self._current_realm = realm
        except Exception as exc:
            self.log("could not load active realm: %s" % exc)
        return self.current_realm

    def save_persisted_realm(self, realm):
        """全局默认出口只可能是已注册渠道的出口之一；写盘后热生效。"""
        realms = [r for r in registry.all_realms() if r]
        if realm not in realms:
            return self.current_realm
        with self._realm_lock:
            self._current_realm = realm
        try:
            with open(self.realm_state_file(), "w", encoding="utf-8") as fh:
                json.dump({"realm": realm, "updated_at": time.time(),
                           "updated_iso": time.strftime("%Y-%m-%d %H:%M:%S")},
                          fh, indent=2)
            self.log("persisted active realm '%s' to disk" % realm)
        except Exception as exc:
            self.log("failed to persist active realm: %s" % exc)
        return self.current_realm

    # ------------------------------------------------------------ 任务执行
    def task_runner(self):
        if self._task_runner is None:
            self._task_runner = scheduler_mod.TaskRunner(self, log=self.log)
        return self._task_runner

    def run_task_over_accounts(self, kind, action, ready, source="auto",
                               classify=None, guest_action=None, interval=1.0,
                               realm=None, concurrency=1):
        """渠道适配器回调：对每个账号执行一个任务动作并落库。

        账号筛选只有一条硬规则——免登上游（无账号体系）不参与定时任务；
        「该渠道的账号该不该跑」由适配器传入的 ready 判定。concurrency > 1
        时只改变账号间的重叠，单个账号的动作与落账仍走同一条顺序语义。
        """
        accounts = [a for a in self._task_runner_accounts()
                    if not getattr(a, "free_realm", False)]
        return self.task_runner().run(
            kind, accounts, ready=ready, action=action, classify=classify,
            guest_action=guest_action, interval=interval, source=source,
            realm=realm, concurrency=concurrency)

    def _task_runner_accounts(self):
        try:
            return list(self.pool.accounts) if self.pool else []
        except Exception:
            return []

    # ------------------------------------------------------------ 日志与存储
    def configure_log_store(self):
        self.log_store.configure(
            settings.log_db_enabled(self.accounts_dir),
            settings.log_db_max_rows(self.accounts_dir),
            settings.log_db_max_days(self.accounts_dir),
            settings.log_db_max_bytes(self.accounts_dir))

    # ------------------------------------------------------------ 代理槽
    def proxy_slots(self):
        return settings.proxy_slots(self.accounts_dir)

    def apply_proxy_slots(self, slots=None):
        slots = slots if slots is not None else self.proxy_slots()
        if self.pool:
            self.pool.apply_proxy_slots(slots)

    def probe_proxy(self, proxy_url, timeout=12):
        """探测一个代理出口：IP + 国家/类型（面板代理槽用）。"""
        import urllib.request
        from core import net
        started = time.time()
        exit_ip, error = "", ""
        try:
            req = urllib.request.Request("https://api.ipify.org", method="GET")
            with net.urlopen(req, timeout=timeout, proxy=proxy_url) as resp:
                exit_ip = resp.read().decode("utf-8", "replace").strip()
        except Exception as exc:
            error = str(exc)[:160]
        latency_ms = int((time.time() - started) * 1000)
        intel = ipintel.lookup(exit_ip) if exit_ip else ipintel.empty()
        intel_ok = any(str(intel.get(field) or "").strip()
                       for field in ipintel.FIELDS)
        return {
            "ok": not error,
            "exit_ip": exit_ip,
            "latency_ms": latency_ms,
            "error": error,
            "intel_ok": intel_ok,
            "country": intel["country"],
            "country_code": intel["country_code"],
            "ip_type": intel["ip_type"],
            "isp": intel["isp"],
            "asn": intel["asn"],
        }

    def discover_proxy_slots(self):
        """探测本机 mihomo 槽位端口段，报告可达出口（自上游 v1.7.12 移植）。

        主机与端口段可用环境变量覆盖：WB_PROXY_DISCOVER_HOST /
        WB_PROXY_DISCOVER_PORTS（默认 cli-proxy-mihomo、17901-17910）。
        """
        import os as _os
        host = _os.environ.get("WB_PROXY_DISCOVER_HOST") or "cli-proxy-mihomo"
        raw = _os.environ.get("WB_PROXY_DISCOVER_PORTS") or "17901-17910"
        if "-" in raw:
            lo, _, hi = raw.partition("-")
            ports = range(int(lo), int(hi) + 1) if (lo.strip().isdigit()
                                                    and hi.strip().isdigit()) \
                else range(17901, 17911)
        elif raw.strip().isdigit():
            ports = [int(raw)]
        else:
            ports = range(17901, 17911)
        out = []
        for port in ports:
            url = "http://%s:%d" % (host, port)
            probe = self.probe_proxy(url, timeout=6)
            probe["url"] = url
            probe["reachable"] = probe["ok"]
            out.append(probe)
        return out

    # ------------------------------------------------------------ 面板鉴权
    def panel_ok(self, token):
        return self.panel_sessions.valid(token, self.accounts_dir)
