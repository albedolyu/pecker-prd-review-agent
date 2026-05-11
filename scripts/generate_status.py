"""
自动生成 STATUS.md — 替代手写 HARNESS_MATURITY.md / PRODUCTION_READINESS.md / CHANGELOG.md

数据源:
- git log: 最近提交 / 活跃度
- pytest --collect-only: 单测数量
- workspace-*/output/sessions/*.jsonl: 真实 run 计数 / worker 静默率 / 一致性基线
- 代码行数: wc -l *.py

用法:
    python scripts/generate_status.py               # 写到 STATUS.md
    python scripts/generate_status.py --dry-run     # 打印到 stdout
    python scripts/generate_status.py --out foo.md  # 自定义输出路径

CI 用法: 在 push 前跑,提交时带上自动生成的 STATUS.md。
"""

import argparse
import json
import os
import subprocess
import sys
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
try:
    from scripts.goshawk_failure_triage import classify_failure_type as _classify_goshawk_failure_type
except ImportError:  # pragma: no cover - direct script execution from scripts/
    from goshawk_failure_triage import classify_failure_type as _classify_goshawk_failure_type

# 让脚本可独立调用
ROOT = Path(__file__).resolve().parent.parent


def _run(cmd, cwd=None):
    """Run shell command, return stdout stripped (empty on failure)."""
    try:
        r = subprocess.run(cmd, cwd=cwd or ROOT, capture_output=True,
                           text=True, encoding="utf-8", errors="replace", timeout=30)
        return r.stdout.strip() if r.returncode == 0 else ""
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return ""


def collect_git_activity(days: int = 14) -> dict:
    """最近 N 天的 commit 活动."""
    since = f"{days} days ago"
    count_raw = _run(["git", "rev-list", "--count", f"--since={since}", "HEAD"])
    log_raw = _run([
        "git", "log", f"--since={since}", "--pretty=format:%h|%ad|%s",
        "--date=short", "-n", "10",
    ])
    commits = []
    for line in log_raw.split("\n"):
        if "|" in line:
            parts = line.split("|", 2)
            if len(parts) == 3:
                commits.append({"sha": parts[0], "date": parts[1], "subject": parts[2]})
    return {
        "days": days,
        "commit_count": int(count_raw) if count_raw.isdigit() else 0,
        "recent_commits": commits,
    }


def collect_test_status() -> dict:
    """pytest --collect-only 的单测计数."""
    import re
    out = _run([
        sys.executable, "-m", "pytest", "tests/",
        "--collect-only", "-q", "-p", "no:cacheprovider",
    ])
    test_count = 0
    # pytest 输出: "180 tests collected in 0.53s"
    m = re.search(r"(\d+)\s+tests?\s+collected", out)
    if m:
        test_count = int(m.group(1))
    return {"collected": test_count, "raw_tail": "\n".join(out.split("\n")[-3:])}


def collect_code_stats() -> dict:
    """根目录 .py 文件总行数 + 文件数."""
    py_files = list(ROOT.glob("*.py"))
    total_lines = 0
    for f in py_files:
        try:
            total_lines += sum(1 for _ in f.open("r", encoding="utf-8", errors="replace"))
        except OSError:
            pass
    return {"file_count": len(py_files), "total_lines": total_lines}


def _is_quota_error(err: str) -> bool:
    """识别 Claude CLI 配额耗尽错误 (ops 问题,非代码 bug)."""
    if not err:
        return False
    low = err.lower()
    return "hit your limit" in low or "usage limit" in low or "quotaexhausted" in low


def _is_auth_error(err: str) -> bool:
    """Round 15: 识别 CLI OAuth 401 失效 (ops 问题,通常因多进程并发挤占 token).

    和 quota 一样:是 ops 问题,不应该污染 effective_consistency。
    """
    if not err:
        return False
    low = err.lower()
    return ('api_error_status":401' in low or "authentication_error" in low
            or "invalid authentication" in low or "failed to authenticate" in low)


def _is_confirmed_empty_worker(w: dict) -> bool:
    """0 items 但 worker 明确填写 null_finding_reason,视为 clean 结果。"""
    return (
        (w.get("items_count", 0) or 0) == 0
        and not w.get("error")
        and bool(w.get("empty_submission_confirmed"))
    )


def _read_session_events(session_file: Path) -> list | None:
    try:
        text = session_file.read_text(encoding="utf-8", errors="replace").strip()
        return [json.loads(line) for line in text.split("\n") if line]
    except (json.JSONDecodeError, OSError):
        return None


def _normalize_session_tag(tag) -> str:
    text = str(tag or "").strip().lower()
    aliases = {
        "load-test": "stress",
        "load_test": "stress",
        "pressure-test": "stress",
        "pressure_test": "stress",
        "压测": "stress",
    }
    return aliases.get(text, text)


def _session_tags(events: list) -> set[str]:
    started = next((e for e in events if e.get("type") == "review_started"), {})
    raw_tags = started.get("session_tags") or started.get("tags") or []
    if isinstance(raw_tags, str):
        raw_tags = [raw_tags]
    elif not isinstance(raw_tags, list):
        raw_tags = []

    tags = {_normalize_session_tag(tag) for tag in raw_tags}
    for key in ("session_kind", "run_kind"):
        if started.get(key):
            tags.add(_normalize_session_tag(started.get(key)))
    return {tag for tag in tags if tag}


def _is_stress_session(events: list) -> bool:
    started = next((e for e in events if e.get("type") == "review_started"), {})
    if "stress" in _session_tags(events):
        return True

    prd_name = str(started.get("prd_name") or "").strip().lower()
    reviewer = str(started.get("reviewer") or "").strip().lower()
    return prd_name.startswith("team-beta-stress-") or reviewer.startswith("stress-pm-")


def classify_session(workers_done: list) -> str:
    """把一次 session 分类为 ops/bug 分层结果:

    - "quota_exhausted": 所有 worker 都因配额耗尽失败 (ops 问题)
    - "auth_expired": 所有 worker 都因 401 OAuth 失效失败 (ops 问题, Round 15 新增)
    - "empty_bug": 所有 worker 都返回 0 items 且无 error (真·静默 bug)
    - "partial_silent": 部分 worker 静默,部分正常
    - "productive": 所有 worker 都出 items 且无 error
    - "error_other": 其他错误混合
    """
    if not workers_done:
        return "error_other"

    all_quota = all(_is_quota_error(w.get("error")) for w in workers_done)
    if all_quota:
        return "quota_exhausted"

    all_auth = all(_is_auth_error(w.get("error")) for w in workers_done)
    if all_auth:
        return "auth_expired"

    def _is_silent(w):
        return (
            (w.get("items_count", 0) or 0) == 0
            and not w.get("error")
            and not _is_confirmed_empty_worker(w)
        )

    def _is_productive(w):
        return (w.get("items_count", 0) or 0) > 0 and not w.get("error")

    def _is_healthy(w):
        return _is_productive(w) or _is_confirmed_empty_worker(w)

    silent_count = sum(1 for w in workers_done if _is_silent(w))
    healthy_count = sum(1 for w in workers_done if _is_healthy(w))

    if healthy_count == len(workers_done):
        return "productive"
    if silent_count == len(workers_done):
        return "empty_bug"
    if silent_count > 0 and healthy_count > 0:
        return "partial_silent"
    return "error_other"


def _error_fingerprint(err: str) -> str:
    """把 error 字符串归一化成 80 字符内的 fingerprint,便于聚合计数。

    剥离具体文件路径、时间戳、duration 等易变部分。
    """
    import re as _re
    if not err:
        return ""
    s = err.strip()
    # 去路径: C:\Users\... 或 /home/... 之类
    s = _re.sub(r"[A-Z]:\\[^\s'\"]+|/[a-z][^\s'\"]+", "<path>", s)
    # 去时间戳 / duration
    s = _re.sub(r"duration_ms\":\d+", "duration_ms:<n>", s)
    s = _re.sub(r"resets\s+\d+[ap]m[^\"']*", "resets <time>", s)
    # 限长
    return s[:80]


def _analyze_sessions(session_files: list, include_stress: bool = False) -> dict:
    """核心分析逻辑,给定一批 session jsonl 文件,返回统计字典.

    抽出这层是为了支持"全量 vs 最近 N 条"双口径对比。
    """
    if not session_files:
        return {"sessions": 0, "note": "no sessions found", "stress_sessions_excluded": 0}

    outcomes = Counter()
    worker_silent = Counter()
    worker_productive = Counter()
    worker_confirmed_empty = Counter()
    worker_errored = Counter()
    items_distribution = []

    # 新增指标
    flow_milestones = Counter()  # 每个 session 到达了哪些里程碑
    error_fingerprints = Counter()  # 非 quota 错误的聚合
    final_reviewer_total = 0
    final_reviewer_failed = 0

    # Round 2: 空提交重试 telemetry 聚合
    retry_triggered = 0  # 触发了 empty_retry 的 worker_done 计数
    retry_rescued = 0    # 触发后最终出了 items 的计数
    retry_kept_empty = 0 # 触发后仍空的计数
    retry_confirmed_empty = 0  # 触发后仍空但显式说明 clean 的计数
    retry_total_workers = 0  # 具备 empty_retry_used 字段的 worker_done 总数

    # Round 8: goshawk verdict 分布聚合
    goshawk_verdicts = Counter()
    goshawk_empty_retry_used = 0
    goshawk_instrumented = 0  # 带 verdict 字段的 final_reviewer_done 计数
    goshawk_failure_types = Counter()
    stress_sessions_excluded = 0

    for sf in session_files:
        events = _read_session_events(sf)
        if events is None:
            continue
        if not include_stress and _is_stress_session(events):
            stress_sessions_excluded += 1
            continue

        workers_done = [e for e in events if e.get("type") == "worker_done"]
        if not workers_done:
            continue

        outcome = classify_session(workers_done)
        outcomes[outcome] += 1

        # flow milestones: 记录该 session 最远走到哪一步
        event_types = {e.get("type") for e in events}
        for milestone in ("review_started", "workers_started", "checkpoint",
                          "final_reviewer_done", "review_completed"):
            if milestone in event_types:
                flow_milestones[milestone] += 1

        # final_reviewer 失败率 (检查 final_reviewer_done 是否有 error)
        for e in events:
            if e.get("type") == "final_reviewer_done":
                final_reviewer_total += 1
                failure_type = _classify_goshawk_failure_type(e)
                if failure_type != "success":
                    goshawk_failure_types[failure_type] += 1
                if e.get("error"):
                    final_reviewer_failed += 1
                    error_fingerprints[_error_fingerprint(e["error"])] += 1
                # Round 8: 聚合 verdict + empty_retry
                verdict = e.get("verdict")
                if verdict:
                    goshawk_instrumented += 1
                    goshawk_verdicts[verdict] += 1
                if e.get("empty_retry_used"):
                    goshawk_empty_retry_used += 1

        # worker 级统计: 只在非 ops 场景统计静默率
        if outcome not in ("quota_exhausted", "auth_expired"):
            items_sum = 0
            for w in workers_done:
                dim = w.get("dim", "?")
                count = w.get("items_count", 0) or 0
                confirmed_empty = _is_confirmed_empty_worker(w)
                if w.get("error"):
                    worker_errored[dim] += 1
                    error_fingerprints[_error_fingerprint(w["error"])] += 1
                elif confirmed_empty:
                    worker_confirmed_empty[dim] += 1
                elif count == 0:
                    worker_silent[dim] += 1
                else:
                    worker_productive[dim] += 1
                items_sum += count

                # Round 2: 聚合 empty_retry telemetry (字段可能为 None,代表旧数据)
                retry_flag = w.get("empty_retry_used")
                if retry_flag is not None:
                    retry_total_workers += 1
                    if retry_flag:
                        retry_triggered += 1
                        if count > 0:
                            retry_rescued += 1
                        else:
                            retry_kept_empty += 1
                            if confirmed_empty:
                                retry_confirmed_empty += 1
            items_distribution.append(items_sum)

    total = sum(outcomes.values())
    # Round 15: effective_consistency 剔除所有 ops 类问题 (quota + 401 auth)
    ops_issues = outcomes["quota_exhausted"] + outcomes.get("auth_expired", 0)
    non_ops = total - ops_issues

    effective_consistency = (
        outcomes["productive"] / non_ops if non_ops > 0 else 0
    )

    # per-worker silent_rate: 分母是"该 worker 成功跑完没 error 的次数"
    silent_rate = {}
    for dim in set(list(worker_silent) + list(worker_productive) + list(worker_confirmed_empty)):
        denom = worker_silent[dim] + worker_productive[dim] + worker_confirmed_empty[dim]
        silent_rate[dim] = worker_silent[dim] / denom if denom else 0

    items_sorted = sorted(items_distribution)
    median = items_sorted[len(items_sorted) // 2] if items_sorted else 0

    # flow dropout: 到达 review_started 的 session 里,有多少最终 review_completed
    completion_rate = (flow_milestones["review_completed"] / total) if total else 0
    checkpoint_rate = (flow_milestones["checkpoint"] / total) if total else 0

    final_reviewer_failure_rate = (
        final_reviewer_failed / final_reviewer_total if final_reviewer_total else 0
    )

    # Round 2: 空提交重试效果聚合
    retry_trigger_rate = (
        retry_triggered / retry_total_workers if retry_total_workers else 0
    )
    retry_rescue_rate = (
        retry_rescued / retry_triggered if retry_triggered else 0
    )

    return {
        "sessions": total,
        "outcomes": dict(outcomes),
        "stress_sessions_excluded": stress_sessions_excluded,
        "quota_hit_rate": round(outcomes["quota_exhausted"] / total, 3) if total else 0,
        "auth_expired_rate": round(outcomes.get("auth_expired", 0) / total, 3) if total else 0,
        "effective_consistency": round(effective_consistency, 3),
        "completion_rate": round(completion_rate, 3),
        "checkpoint_rate": round(checkpoint_rate, 3),
        "final_reviewer_failure_rate": round(final_reviewer_failure_rate, 3),
        "worker_silent_rate": {k: round(v, 3) for k, v in silent_rate.items()},
        "worker_confirmed_empty": dict(worker_confirmed_empty),
        "worker_errored": dict(worker_errored),
        "items_median": median,
        "flow_milestones": dict(flow_milestones),
        "error_fingerprints": dict(error_fingerprints.most_common(10)),
        # Round 2: 空提交重试聚合
        "empty_retry": {
            "instrumented_workers": retry_total_workers,
            "trigger_rate": round(retry_trigger_rate, 3),
            "rescue_rate": round(retry_rescue_rate, 3),
            "triggered": retry_triggered,
            "rescued": retry_rescued,
            "kept_empty": retry_kept_empty,
            "confirmed_empty": retry_confirmed_empty,
        },
        # Round 8: goshawk verdict 分布
        "goshawk": {
            "instrumented_sessions": goshawk_instrumented,
            "verdict_distribution": dict(goshawk_verdicts),
            "empty_retry_used_count": goshawk_empty_retry_used,
        },
        "goshawk_failure_types": dict(goshawk_failure_types),
    }


def collect_session_stats(recent_window: int = 20, include_stress: bool = False) -> dict:
    """扫描所有 workspace-*/output/sessions/*.jsonl,给出分层一致性指标.

    关键区分: quota_exhausted (ops) vs empty_bug (代码 bug) vs partial_silent (worker 稳定性)。
    effective_consistency 只计非 quota session,反映真实 harness 健康度。

    双口径输出 (2026-04-16):
    - all_time 维度: 全部 session 累积 (历史背景)
    - recent 维度: 最近 N 条 session (滑动窗口,反映近期修复效果)

    老数据容易拖累指标判断,两者对照才看得出"修了还是没修"。
    """
    session_files = list(ROOT.glob("workspace-*/output/sessions/*.jsonl"))
    if not session_files:
        return {"sessions": 0, "note": "no sessions found"}

    # 文件名格式 rev_<epoch_ts>_<uid>.jsonl,按文件名即按时间升序
    session_files.sort(key=lambda p: p.name)

    all_time = _analyze_sessions(session_files, include_stress=include_stress)
    if include_stress:
        recent_files = session_files[-recent_window:]
    else:
        recent_files = [
            sf for sf in session_files
            if (events := _read_session_events(sf)) is not None and not _is_stress_session(events)
        ][-recent_window:]
    recent = _analyze_sessions(recent_files, include_stress=include_stress)

    # 合并: 默认指标用 recent (更反映现状),同时保留 all_time 做对照
    out = dict(recent)
    out["recent_window"] = recent_window
    out["all_time"] = all_time
    out["stress_sessions_excluded"] = all_time.get("stress_sessions_excluded", 0)
    out["include_stress"] = include_stress
    return out


def format_report(git_info, test_info, code_info, session_info) -> str:
    """渲染 markdown."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [
        "# 啄木鸟项目状态 — 自动生成",
        "",
        f"> 生成时间: {now}",
        f"> 来源: git log + pytest + workspace-*/output/sessions",
        "> 本文件由 `scripts/generate_status.py` 生成,请勿手工编辑。",
        "",
        "## 代码规模",
        "",
        f"- 根目录 Python 文件: {code_info['file_count']} 个",
        f"- 根目录总行数: {code_info['total_lines']:,}",
        "",
        "## 测试状态",
        "",
        f"- 单测总数: **{test_info['collected']}**",
        "",
        f"## 最近 {git_info['days']} 天开发活动",
        "",
        f"- commit 数: **{git_info['commit_count']}**",
        "",
        "最近 10 条提交:",
        "",
        "| SHA | 日期 | 主题 |",
        "|-----|------|------|",
    ]
    for c in git_info["recent_commits"]:
        subj = c["subject"].replace("|", "\\|")
        lines.append(f"| `{c['sha']}` | {c['date']} | {subj} |")

    lines += [
        "",
        "## 真实运行指标 (evidence-based)",
        "",
    ]
    excluded_stress = session_info.get("stress_sessions_excluded", 0)
    if excluded_stress and not session_info.get("include_stress"):
        lines += [
            f"- 已排除压测 session: **{excluded_stress}** (默认不计入真实运行指标)",
            "",
        ]
    if session_info.get("sessions", 0) == 0:
        lines.append("- 尚无 session 数据")
    else:
        outcomes = session_info.get("outcomes", {})
        total = session_info["sessions"]
        all_time = session_info.get("all_time", {})
        window = session_info.get("recent_window", 20)

        # 双口径对照表 (核心创新: 老数据 vs 近况)
        if all_time and all_time.get("sessions", 0) != total:
            at_cons = all_time.get("effective_consistency", 0)
            lines += [
                f"- 累计 session: **{all_time.get('sessions', 0)}** (最近 {window} 条用于下列指标)",
                "",
                "### 口径对照 (recent vs all_time)",
                "",
                "| 指标 | 最近 {window} 条 | 全量历史 |".replace("{window}", str(window)),
                "|------|--------------|----------|",
                f"| 有效一致性 | {session_info['effective_consistency']:.1%} | {at_cons:.1%} |",
                f"| 配额耗尽率 | {session_info['quota_hit_rate']:.1%} | {all_time.get('quota_hit_rate', 0):.1%} |",
                f"| 完成率 | {session_info['completion_rate']:.1%} | {all_time.get('completion_rate', 0):.1%} |",
                f"| items 中位数 | {session_info['items_median']} | {all_time.get('items_median', 0)} |",
                "",
                "> recent 降 → 新 bug;recent 升 → 修复生效;只看 all_time 容易被老数据误导。",
                "",
            ]
        else:
            lines.append(f"- 累计 session: **{total}**")
            lines.append("")

        lines += [
            "Session 分类 (分层统计,避免 ops 噪声污染):",
            "",
            "| 类别 | 计数 | 占比 | 含义 |",
            "|------|------|------|------|",
            f"| productive | {outcomes.get('productive', 0)} | {outcomes.get('productive', 0)/total:.0%} | 所有 worker 都出 items,健康 |",
            f"| partial_silent | {outcomes.get('partial_silent', 0)} | {outcomes.get('partial_silent', 0)/total:.0%} | 部分 worker 静默,harness bug |",
            f"| empty_bug | {outcomes.get('empty_bug', 0)} | {outcomes.get('empty_bug', 0)/total:.0%} | 所有 worker 都静默,严重 bug |",
            f"| quota_exhausted | {outcomes.get('quota_exhausted', 0)} | {outcomes.get('quota_exhausted', 0)/total:.0%} | CLI 配额耗尽,ops 问题非 bug |",
            f"| auth_expired | {outcomes.get('auth_expired', 0)} | {outcomes.get('auth_expired', 0)/total:.0%} | CLI OAuth 401,ops 并发挤占 |",
            f"| error_other | {outcomes.get('error_other', 0)} | {outcomes.get('error_other', 0)/total:.0%} | 其他混合错误 |",
            "",
            f"- **有效一致性** (productive / 非 ops 的,剔除 quota+auth): **{session_info['effective_consistency']:.1%}**",
            f"- 配额耗尽占比: {session_info['quota_hit_rate']:.1%} (高 → 调整运行时段)",
            f"- 401 Auth 失效占比: {session_info.get('auth_expired_rate', 0):.1%} (高 → 避免多进程并发)",
            f"- items 中位数 (非 quota session): {session_info['items_median']}",
            "",
            "### Flow 完整性 (session 走完整条 pipeline 的比例)",
            "",
            f"- 完成率 (review_completed): {session_info['completion_rate']:.1%}",
            f"- checkpoint 率: {session_info['checkpoint_rate']:.1%}",
            f"- 苍鹰终审失败率 (final_reviewer_done with error): {session_info['final_reviewer_failure_rate']:.1%}",
            "",
            "### Worker 静默率 (仅统计非 quota 成功调用)",
            "",
            "| dimension | silent_rate | confirmed_empty |",
            "|-----------|-------------|-----------------|",
        ]
        confirmed_empty = session_info.get("worker_confirmed_empty", {})
        for dim, rate in sorted(session_info["worker_silent_rate"].items()):
            lines.append(f"| {dim} | {rate:.1%} | {confirmed_empty.get(dim, 0)} |")

        # 非 quota 错误 fingerprint (前 10 条,归一化聚合)
        fps = session_info.get("error_fingerprints", {})
        if fps:
            lines += [
                "",
                "### 错误指纹 (归一化聚合,揪出重复 bug)",
                "",
                "| 计数 | 指纹 (前 80 字) |",
                "|------|----------------|",
            ]
            for fp, count in fps.items():
                fp_display = fp.replace("|", "\\|").replace("\n", " ")
                lines.append(f"| {count} | `{fp_display}` |")

        # Round 8: goshawk verdict 分布
        goshawk = session_info.get("goshawk", {})
        if goshawk.get("instrumented_sessions", 0) > 0:
            lines += [
                "",
                "### 苍鹰 verdict 分布 (Round 8)",
                "",
                f"- 已埋点 session: {goshawk['instrumented_sessions']}",
                f"- empty_retry 触发次数: {goshawk['empty_retry_used_count']}",
                "",
                "| verdict | 计数 | 含义 |",
                "|---------|------|------|",
            ]
            dist = goshawk.get("verdict_distribution", {})
            verdict_meaning = {
                "REVIEWED": "苍鹰有输出(误报/漏报/冲突 >= 1),正常工作",
                "EMPTY_APPROVAL": "苍鹰 tool 调了但全空,显式'三无'背书",
                "SILENT": "苍鹰 tool 根本没调成功,降级失败",
                "TIMEOUT": "苍鹰超时,pipeline 继续无苍鹰加持",
                "UNKNOWN": "埋点字段缺失(老数据)",
            }
            for v, cnt in sorted(dist.items(), key=lambda x: -x[1]):
                lines.append(f"| {v} | {cnt} | {verdict_meaning.get(v, '?')} |")

        failure_types = session_info.get("goshawk_failure_types", {})
        if failure_types:
            lines += [
                "",
                "### 苍鹰失败类型分布",
                "",
                "| type | 计数 |",
                "|------|------|",
            ]
            for failure_type, count in sorted(failure_types.items(), key=lambda item: (-item[1], item[0])):
                lines.append(f"| {failure_type} | {count} |")

        # Round 2: 空提交重试 telemetry 消费
        retry = session_info.get("empty_retry", {})
        if retry.get("instrumented_workers", 0) > 0:
            lines += [
                "",
                "### 空提交重试分支 (Round 2)",
                "",
                f"- 已埋点 worker 调用数: {retry['instrumented_workers']}",
                f"- 触发率: **{retry['trigger_rate']:.1%}** (应接近 data_quality/quality 静默率 ≈ 50%)",
                f"- 救回率 (触发后最终出了 items): **{retry['rescue_rate']:.1%}**",
                f"- 分解: triggered={retry['triggered']} rescued={retry['rescued']} "
                f"kept_empty={retry['kept_empty']} confirmed_empty={retry.get('confirmed_empty', 0)}",
                "",
                "> 救回率 < 40% → retry prompt 无效,考虑改进提示词;",
                "> 救回率 > 70% → 修复有效;",
                "> instrumented_workers = 0 → 新代码还没跑,需要 shadow_run 或线上 session。",
            ]
        elif session_info.get("sessions", 0) > 0:
            lines += [
                "",
                "### 空提交重试分支 (Round 2)",
                "",
                "- [pending] 尚无埋点数据 — 所有 session 都是修复前的,需要跑新 session 才能看到 retry 效果",
            ]

    lines += [
        "",
        "## 稳定性门禁",
        "",
    ]
    cons = session_info.get("effective_consistency", 0)
    if session_info.get("sessions", 0) == 0:
        lines.append("- [N/A] 无 session 数据")
    elif session_info.get("sessions", 0) - session_info.get("outcomes", {}).get("quota_exhausted", 0) == 0:
        lines.append("- [N/A] 所有 session 都是 quota 耗尽,没有有效数据判定")
    elif cons >= 0.6:
        lines.append(f"- [PASS] 有效一致性 {cons:.1%} ≥ 60%")
    else:
        lines.append(f"- [FAIL] 有效一致性 {cons:.1%} < 60% (目标: 60%+)")
    if session_info.get("sessions", 0) > 0:
        goshawk_failure_rate = session_info.get("final_reviewer_failure_rate", 0)
        if goshawk_failure_rate <= 0.15:
            lines.append(f"- [PASS] 苍鹰失败率 {goshawk_failure_rate:.1%} ≤ 15%")
        else:
            lines.append(f"- [FAIL] 苍鹰失败率 {goshawk_failure_rate:.1%} > 15%")

    lines += [
        "",
        "---",
        "",
        "> 手写版本 (HARNESS_MATURITY.md / PRODUCTION_READINESS.md) 已废弃,",
        "> 评估以本文件为准。如需新增维度,改 `scripts/generate_status.py`。",
    ]
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description="生成 STATUS.md")
    parser.add_argument("--dry-run", action="store_true", help="只打印不写文件")
    parser.add_argument("--out", default=str(ROOT / "STATUS.md"), help="输出路径")
    parser.add_argument("--days", type=int, default=14, help="git 活动窗口 (天)")
    parser.add_argument("--recent-window", type=int, default=20,
                        help="recent 口径的 session 数,默认最近 20 条")
    parser.add_argument("--include-stress", action="store_true",
                        help="包含压测 session;默认排除,避免污染真实运行指标")
    args = parser.parse_args()

    git_info = collect_git_activity(args.days)
    test_info = collect_test_status()
    code_info = collect_code_stats()
    session_info = collect_session_stats(
        recent_window=args.recent_window,
        include_stress=args.include_stress,
    )

    report = format_report(git_info, test_info, code_info, session_info)

    if args.dry_run:
        print(report)
    else:
        Path(args.out).write_text(report, encoding="utf-8")
        print(f"[ok] 已生成 {args.out}")
        print(f"     session={session_info.get('sessions', 0)} "
              f"tests={test_info['collected']} "
              f"effective_consistency={session_info.get('effective_consistency', 0):.1%} "
              f"quota_hit={session_info.get('quota_hit_rate', 0):.1%}")


if __name__ == "__main__":
    main()
