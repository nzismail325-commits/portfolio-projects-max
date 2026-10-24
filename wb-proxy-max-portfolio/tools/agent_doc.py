#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Generate and check the agent fact sheet.

FACTS.md is derived from three sources:
  - upstream snapshot directory names
  - channel adapter metadata (id/realms/route_prefixes/capabilities)
  - the smoke suite's PASS count

POLICY.md is the shared policy index; per-channel policy lives in
docs/agent/policy/<id>.md. --check verifies that every registered channel has a
policy file, that each file keeps the required labels and size budget, that the
index mentions every channel/upstream, and that core packages never import
concrete channel modules (integrations.registry is the allowed interface).

Usage:
    python tools/agent_doc.py
    python tools/agent_doc.py --check
"""
import argparse
import ast
import difflib
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT.parent
FACTS = ROOT / "docs" / "agent" / "FACTS.md"
POLICY = ROOT / "docs" / "agent" / "POLICY.md"
POLICY_DIR = ROOT / "docs" / "agent" / "policy"
POLICY_MAX_BYTES = 8 * 1024
POLICY_REQUIRED_LABELS = ("**Prerequisite:**", "**Behavior:**",
                          "**Exclusions:**")
#: 两个 adapter 可共享一份渠道策略（qoder / qoder_intl 协议与排除项相同）。
POLICY_FILE_ALIASES = {"qoder_intl": "qoder"}
SMOKE = ROOT / "tests" / "test_smoke.py"

# Directory prefix -> (display name, repository). Keep the order stable so
# generated output is deterministic.
UPSTREAMS = (
    ("upstream-v", "workbuddy2api-hub",
     "https://github.com/ardeyouxipianyi/workbuddy2api-hub"),
    ("upstream-agenthub-v", "AgentHub",
     "https://github.com/HUIdada1/AgentHub"),
    ("upstream-qoderfarm", "QoderFarm",
     "https://github.com/Libra1337/qoder-farm"),
)

CORE_DIRS = ("core", "auth", "infra", "intel", "tasks")

# Update-checker source id -> upstream display name used in FACTS.md
UPDATE_SOURCE_TO_UPSTREAM = {
    "workbuddy2api-hub": "workbuddy2api-hub",
    "agenthub": "AgentHub",
}


def upstream_rows():
    known_prefixes = tuple(prefix for prefix, _name, _repo in UPSTREAMS)
    unknown = sorted(
        path.name for path in PROJECT.iterdir()
        if path.is_dir() and path.name.startswith("upstream-")
        and not any(path.name.startswith(prefix) for prefix in known_prefixes))
    if unknown:
        raise SystemExit("unregistered upstream snapshots: %s"
                         % ", ".join(unknown))
    rows = []
    for prefix, name, repo in UPSTREAMS:
        matches = sorted(p.name for p in PROJECT.iterdir()
                         if p.is_dir() and p.name.startswith(prefix))
        if not matches:
            raise SystemExit("missing snapshot for %s (prefix %s)" % (name, prefix))
        if len(matches) > 1:
            raise SystemExit("multiple snapshots for %s: %s (keep only the latest)"
                             % (name, ", ".join(matches)))
        rows.append((name, repo, matches[0]))
    return rows


def update_sources():
    path = ROOT / "infra" / "updates.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == "UPSTREAM_SOURCES":
                return ast.literal_eval(node.value)
    raise SystemExit("UPSTREAM_SOURCES not found in infra/updates.py")


def snapshot_version(snapshot):
    match = re.search(r"v(\d+\.\d+\.\d+)$", snapshot)
    return match.group(1) if match else ""


def check_update_baselines(upstreams, sources):
    versions = {name: snapshot_version(snapshot)
                for name, _repo, snapshot in upstreams}
    by_id = {item.get("id"): item for item in sources
             if isinstance(item, dict) and item.get("id")}
    issues = []
    for source_id, upstream_name in UPDATE_SOURCE_TO_UPSTREAM.items():
        item = by_id.pop(source_id, None)
        if item is None:
            issues.append("update source `%s` missing from infra/updates.py"
                          % source_id)
            continue
        baseline = str(item.get("baseline") or "")
        expected = versions.get(upstream_name, "")
        if expected and baseline != expected:
            issues.append("infra/updates.py baseline for `%s` is %s, snapshot is %s"
                          % (source_id, baseline, expected))
    for source_id in by_id:
        issues.append("update source `%s` has no snapshot mapping" % source_id)
    return issues


def channel_adapters():
    sys.path.insert(0, str(ROOT))
    try:
        from integrations import codearts, loomy, qoder, trae, workbuddy, zcode
    except Exception as exc:  # pragma: no cover - import failures are fatal
        raise SystemExit("cannot import channel adapters: %s" % exc)
    return [
        workbuddy.WorkBuddyAdapter(),
        trae.TraeAdapter(),
        qoder.QoderAdapter("qoder"),
        qoder.QoderAdapter("qoder_intl"),
        zcode.ZcodeAdapter(),
        codearts.CodeArtsAdapter(),
        loomy.LoomyAdapter(),
    ]


def run_smoke():
    temp_root = tempfile.mkdtemp(prefix="agent-doc-smoke-")
    env = os.environ.copy()
    for key in ("TMPDIR", "TEMP", "TMP"):
        env[key] = temp_root
    try:
        proc = subprocess.run(
            [sys.executable, str(SMOKE)],
            cwd=str(ROOT), env=env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", timeout=300,
        )
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)
    if proc.returncode != 0 or "ALL CHECKS PASSED" not in proc.stdout:
        tail = "\n".join(proc.stdout.splitlines()[-40:])
        raise SystemExit("smoke suite failed:\n%s" % tail)
    lines = proc.stdout.splitlines()
    passes = sum(1 for line in lines if line.startswith("PASS "))
    fails = sum(1 for line in lines if line.startswith("FAIL "))
    if fails or passes < 1:
        raise SystemExit("unexpected smoke result: %d PASS, %d FAIL" % (passes, fails))
    return passes


def render_facts(upstreams, sources, adapters, passes):
    lines = [
        "# Agent Facts (generated)",
        "",
        "> Generated by `tools/agent_doc.py` from snapshot directories, channel",
        "> adapters, and the smoke suite. Do not edit by hand.",
        "> Refresh: `python tools/agent_doc.py`.",
        "> Check: `python tools/agent_doc.py --check`.",
        "",
        "## Upstream snapshots",
        "",
        "| Upstream | Repository | Local snapshot |",
        "|---|---|---|",
    ]
    for name, repo, snapshot in upstreams:
        lines.append("| %s | %s | `%s/` |" % (name, repo, snapshot))
    lines += [
        "",
        "## Update-check baselines",
        "",
        "| Source | Baseline |",
        "|---|---|",
    ]
    for item in sources:
        lines.append("| `%s` | %s |"
                     % (item.get("id", ""), item.get("baseline", "")))
    lines += [
        "",
        "Source: `UPSTREAM_SOURCES` in `infra/updates.py`; must match the",
        "snapshots above.",
        "",
        "## Channel registry",
        "",
        "| Channel | Realm(s) | Prefix(es) | Capabilities |",
        "|---|---|---|---|",
    ]
    for adapter in adapters:
        realms = ", ".join("`%s`" % realm for realm in adapter.realms) or "—"
        prefixes = ", ".join("`%s/`" % prefix
                             for prefix in adapter.route_prefixes) or "—"
        caps = ", ".join(sorted(adapter.capabilities)) or "—"
        lines.append("| `%s` | %s | %s | %s |" % (adapter.id, realms, prefixes, caps))
    lines += [
        "",
        "Source: adapter `id`, `realms`, `route_prefixes`, `capabilities`.",
        "",
        "## Smoke baseline",
        "",
        "- `python tests/test_smoke.py` -> **%d checks**, 0 failures." % passes,
        "",
    ]
    return "\n".join(lines)


def _import_violations(path):
    out = []
    text = path.read_text(encoding="utf-8", errors="replace")
    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.split("#", 1)[0].strip()
        if line.startswith("from integrations"):
            rest = line[len("from integrations"):].strip()
            if rest.startswith("."):
                mod = rest[1:].split()[0] if rest[1:].split() else ""
                if mod != "registry":
                    out.append((lineno, line))
            elif rest.startswith("import "):
                names = rest[len("import "):].strip().strip("() ")
                for name in names.split(","):
                    name = name.strip().split(" as ")[0].strip()
                    if name and name != "registry":
                        out.append((lineno, line))
                        break
        elif line.startswith("import integrations"):
            rest = line[len("import integrations"):].strip()
            if rest.startswith("."):
                mod = rest[1:].split()[0] if rest[1:].split() else ""
                if mod != "registry":
                    out.append((lineno, line))
    return out


def check_import_boundary():
    violations = []
    for package in CORE_DIRS:
        base = ROOT / package
        if not base.exists():
            continue
        for path in base.rglob("*.py"):
            for lineno, line in _import_violations(path):
                violations.append("%s:%d: %s" % (path.relative_to(ROOT), lineno, line))
    return violations


def _policy_name(adapter_id):
    return POLICY_FILE_ALIASES.get(adapter_id, adapter_id)


def _show(path):
    """错误信息里的路径：仓库内用相对路径，测试临时目录回退绝对路径。"""
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def check_policy(upstreams, adapters):
    """共享索引 + 每渠道策略文件的存在性、结构与大小预算。"""
    if not POLICY.exists():
        return ["missing %s" % POLICY.relative_to(ROOT)]
    issues = []
    raw = POLICY.read_bytes()
    if len(raw) > POLICY_MAX_BYTES:
        issues.append("POLICY.md is %d bytes (budget %d)"
                      % (len(raw), POLICY_MAX_BYTES))
    text = raw.decode("utf-8", "replace")
    for adapter in adapters:
        if ("`%s`" % adapter.id) not in text:
            issues.append("channel `%s` not mentioned in POLICY.md" % adapter.id)
    for name, _repo, _snapshot in upstreams:
        if name not in text:
            issues.append("upstream `%s` not mentioned" % name)
    if not POLICY_DIR.is_dir():
        issues.append("missing per-channel policy directory: %s"
                      % _show(POLICY_DIR))
        return issues

    checked = set()
    for adapter in adapters:
        filename = _policy_name(adapter.id)
        if filename in checked:
            continue
        path = POLICY_DIR / ("%s.md" % filename)
        if not path.exists():
            issues.append("missing per-channel policy: %s" % _show(path))
            checked.add(filename)
            continue
        checked.add(filename)
        body_raw = path.read_bytes()
        if len(body_raw) > POLICY_MAX_BYTES:
            issues.append("%s is %d bytes (budget %d)"
                          % (_show(path), len(body_raw), POLICY_MAX_BYTES))
        body = body_raw.decode("utf-8", "replace")
        first = body.strip().splitlines()[0].strip() if body.strip() else ""
        if not first.startswith("# ") or adapter.id not in first:
            issues.append("%s must start with a `# ...%s...` heading"
                          % (_show(path), adapter.id))
        for label in POLICY_REQUIRED_LABELS:
            if label not in body:
                issues.append("%s missing %s" % (_show(path), label))
        if ("policy/%s.md" % filename) not in text:
            issues.append("POLICY.md index missing policy/%s.md" % filename)

    for path in sorted(POLICY_DIR.glob("*.md")):
        if path.stem not in checked:
            issues.append("orphan policy file: %s" % _show(path))
    return issues


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true",
                        help="verify FACTS.md, shared/per-channel policies, "
                             "and the import boundary")
    args = parser.parse_args()

    upstreams = upstream_rows()
    sources = update_sources()
    adapters = channel_adapters()
    passes = run_smoke()
    content = render_facts(upstreams, sources, adapters, passes)
    issues = check_policy(upstreams, adapters)
    issues += check_update_baselines(upstreams, sources)
    issues += ["concrete channel import: " + item
               for item in check_import_boundary()]

    if args.check:
        current = FACTS.read_text(encoding="utf-8") if FACTS.exists() else ""
        if current != content:
            diff = difflib.unified_diff(
                current.splitlines(), content.splitlines(),
                fromfile="FACTS.md (current)", tofile="FACTS.md (generated)",
                lineterm="")
            issues.append("FACTS.md is stale:\n" +
                          "\n".join(list(diff)[:80]))
        if issues:
            print("AGENT DOC CHECK FAILED")
            for issue in issues:
                print("- " + issue)
            return 1
        print("AGENT DOC CHECK PASSED")
        print("- smoke baseline: %d checks" % passes)
        print("- FACTS.md is current")
        print("- update-check baselines match snapshots")
        print("- POLICY.md index and per-channel policies cover all channels")
        print("- no concrete channel imports in core packages")
        return 0

    FACTS.parent.mkdir(parents=True, exist_ok=True)
    FACTS.write_text(content, encoding="utf-8")
    print("wrote %s" % FACTS.relative_to(ROOT))
    print("smoke baseline: %d checks" % passes)
    if issues:
        print("WARNING:")
        for issue in issues:
            print("- " + issue)
        return 1
    print("policy and import-boundary checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
