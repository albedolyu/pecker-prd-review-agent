"""R19: rule_performance_history 污染清洗工具

根据 docs/RULE_PERF_CLEANUP.md 的诊断逻辑，把 CLI 配额 bug 时代产生的
伪污染规则 stats 重置为中性值，保留 history 条目但加 contaminated 标记。

为什么需要: 2026-04-16 发现 workspace-对外投资 的 rule_performance_history.json
里 7/15 条规则呈现"0 confirmed, 全 rejected"特征。这些数据极可能是用户在
配额耗尽的 0-items 伪成功报告上被迫 reject all 产生的，反哺 Worker prompt 时
给出错误信号（"这些规则被频繁驳回，少报"）。

用法:
    # dry-run 只打印分类结果不改文件
    python -m scripts.cleanup_rule_perf --workspace workspace-对外投资

    # --confirm 真正清洗(会生成 .bak 备份)
    python -m scripts.cleanup_rule_perf --workspace workspace-对外投资 --confirm

    # 扫描所有 workspace 做 dry-run
    python -m scripts.cleanup_rule_perf --all
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Tuple


def classify(rid: str, entry: Dict[str, Any]) -> Tuple[str, str]:
    """按启发式规则分类

    Returns:
        (category, reason)
        category ∈ {"CONTAMINATED", "LIKELY_CONTAMINATED", "TRUE_NOISE",
                    "EFFECTIVE", "MISS_HEAVY", "UNTRIGGERED", "UNKNOWN"}
    """
    stats = entry.get("stats", {}) or {}
    total = stats.get("total", 0)
    conf = stats.get("confirmed", 0)
    rej = stats.get("rejected", 0)
    miss = stats.get("missed", 0)
    is_noisy = entry.get("is_noisy", False)

    if total == 0:
        return "UNTRIGGERED", "从未被评审命中,存在性存疑"
    if conf == 0 and rej > 0 and total < 10:
        return "CONTAMINATED", f"0 confirmed + {rej} rejected 小样本,疑似配额 bug 伪评审污染"
    if conf == 0 and rej >= 4:
        return "LIKELY_CONTAMINATED", f"0 confirmed + {rej} rejected,疑似污染"
    if miss > conf and miss > 3:
        return "MISS_HEAVY", f"{miss} missed > {conf} confirmed,规则定义可能过严或描述不清"
    if is_noisy and conf > 0:
        return "TRUE_NOISE", f"有 {conf} 次 confirmed 历史仍被标 noisy,真噪声"
    if conf > rej:
        return "EFFECTIVE", f"{conf} confirmed > {rej} rejected,有效规则"
    return "UNKNOWN", "无法明确分类"


def reset_stats(entry: Dict[str, Any], reason: str) -> Dict[str, Any]:
    """重置一条规则的 stats 到中性值,保留 history 元信息"""
    name = entry.get("name", "")
    history = entry.get("history", []) or []
    # 给每条 history 追加 contaminated 标记（如果还没标）
    for h in history:
        if isinstance(h, dict):
            h.setdefault("contaminated", True)
            h.setdefault("cleanup_reason", reason[:80])
    return {
        "name": name,
        "history": history,
        "stats": {"confirmed": 0, "rejected": 0, "missed": 0, "total": 0},
        "rejection_rate": 0.0,
        "impact_score": 0.5,  # 中性
        "is_noisy": False,
        "cleaned_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "cleaned_reason": reason[:200],
    }


def scan_workspace(ws_path: Path, confirm: bool = False) -> Dict[str, Any]:
    """扫描并（可选）清洗一个 workspace 的 rule_performance_history

    Returns: summary dict
    """
    hist_path = ws_path / "output" / "rule_performance_history.json"
    if not hist_path.is_file():
        return {"workspace": ws_path.name, "status": "no_history"}

    with open(hist_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    summary: Dict[str, List[str]] = {
        "CONTAMINATED": [],
        "LIKELY_CONTAMINATED": [],
        "TRUE_NOISE": [],
        "EFFECTIVE": [],
        "MISS_HEAVY": [],
        "UNTRIGGERED": [],
        "UNKNOWN": [],
    }
    details: List[Tuple[str, str, str]] = []

    for rid, entry in data.items():
        if not isinstance(entry, dict):
            continue
        category, reason = classify(rid, entry)
        summary[category].append(rid)
        details.append((rid, category, reason))

    # 打印报告
    print(f"\n=== {ws_path.name} ===")
    print(f"{'rule_id':12} {'category':22} reason")
    print("-" * 90)
    for rid, cat, reason in sorted(details, key=lambda x: x[0]):
        print(f"{rid:12} {cat:22} {reason}")
    print()
    for cat, rids in summary.items():
        if rids:
            print(f"  {cat}: {len(rids)} — {rids}")

    to_clean = summary["CONTAMINATED"] + summary["LIKELY_CONTAMINATED"]

    if not confirm:
        print(f"\n[DRY-RUN] 会清洗 {len(to_clean)} 条规则,传 --confirm 实际执行")
        return {
            "workspace": ws_path.name,
            "total_rules": len(data),
            "would_clean": to_clean,
            "summary": {k: len(v) for k, v in summary.items()},
        }

    if not to_clean:
        print(f"[无需清洗]")
        return {"workspace": ws_path.name, "status": "nothing_to_clean"}

    # 备份
    ts = int(time.time())
    bak_path = hist_path.with_suffix(f".json.bak_{ts}")
    shutil.copy(hist_path, bak_path)
    print(f"[备份] 原文件 → {bak_path.name}")

    # 清洗
    for rid in to_clean:
        _, reason = classify(rid, data[rid])
        data[rid] = reset_stats(data[rid], reason)

    with open(hist_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"[完成] 已清洗 {len(to_clean)} 条规则")
    return {
        "workspace": ws_path.name,
        "status": "cleaned",
        "cleaned": to_clean,
        "backup": bak_path.name,
    }


def main():
    parser = argparse.ArgumentParser(
        description="rule_performance_history 污染清洗 (详见 docs/RULE_PERF_CLEANUP.md)"
    )
    parser.add_argument("--workspace", type=str, help="workspace 目录名,如 workspace-对外投资")
    parser.add_argument("--all", action="store_true", help="扫描所有 workspace (dry-run only)")
    parser.add_argument("--confirm", action="store_true", help="真正执行清洗(默认 dry-run)")
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parent.parent

    if args.all:
        if args.confirm:
            print("[错误] --all 模式禁用 --confirm(避免一次性破坏多份数据),请单独指定 --workspace")
            sys.exit(1)
        workspaces = [
            p for p in project_root.iterdir() if p.is_dir() and p.name.startswith("workspace")
        ]
        for ws in workspaces:
            scan_workspace(ws, confirm=False)
        return

    if not args.workspace:
        print("[错误] 需指定 --workspace 或 --all")
        parser.print_help()
        sys.exit(1)

    ws_path = project_root / args.workspace
    if not ws_path.is_dir():
        print(f"[错误] workspace 不存在: {ws_path}")
        sys.exit(1)

    scan_workspace(ws_path, confirm=args.confirm)


if __name__ == "__main__":
    main()
