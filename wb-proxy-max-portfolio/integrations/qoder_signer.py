# -*- coding: utf-8 -*-
"""integrations/qoder_signer.py —— Qoder 签名桥（Python 侧）

Qoder 的推理请求必须由本机客户端内置 wasm 生成每请求签名与 Encode=1 包体，
纯 Python 无法复刻。本模块把 integrations/qoder_bridge/ 的 Node 桥拉成常驻
子进程，用 JSON 行协议提供：凭据读取、设备标识、目录解密、请求签名。

进程选择顺序：WB_QODER_NODE → 系统 node → Qoder 客户端自带 Electron
（ELECTRON_RUN_AS_NODE=1）。后两者任一可用即可；两者都没有时抛 BridgeError，
渠道仍可完成账号导入以外的操作（如展示错误）。
"""
import json
import os
import queue
import shutil
import subprocess
import threading

BRIDGE_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "qoder_bridge", "bridge.cjs")

_LABELS = {"qoder": "Qoder CN", "qoder_intl": "Qoder"}
_EXE_NAMES = {"qoder": "Qoder CN.exe", "qoder_intl": "Qoder.exe"}
_RES_ENV = {"qoder": ("WB_QODER_RESOURCES", "AGENTHUB_QODER_RESOURCES"),
            "qoder_intl": ("WB_QODER_INTL_RESOURCES", "AGENTHUB_QODER_INTL_RESOURCES")}

_CONFIG = {"cache_dir": "", "log": None}
_BRIDGES = {}
_BRIDGES_LOCK = threading.Lock()


class BridgeError(RuntimeError):
    def __init__(self, message, signer_down=False):
        super().__init__(message)
        self.signer_down = bool(signer_down)


def configure(accounts_dir, log=None):
    """由渠道 install() 调用：签名器补丁缓存放账号目录下。"""
    cache_dir = os.path.join(accounts_dir or ".", "qoder-signer")
    try:
        os.makedirs(cache_dir, exist_ok=True)
    except Exception:
        pass
    _CONFIG["cache_dir"] = cache_dir
    _CONFIG["log"] = log


def _log(msg):
    fn = _CONFIG.get("log")
    if callable(fn):
        try:
            fn(msg)
        except Exception:
            pass


def _local_appdata():
    return (os.environ.get("LOCALAPPDATA")
            or os.path.join(os.path.expanduser("~"), "AppData", "Local"))


def _launcher_exes(product):
    """扫 launcher state.ini（UTF-16LE/UTF-8）取版本目录里的客户端 exe。"""
    local = _local_appdata()
    exe_name = _EXE_NAMES.get(product) or ""
    want_cn = product == "qoder"
    out = []
    try:
        subs = os.listdir(local)
    except Exception:
        return out
    for sub in subs:
        if "qoder" not in sub.lower():
            continue
        is_cn = ("cn" in sub.lower()) or ("中国" in sub)
        if is_cn != want_cn:
            continue
        base = os.path.join(local, sub)
        try:
            inners = os.listdir(base)
        except Exception:
            continue
        for inner in inners:
            if "launcher" not in inner.lower():
                continue
            for ini in ("state.ini", "install.ini"):
                path = os.path.join(base, inner, ini)
                if not os.path.exists(path):
                    continue
                try:
                    raw = open(path, "rb").read()
                    utf16 = (raw[:2] == b"\xff\xfe") or (
                        len(raw) > 3 and raw[1:2] == b"\x00" and raw[3:4] == b"\x00")
                    text = raw.decode("utf-16-le" if utf16 else "utf-8", "replace")
                except Exception:
                    continue
                fields = {}
                for line in text.splitlines():
                    if "=" in line:
                        k, _, v = line.partition("=")
                        fields[k.strip()] = v.strip()
                install_dir = fields.get("installDir") or ""
                app_exe = fields.get("appExecutable") or ""
                if install_dir and app_exe:
                    out.append(os.path.join(install_dir, app_exe))
                elif install_dir:
                    out.append(os.path.join(install_dir, exe_name))
    return out


def _registry_exes(product):
    """注册表 Uninstall 项兜底（自定义安装路径）。"""
    if os.name != "nt":
        return []
    try:
        import winreg
    except Exception:
        return []
    want_cn = product == "qoder"
    names = ("DisplayName", "DisplayIcon", "InstallLocation")
    roots = [
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE,
         r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
    ]
    out = []
    for root, path in roots:
        try:
            key = winreg.OpenKey(root, path)
        except OSError:
            continue
        index = 0
        while True:
            try:
                sub_name = winreg.EnumKey(key, index)
                index += 1
            except OSError:
                break
            try:
                sub = winreg.OpenKey(key, sub_name)
                vals = {}
                for name in names:
                    try:
                        vals[name] = str(winreg.QueryValueEx(sub, name)[0])
                    except OSError:
                        vals[name] = ""
                display = vals.get("DisplayName") or ""
                if "qoder" not in display.lower():
                    continue
                is_cn = ("cn" in display.lower()) or ("中国" in display)
                if is_cn != want_cn:
                    continue
                loc = vals.get("InstallLocation") or ""
                icon = vals.get("DisplayIcon") or ""
                if loc:
                    out.append(os.path.join(loc, _EXE_NAMES.get(product) or ""))
                if icon:
                    icon = icon.strip('"').split(",")[0]
                    if icon.lower().endswith(".exe"):
                        out.append(icon)
            except OSError:
                continue
    return out


def _client_exe(product):
    env_key = ("WB_QODER_CLIENT_EXE" if product == "qoder"
               else "WB_QODER_INTL_CLIENT_EXE")
    explicit = os.environ.get(env_key) or ""
    if explicit and os.path.exists(explicit):
        return explicit
    exe_name = _EXE_NAMES.get(product) or ""
    label = _LABELS.get(product) or ""
    local = _local_appdata()
    candidates = []
    for key in _RES_ENV.get(product, ()):
        res = os.environ.get(key) or ""
        if res:
            candidates.append(os.path.join(os.path.dirname(res.rstrip("\\/")), exe_name))
    candidates.extend([
        os.path.join(local, "Programs", label, exe_name),
        os.path.join(local, label, exe_name),
    ])
    candidates.extend(_launcher_exes(product))
    candidates.extend(_registry_exes(product))
    for path in candidates:
        try:
            if path and os.path.exists(path):
                return path
        except Exception:
            continue
    return ""


def _start_candidates(product):
    """[(executable, extra_env)]，按优先级排列。"""
    out = []
    explicit_node = os.environ.get("WB_QODER_NODE") or ""
    node = explicit_node or shutil.which("node") or ""
    if node:
        out.append((node, {}))
    exe = _client_exe(product)
    if exe:
        out.append((exe, {"ELECTRON_RUN_AS_NODE": "1"}))
    return out


class _Bridge(object):
    def __init__(self, product):
        self.product = product
        self._proc = None
        self._reader = None
        self._stderr = None
        self._waiters = {}
        self._lock = threading.RLock()
        self._start_lock = threading.Lock()
        self._call_lock = threading.Lock()
        self._next_id = 1
        self._alive = False

    # ---- 进程 ----
    def _spawn(self, exe, extra_env):
        env = os.environ.copy()
        env.update(extra_env)
        env["WB_QODER_SIGNER_CACHE"] = _CONFIG.get("cache_dir") or ""
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
        proc = subprocess.Popen(
            [exe, BRIDGE_SCRIPT],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, encoding="utf-8",
            errors="replace", bufsize=1, creationflags=flags)
        return proc

    def _read_stdout(self, proc):
        try:
            for line in proc.stdout:
                line = (line or "").strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    _log("qoder bridge stdout noise: %s" % line[:160])
                    continue
                waiter = self._waiters.pop(obj.get("id"), None)
                if waiter is not None:
                    try:
                        waiter.put_nowait(obj)
                    except Exception:
                        pass
        finally:
            self._alive = False
            for waiter in list(self._waiters.values()):
                try:
                    waiter.put_nowait({"ok": False, "error": "签名桥进程已退出",
                                       "signerDown": True})
                except Exception:
                    pass
            self._waiters.clear()

    def _read_stderr(self, proc):
        try:
            for line in proc.stderr:
                line = (line or "").strip()
                if line:
                    _log("qoder bridge: %s" % line[:300])
        except Exception:
            pass

    def _shutdown(self):
        proc = self._proc
        self._proc = None
        self._alive = False
        if proc is None:
            return
        try:
            if proc.stdin:
                proc.stdin.close()
        except Exception:
            pass
        try:
            proc.wait(timeout=2)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass

    def _ensure_started(self):
        if self._alive and self._proc is not None:
            return
        with self._start_lock:
            if self._alive and self._proc is not None:
                return
            candidates = _start_candidates(self.product)
            if not candidates:
                raise BridgeError(
                    "Qoder 签名桥不可用：未找到 Node，也未找到已安装的 %s 客户端"
                    % _LABELS.get(self.product, self.product), signer_down=True)
            last = None
            for exe, extra in candidates:
                try:
                    proc = self._spawn(exe, extra)
                except Exception as exc:
                    last = exc
                    continue
                self._proc = proc
                self._alive = True
                self._reader = threading.Thread(
                    target=self._read_stdout, args=(proc,),
                    name="qoder-bridge-out-%s" % self.product, daemon=True)
                self._reader.start()
                self._stderr = threading.Thread(
                    target=self._read_stderr, args=(proc,),
                    name="qoder-bridge-err-%s" % self.product, daemon=True)
                self._stderr.start()
                try:
                    self._call_locked("ping", timeout=15)
                    _log("qoder bridge started via %s" % os.path.basename(exe))
                    return
                except Exception as exc:
                    last = exc
                    self._shutdown()
            raise BridgeError(
                "Qoder 签名桥启动失败：%s" % (last or "未知原因"), signer_down=True)

    # ---- RPC ----
    def _call_locked(self, op, timeout=30, **args):
        self._ensure_started()
        req_id = self._next_id
        self._next_id += 1
        waiter = queue.Queue(maxsize=1)
        self._waiters[req_id] = waiter
        payload = {"id": req_id, "op": op}
        payload.update(args)
        try:
            self._proc.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
            self._proc.stdin.flush()
        except Exception as exc:
            self._waiters.pop(req_id, None)
            self._shutdown()
            raise BridgeError("签名桥写入失败：%s" % exc, signer_down=True)
        try:
            obj = waiter.get(timeout=timeout)
        except queue.Empty:
            self._waiters.pop(req_id, None)
            self._shutdown()
            raise BridgeError("Qoder 签名桥超时（%s，%ss）" % (op, timeout),
                              signer_down=True)
        if not obj.get("ok"):
            raise BridgeError(obj.get("error") or "签名桥请求失败",
                              signer_down=obj.get("signerDown", False))
        return obj.get("result") or {}

    def call(self, op, timeout=30, **args):
        with self._call_lock:
            return self._call_locked(op, timeout=timeout, **args)

    # ---- 业务方法 ----
    def status(self):
        return self.call("status", timeout=20, product=self.product)

    def read_credentials(self):
        return self.call("read_credentials", timeout=60, product=self.product)

    def ensure_machine_id(self):
        result = self.call("ensure_machine_id", timeout=20, product=self.product)
        return str((result or {}).get("machineId") or "")

    def catalog(self, uid, machine_id, token):
        return self.call("catalog", timeout=60, product=self.product,
                         uid=str(uid or ""), machineId=str(machine_id or ""),
                         token=str(token or ""))

    def sign(self, uid, machine_id, token, origin, body_json, model,
             source="system"):
        return self.call("sign", timeout=60, product=self.product,
                         uid=str(uid or ""), machineId=str(machine_id or ""),
                         token=str(token or ""), origin=str(origin or ""),
                         body=str(body_json or ""), model=str(model or ""),
                         source=str(source or "system"))


def get_bridge(product):
    with _BRIDGES_LOCK:
        bridge = _BRIDGES.get(product)
        if bridge is None:
            bridge = _Bridge(product)
            _BRIDGES[product] = bridge
        return bridge


def status(product):
    return get_bridge(product).status()


def read_credentials(product):
    return get_bridge(product).read_credentials()


def ensure_machine_id(product):
    return get_bridge(product).ensure_machine_id()


def catalog(product, uid, machine_id, token):
    return get_bridge(product).catalog(uid, machine_id, token)


def sign(product, uid, machine_id, token, origin, body_json, model,
         source="system"):
    return get_bridge(product).sign(uid, machine_id, token, origin, body_json,
                                    model, source)


def client_exe(product):
    return _client_exe(product)


def shutdown_all():
    with _BRIDGES_LOCK:
        bridges = list(_BRIDGES.values())
        _BRIDGES.clear()
    for bridge in bridges:
        bridge._shutdown()
