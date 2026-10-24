# -*- coding: utf-8 -*-
"""infra/usage.py —— 用量记账与看板统计（二开实现，已剥离全部定价字段）

吸收内容（重构 §4.7）：
- 每请求 JSONL 落盘 + 进程内累计（requests / tokens / 各模型计数）；
- 延迟分位（TTFT / 生成 / 墙钟）、tokens/s、缓存命中率；
- snapshot（总量与按模型）、perf、recent、timeseries、by-account、analytics。

明确删除（拍板砍掉）：PRICING / _row_cost / cost_usd / cost_cny / 估算预算 /
remaining 系列 / limit-events。看板与接口都不再出现任何价格字段。

存储只追加 JSONL；写入失败绝不影响请求本身。
"""
import json
import os
import threading
import time

USAGE_FIELDS = ("prompt_tokens", "completion_tokens", "reasoning_tokens",
                "cached_tokens", "total_tokens", "credit")

_lock = threading.Lock()


def _empty_stats():
    return {"requests": 0, "errors": 0, "prompt_tokens": 0, "completion_tokens": 0,
            "reasoning_tokens": 0, "cached_tokens": 0, "total_tokens": 0,
            "credit": 0.0, "started": time.time(), "by_model": {},
            "ttft_ms_sum": 0, "ttft_samples": 0,
            "gen_ms_sum": 0, "gen_samples": 0,
            "wall_ms_sum": 0, "wall_samples": 0}


class UsageStore(object):
    def __init__(self, usage_dir, log=None):
        self.dir = usage_dir
        self.log = log or (lambda msg: None)
        self.log_path = os.path.join(usage_dir, "usage.jsonl")
        self._stats = _empty_stats()
        self._cache = {}
        self._cache_lock = threading.Lock()
        os.makedirs(usage_dir, exist_ok=True)

    # ------------------------------------------------------------ 记账
    @staticmethod
    def extract_usage(usage):
        """统一三种计费口径：OpenAI / Responses / Anthropic。"""
        if not usage:
            return {}
        details = usage.get("completion_tokens_details") or {}
        prompt_details = usage.get("prompt_tokens_details") or {}
        out_det = usage.get("output_tokens_details") or {}
        in_det = usage.get("input_tokens_details") or {}
        return {
            "prompt_tokens": usage.get("prompt_tokens") or usage.get("input_tokens") or 0,
            "completion_tokens": usage.get("completion_tokens")
            or usage.get("output_tokens") or 0,
            "reasoning_tokens": details.get("reasoning_tokens")
            or out_det.get("reasoning_tokens") or 0,
            "cached_tokens": usage.get("prompt_cache_hit_tokens")
            or details.get("cached_tokens") or prompt_details.get("cached_tokens")
            or in_det.get("cached_tokens") or 0,
            "total_tokens": usage.get("total_tokens") or 0,
            "credit": usage.get("credit") or 0,
        }

    def record(self, model, usage, stream=None, elapsed_ms=None, ttft_ms=None,
               gen_ms=None, fp=None, account=None, realm=None):
        """累计统计并追加一行 JSONL。"""
        fields = self.extract_usage(usage)
        if not fields:
            return None
        row = {
            "at": time.time(),
            "iso": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "model": model,
            "stream": bool(stream),
            "elapsed_ms": elapsed_ms,
            "ttft_ms": ttft_ms,
            "gen_ms": gen_ms,
        }
        row.update(fields)
        if fp:
            row.update(fp)
        if account:
            row["account"] = account
        if realm:
            row["realm"] = realm
        if gen_ms and gen_ms > 0:
            row["tokens_per_sec"] = round(fields["completion_tokens"] / (gen_ms / 1000.0), 2)
        if fields["prompt_tokens"]:
            row["cache_hit_pct"] = round(
                fields["cached_tokens"] * 100.0 / fields["prompt_tokens"], 1)

        with _lock:
            stats = self._stats
            stats["requests"] += 1
            for key in USAGE_FIELDS:
                if key in fields:
                    stats[key] += fields[key]
            if ttft_ms is not None:
                stats["ttft_ms_sum"] += ttft_ms
                stats["ttft_samples"] += 1
            if gen_ms is not None:
                stats["gen_ms_sum"] += gen_ms
                stats["gen_samples"] += 1
            if elapsed_ms is not None:
                stats["wall_ms_sum"] += elapsed_ms
                stats["wall_samples"] += 1
            per = stats["by_model"].setdefault(
                model, {"requests": 0, **{k: 0 for k in USAGE_FIELDS}})
            per["requests"] += 1
            for key in USAGE_FIELDS:
                if key in fields:
                    per[key] += fields[key]

        self._append(row, "usage persist failed")
        return row

    def record_error(self, model, status, message, elapsed_ms=None, realm=None,
                     account=None):
        """记一次失败请求（不进 token 统计，只计错误数并落一行）。"""
        row = {
            "at": time.time(),
            "iso": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "model": model,
            "error": True,
            "status": status,
            "message": str(message)[:200],
            "elapsed_ms": elapsed_ms,
        }
        if realm:
            row["realm"] = realm
        if account:
            row["account"] = account
        with _lock:
            self._stats["errors"] += 1
            if elapsed_ms is not None:
                self._stats["wall_ms_sum"] += elapsed_ms
                self._stats["wall_samples"] += 1
        self._append(row, "error persist failed")
        return row

    def _append(self, row, fail_label):
        try:
            with open(self.log_path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        except Exception as exc:
            self.log("%s: %s" % (fail_label, exc))

    # ------------------------------------------------------------ 读
    def _tail_lines(self, max_lines, chunk=256 * 1024):
        """倒序分块只读文件末尾 max_lines 个非空行（最旧在前）。"""
        lines = []
        try:
            with open(self.log_path, "rb") as fh:
                fh.seek(0, os.SEEK_END)
                pos = fh.tell()
                buf = b""
                while pos > 0 and len(lines) < max_lines:
                    step = min(chunk, pos)
                    pos -= step
                    fh.seek(pos)
                    buf = fh.read(step) + buf
                    parts = buf.split(b"\n")
                    buf = parts[0]
                    for raw in reversed(parts[1:]):
                        if not raw.strip():
                            continue
                        lines.append(raw)
                        if len(lines) >= max_lines:
                            break
                if len(lines) < max_lines and buf.strip():
                    lines.append(buf)
        except FileNotFoundError:
            return []
        except Exception as exc:
            self.log("tail read failed: %s" % exc)
            return []
        lines.reverse()
        return lines

    def _iter_rows(self, max_lines):
        for raw in self._tail_lines(max_lines):
            try:
                yield json.loads(raw.decode("utf-8", "replace"))
            except Exception:
                continue

    def _cached(self, key, ttl, builder):
        now = time.time()
        with self._cache_lock:
            hit = self._cache.get(key)
        if hit and now - hit[0] < ttl:
            return hit[1]
        value = builder()
        with self._cache_lock:
            self._cache[key] = (time.time(), value)
        return value

    # ------------------------------------------------------------ 看板
    def snapshot(self, realm=None, ttl=30):
        """累计总量与按模型分布（可限定出口）。"""
        return self._cached(("snapshot", realm), ttl,
                            lambda: self._snapshot_uncached(realm))

    def _snapshot_uncached(self, realm=None):
        if realm:
            # 失败行也计入调用量与 errors（只是没有 token），与 perf 的成功率同一口径，
            # 否则「网关调用量 · 失败 0」与「成功率 · N 次异常拦截」同屏矛盾（T-37）
            rows = [r for r in self._iter_rows(20000)
                    if (r.get("realm") or "") == realm]
            out = _empty_stats()
            by_model = {}
            for row in rows:
                out["requests"] += 1
                if row.get("error"):
                    out["errors"] += 1
                for key in USAGE_FIELDS:
                    out[key] += row.get(key) or 0
                per = by_model.setdefault(
                    row.get("model") or "?", {"requests": 0, "errors": 0,
                                              **{k: 0 for k in USAGE_FIELDS}})
                per["requests"] += 1
                if row.get("error"):
                    per["errors"] += 1
                for key in USAGE_FIELDS:
                    per[key] += row.get(key) or 0
            out["by_model"] = by_model
            out["realm"] = realm
            return out
        with _lock:
            stats = json.loads(json.dumps(self._stats))
        stats["realm"] = ""
        return stats

    def perf(self, sample=5000, realm=None, ttl=30):
        """延迟分位与派生速率（读日志末尾 sample 行）。"""
        return self._cached(("perf", int(sample), realm), ttl,
                            lambda: self._perf_uncached(sample, realm))

    def _perf_uncached(self, sample=5000, realm=None):
        ttfts, gens, walls, rates, hits, tok_rates = [], [], [], [], [], []
        total = ok = err = 0
        model_buckets = {}
        for row in self._iter_rows(int(sample)):
            if realm and (row.get("realm") or "") != realm:
                continue
            total += 1
            model = row.get("model") or "?"
            bucket = model_buckets.setdefault(model, {
                "requests": 0, "errors": 0, "ttfts": [], "gens": [],
                "walls": [], "tok_rates": [], "hits": []})
            bucket["requests"] += 1
            if row.get("error"):
                err += 1
                bucket["errors"] += 1
                if row.get("elapsed_ms"):
                    walls.append(row["elapsed_ms"])
                continue
            ok += 1
            if row.get("ttft_ms") is not None:
                ttfts.append(row["ttft_ms"])
                bucket["ttfts"].append(row["ttft_ms"])
            if row.get("gen_ms") is not None:
                gens.append(row["gen_ms"])
                bucket["gens"].append(row["gen_ms"])
            if row.get("elapsed_ms") is not None:
                walls.append(row["elapsed_ms"])
                bucket["walls"].append(row["elapsed_ms"])
            if row.get("tokens_per_sec"):
                tok_rates.append(row["tokens_per_sec"])
                bucket["tok_rates"].append(row["tokens_per_sec"])
            if row.get("cache_hit_pct") is not None:
                hits.append(row["cache_hit_pct"])
                bucket["hits"].append(row["cache_hit_pct"])
        return {
            "sampled": total,
            "success": ok,
            "errors": err,
            "success_rate_pct": round(ok * 100.0 / (ok + err), 1) if (ok + err) else None,
            "ttft_ms": _pct_block(ttfts),
            "generation_ms": _pct_block(gens),
            "wall_ms": _pct_block(walls),
            "tokens_per_sec": _pct_block(tok_rates),
            "cache_hit_pct": _pct_block(hits),
            "by_model": {
                mid: {
                    "requests": b["requests"],
                    "errors": b["errors"],
                    "success_rate_pct": round(
                        (b["requests"] - b["errors"]) * 100.0 / b["requests"], 1)
                    if b["requests"] else None,
                    "ttft_ms": _pct_block(b["ttfts"]),
                    "generation_ms": _pct_block(b["gens"]),
                    "wall_ms": _pct_block(b["walls"]),
                    "tokens_per_sec": _pct_block(b["tok_rates"]),
                    "cache_hit_pct": _pct_block(b["hits"]),
                } for mid, b in model_buckets.items()
            },
        }

    def recent(self, limit=100, realm=None):
        """最近若干条请求（面板实时列表用）。"""
        out = []
        for row in reversed(list(self._iter_rows(max(limit * 2, 200)))):
            if realm and (row.get("realm") or "") != realm:
                continue
            out.append(row)
            if len(out) >= limit:
                break
        return out

    def by_account(self, ttl=30):
        """按账号聚合的用量（面板账号排行）。"""
        return self._cached(("by_account",), ttl, self._by_account_uncached)

    def _by_account_uncached(self):
        buckets = {}
        for row in self._iter_rows(20000):
            if row.get("error"):
                continue
            key = row.get("account") or "(unattributed)"
            bucket = buckets.setdefault(key, {
                "account": key, "requests": 0, "prompt_tokens": 0,
                "completion_tokens": 0, "reasoning_tokens": 0,
                "cached_tokens": 0, "total_tokens": 0, "models": {},
            })
            bucket["requests"] += 1
            for field in ("prompt_tokens", "completion_tokens",
                          "reasoning_tokens", "cached_tokens", "total_tokens"):
                bucket[field] += row.get(field) or 0
            model = row.get("model") or "?"
            bucket["models"][model] = bucket["models"].get(model, 0) + 1
        out = sorted(buckets.values(), key=lambda b: -b["total_tokens"])
        for item in out:
            item["models"] = sorted(item["models"].items(), key=lambda kv: -kv[1])[:5]
        return out

    def timeseries(self, days=14, realm=None, ttl=60):
        """按天/小时的请求与 Token 曲线。"""
        return self._cached(("timeseries", days, realm), ttl,
                            lambda: self._timeseries_uncached(days, realm))

    def _timeseries_uncached(self, days=14, realm=None):
        days = max(1, min(90, int(days or 14)))
        cutoff = time.time() - days * 86400
        buckets = {}
        for row in self._iter_rows(50000):
            at = row.get("at") or 0
            if at < cutoff:
                continue
            if realm and (row.get("realm") or "") != realm:
                continue
            day = time.strftime("%Y-%m-%d", time.localtime(at))
            bucket = buckets.setdefault(day, {
                "date": day, "requests": 0, "errors": 0,
                "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0})
            bucket["requests"] += 1
            if row.get("error"):
                bucket["errors"] += 1
                continue
            for field in ("prompt_tokens", "completion_tokens", "total_tokens"):
                bucket[field] += row.get(field) or 0
        return {"days": days, "series": [buckets[k] for k in sorted(buckets)]}

    def analytics(self, ttl=60):
        """模型与账号维度的汇总（面板分析页）。"""
        return self._cached(("analytics",), ttl, self._analytics_uncached)

    def _analytics_uncached(self):
        models = {}
        realms = {}
        total_requests = total_tokens = 0
        for row in self._iter_rows(20000):
            if row.get("error"):
                continue
            total_requests += 1
            total_tokens += row.get("total_tokens") or 0
            model = row.get("model") or "?"
            bucket = models.setdefault(model, {"model": model, "requests": 0,
                                               "total_tokens": 0,
                                               "completion_tokens": 0})
            bucket["requests"] += 1
            bucket["total_tokens"] += row.get("total_tokens") or 0
            bucket["completion_tokens"] += row.get("completion_tokens") or 0
            realm = row.get("realm") or ""
            rb = realms.setdefault(realm, {"realm": realm, "requests": 0,
                                           "total_tokens": 0})
            rb["requests"] += 1
            rb["total_tokens"] += row.get("total_tokens") or 0
        return {
            "total_requests": total_requests,
            "total_tokens": total_tokens,
            "by_model": sorted(models.values(), key=lambda b: -b["total_tokens"]),
            "by_realm": sorted(realms.values(), key=lambda b: -b["total_tokens"]),
        }

    def invalidate(self):
        with self._cache_lock:
            self._cache.clear()


def _pct(values, q):
    """Nearest-rank percentile（不插值）。"""
    if not values:
        return None
    ordered = sorted(values)
    index = int(round((q / 100.0) * (len(ordered) - 1)))
    return ordered[max(0, min(len(ordered) - 1, index))]


def _pct_block(values):
    return {
        "n": len(values),
        "p50": _pct(values, 50),
        "p90": _pct(values, 90),
        "p99": _pct(values, 99),
        "avg": round(sum(values) / len(values), 1) if values else None,
        "max": max(values) if values else None,
    }
