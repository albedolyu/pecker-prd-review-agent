"""seed_ground_truth.py — 从 consistency eval 原始结果生成 ground truth 骨架.

为什么做 (gate 3 质量证据零起点问题): PM 要人工标注 20-30 条评审项很重, 从头开始
会拖很久上不了. 这里把 consistency_eval 跑出的 `all_items` 抽出唯一化骨架
(按 rule_id + location 去重), 每条预标 accept=True 让 PM 只需**反过来标 reject**
或微调.

骨架有了后, PM 在对一份 PRD 的评审报告, 边看边把误报 mark 成 is_true_positive=False,
其他字段 (action / severity) 按预标. 20 分钟能过完 30 条. 比零起点快 4-5 倍.

用法:
  python scripts/seed_ground_truth.py eval/results/consistency_XXX_raw.json
  → eval/ground_truth/seed_XXX_<reviewer>_<ts>.json (PM 后续编辑)

不覆盖已有 ground truth; 跑多次追加 timestamp.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List


PROJECT_ROOT = Path(__file__).parent.parent.resolve()


def _dedup_items_by_rule_location(all_items: List[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """多轮 items 按 (rule_id, location 前 40 字) 去重. 返回合并后的 item 列表.

    保留首次出现的 item 作为代表(items 文本会在多轮间微调, 骨架不追求字面一致)."""
    seen = {}
    order = []
    for run_items in all_items:
        if not isinstance(run_items, list):
            continue
        for it in run_items:
            if not isinstance(it, dict):
                continue
            key = (
                (it.get("rule_id") or "").strip(),
                (it.get("location") or "")[:40].strip(),
            )
            if key in seen or key == ("", ""):
                continue
            seen[key] = it
            order.append(key)
    return [seen[k] for k in order]


def generate_seed(raw_json_path: Path, reviewer: str = "pm-to-fill") -> Dict[str, Any]:
    """读 consistency raw JSON, 返回 ground truth 骨架 dict."""
    with open(raw_json_path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    prd_name = raw.get("prd_name", raw_json_path.stem)
    all_items = raw.get("all_items", [])
    merged = _dedup_items_by_rule_location(all_items)

    # 预标: 全 accept, PM 自己 reject 明显误报
    gt_items = []
    for i, it in enumerate(merged, 1):
        gt_items.append({
            "id": it.get("id") or f"R-{i:03d}",
            "rule_id": it.get("rule_id", ""),
            "location": it.get("location", ""),
            "issue_preview": (it.get("issue") or "")[:120],
            "severity": it.get("severity", ""),
            "action": "accept",                # PM 改这里: accept / reject / edit
            "is_true_positive": True,          # PM 改这里: 误报就 False
            "pm_note": "",                     # PM 可选补注
        })

    return {
        "prd_name": prd_name,
        "source": str(raw_json_path.name),
        "reviewer": reviewer,
        "ts": int(time.time()),
        "seeded_at": time.strftime("%Y-%m-%d %H:%M"),
        "note": (
            "骨架: 每条预标 accept=True + is_true_positive=True. PM 过一遍, "
            "误报改 is_true_positive=False, 接受的保留, 有改动的 action=edit + pm_note."
        ),
        "items": gt_items,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("raw_json", help="consistency eval 的 _raw.json 路径")
    parser.add_argument("--reviewer", default="pm-to-fill",
                        help="PM 名字, 默认 pm-to-fill 作占位")
    parser.add_argument("--output", help="输出路径, 默认 eval/ground_truth/seed_<prd>_<reviewer>_<ts>.json")
    args = parser.parse_args()

    raw_path = Path(args.raw_json)
    if not raw_path.is_file():
        print(f"✗ 找不到: {raw_path}", file=sys.stderr)
        return 1

    seed = generate_seed(raw_path, args.reviewer)

    if args.output:
        out_path = Path(args.output)
    else:
        safe_prd = seed["prd_name"].replace("/", "_").replace("\\", "_")[:50]
        out_dir = PROJECT_ROOT / "eval" / "ground_truth"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"seed_{safe_prd}_{args.reviewer}_{seed['ts']}.json"

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(seed, f, ensure_ascii=False, indent=2)

    msg = (
        f"[OK] 骨架已生成: {out_path}\n"
        f"     items 去重后: {len(seed['items'])} 条\n"
        f"     下一步: PM 打开此文件, 把误报项的 is_true_positive 改成 false"
    )
    try:
        print(msg)
    except UnicodeEncodeError:
        sys.stdout.buffer.write(msg.encode("utf-8", errors="replace"))
        sys.stdout.buffer.write(b"\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
