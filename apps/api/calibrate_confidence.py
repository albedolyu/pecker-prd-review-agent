"""
Confidence Score 校准工具 — 缺失 ⑦ 闭环

跑过去所有 workspace 的历史评审数据,统计:
- 每个 evidence_type (A/B/C) 在 cuckoo verify 的真实通过率
- 每个 evidence_type 的真实 PM 接受率 (status=confirmed/accepted)

输出建议的 EVIDENCE_CONFIDENCE_BASE 常量,让 review.confidence.compute_confidence
从「先验常量」变成「后验实测」。

运行方式:
    # 跑所有 workspace
    python calibrate_confidence.py

    # 跑指定 workspace
    python calibrate_confidence.py --workspace workspace-sample

    # 写回 review/confidence.py (默认只打印)
    python calibrate_confidence.py --apply

输出:
    calibration_report.json
    控制台 markdown 表格
"""

import argparse
import glob
import json
import os
import sys
from collections import defaultdict
from datetime import datetime


def _find_workspaces(root="."):
    """找所有 workspace-* 目录"""
    return sorted([
        d for d in os.listdir(root)
        if os.path.isdir(d) and d.startswith("workspace-")
    ])


def _load_items_files(workspace):
    """加载 workspace/output/review_items_*.json"""
    pattern = os.path.join(workspace, "output", "review_items_*.json")
    files = glob.glob(pattern)
    all_items = []
    for f in sorted(files):
        try:
            with open(f, encoding="utf-8") as fp:
                items = json.load(fp)
                for it in items:
                    it["_source_file"] = f
                    it["_workspace"] = workspace
                all_items.extend(items)
        except (json.JSONDecodeError, OSError):
            continue
    return all_items


def calibrate(workspaces, sample_size_min=5):
    """对所有 items 做校准统计

    Returns:
        {
            "by_type": {
                "A": {"total": int, "verified": int, "confirmed": int,
                       "verify_rate": float, "accept_rate": float, "samples": list},
                "B": ...,
                "C": ...,
            },
            "current_base": {"A": 0.9, ...},
            "suggested_base": {"A": float, ...},
            "sample_size_warning": [...],  # 样本太少的类型
        }
    """
    by_type = defaultdict(lambda: {
        "total": 0,
        "verified": 0,        # cuckoo verify 通过
        "confirmed": 0,        # PM 接受
        "samples": [],
    })

    for ws in workspaces:
        items = _load_items_files(ws)
        for it in items:
            ev_type = (it.get("evidence_type") or "").strip().upper() or "(空)"
            verification_status = (it.get("verification_status") or "").lower()
            pm_status = (it.get("status") or "").lower()

            stats = by_type[ev_type]
            stats["total"] += 1
            if verification_status == "verified":
                stats["verified"] += 1
            if pm_status in ("confirmed", "accepted", "y"):
                stats["confirmed"] += 1
            stats["samples"].append({
                "id": it.get("id"),
                "workspace": it.get("_workspace"),
                "verification_status": verification_status or None,
                "pm_status": pm_status or None,
            })

    # 计算比率
    for ev_type, stats in by_type.items():
        stats["verify_rate"] = stats["verified"] / stats["total"] if stats["total"] else 0.0
        stats["accept_rate"] = stats["confirmed"] / stats["total"] if stats["total"] else 0.0
        # 不在 console 输出 raw samples
        del stats["samples"]

    # 当前 review.confidence 的常量
    current_base = {"A": 0.9, "B": 0.8, "C": 0.5, "(空)": 0.4}

    # 建议值: 用 verify_rate 作为后验下限,如果 PM accept_rate 有数据则取两者均值
    suggested = {}
    warnings = []
    for ev_type in ("A", "B", "C"):
        stats = by_type.get(ev_type, {})
        total = stats.get("total", 0)
        if total < sample_size_min:
            warnings.append(f"{ev_type} 类样本仅 {total} 条 (< {sample_size_min}),建议保留当前值")
            suggested[ev_type] = current_base.get(ev_type, 0.5)
            continue
        verify = stats.get("verify_rate", 0)
        accept = stats.get("accept_rate", 0)
        if accept > 0:
            # 两者都有数据,加权平均 (PM 接受占大权重)
            suggested[ev_type] = round(0.3 * verify + 0.7 * accept, 2)
        else:
            # 只有 verify 数据 (PM 决策没回写)
            suggested[ev_type] = round(verify, 2)

    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "workspaces_scanned": workspaces,
        "by_type": dict(by_type),
        "current_base": current_base,
        "suggested_base": suggested,
        "sample_size_warning": warnings,
    }


def print_report(result):
    """打印 markdown 表格报告"""
    print()
    print(f"# Confidence Score 校准报告")
    print()
    print(f"生成时间: {result['generated_at']}")
    print(f"扫描 workspace: {', '.join(result['workspaces_scanned'])}")
    print()
    print("## 历史样本统计")
    print()
    print("| evidence_type | 样本数 | verify 通过率 | PM 接受率 | 当前 base | 建议 base |")
    print("|---|---|---|---|---|---|")

    for ev_type in ("A", "B", "C", "(空)"):
        stats = result["by_type"].get(ev_type, {})
        total = stats.get("total", 0)
        if total == 0:
            continue
        vr = stats.get("verify_rate", 0)
        ar = stats.get("accept_rate", 0)
        cur = result["current_base"].get(ev_type, "-")
        sug = result["suggested_base"].get(ev_type, "-")
        ar_str = f"{ar:.0%}" if ar > 0 else "(无 PM 数据)"
        print(f"| **{ev_type}** | {total} | {vr:.0%} | {ar_str} | {cur} | **{sug}** |")

    if result["sample_size_warning"]:
        print()
        print("## ⚠️ 样本不足警告")
        for w in result["sample_size_warning"]:
            print(f"- {w}")

    print()
    print("## 建议代码改动")
    print()
    print("```python")
    print("# review/confidence.py")
    print("EVIDENCE_CONFIDENCE_BASE = {")
    for ev_type in ("A", "B", "C"):
        sug = result["suggested_base"].get(ev_type, 0.5)
        print(f'    "{ev_type}": {sug},  # was {result["current_base"].get(ev_type, "?")}')
    print('    "":  0.4,')
    print("}")
    print("```")
    print()


def apply_to_parser(suggested):
    """把 suggested base 写回 review/confidence.py"""
    confidence_file = os.path.join("review", "confidence.py")
    if not os.path.isfile(confidence_file):
        print(f"[error] {confidence_file} 不存在,无法写回")
        return False

    with open(confidence_file, encoding="utf-8") as f:
        content = f.read()

    # 查找 EVIDENCE_CONFIDENCE_BASE 字典
    import re
    pattern = re.compile(
        r'(EVIDENCE_CONFIDENCE_BASE\s*=\s*\{)([^\}]+)(\})',
        re.MULTILINE
    )
    m = pattern.search(content)
    if not m:
        print(f"[error] 在 {confidence_file} 找不到 EVIDENCE_CONFIDENCE_BASE 定义")
        return False

    new_dict = '\n'
    for ev_type in ("A", "B", "C"):
        sug = suggested.get(ev_type, 0.5)
        new_dict += f'    "{ev_type}": {sug},\n'
    new_dict += '    "":  0.4,  # 未标注依据类型的保守扣分\n'

    new_content = content.replace(m.group(0), f"{m.group(1)}{new_dict}{m.group(3)}")

    with open(confidence_file, "w", encoding="utf-8") as f:
        f.write(new_content)

    print(f"[apply] 已写回 {confidence_file}")
    return True


def main():
    parser = argparse.ArgumentParser(
        description="Confidence Score 校准工具 (关闭 ⑦ 反馈闭环缺失)"
    )
    parser.add_argument("--workspace", default=None, help="只跑指定 workspace,默认全部")
    parser.add_argument("--apply", action="store_true", help="直接写回 review/confidence.py")
    parser.add_argument("--output", default="calibration_report.json", help="输出 JSON 路径")
    parser.add_argument("--sample-min", type=int, default=5, help="样本数下限")
    args = parser.parse_args()

    if args.workspace:
        workspaces = [args.workspace]
    else:
        workspaces = _find_workspaces(".")

    if not workspaces:
        print("[error] 找不到 workspace-* 目录")
        return 1

    result = calibrate(workspaces, sample_size_min=args.sample_min)
    print_report(result)

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"[output] {args.output}")

    if args.apply:
        apply_to_parser(result["suggested_base"])

    return 0


if __name__ == "__main__":
    sys.exit(main())
