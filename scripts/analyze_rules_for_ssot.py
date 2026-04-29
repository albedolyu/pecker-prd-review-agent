#!/usr/bin/env python
"""啄木鸟 v2 SSOT 准备脚本 — 扫所有 workspace, 输出汇总 + 高频规则候选.

输入:
  - workspace*/review-rules/review-checklist.yaml
  - workspace*/output/review_items_*.json (历史 finding)

输出 (stdout + 落盘):
  - _ssot_rule_inventory.json: 全量 rule 表
  - _ssot_rule_frequency.json: 引用频次 / retract+downgrade / 跨 ws 数
  - _ssot_upgrade_candidates.json: 25-30 条候选清单

兼容 Windows GBK 控制台 (safe_print).
"""

from __future__ import annotations

import json
import os
import sys
from collections import defaultdict
from typing import Any

import yaml

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)


def safe_print(text: str) -> None:
    try:
        print(text)
    except UnicodeEncodeError:
        print(text.encode("gbk", errors="replace").decode("gbk", errors="replace"))


def find_workspaces(root: str) -> list[str]:
    out = []
    for name in os.listdir(root):
        if not name.startswith("workspace"):
            continue
        p = os.path.join(root, name)
        if not os.path.isdir(p):
            continue
        rules = os.path.join(p, "review-rules", "review-checklist.yaml")
        if os.path.isfile(rules):
            out.append(p)
    return sorted(out)


def load_yaml(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception as e:
        safe_print(f"[warn] load fail {path}: {e}")
        return {}


def is_upgraded(rule: dict) -> bool:
    """L3 升级判定: 至少有 positive_example 或 negative_example 或 fire_when 之一."""
    return bool(
        rule.get("positive_example")
        or rule.get("negative_example")
        or rule.get("fire_when")
    )


def collect_inventory(workspaces: list[str]) -> dict[str, Any]:
    inventory: dict[str, list] = defaultdict(list)  # rule_id → list of (ws, rule_dict)
    for ws in workspaces:
        ws_name = os.path.basename(ws)
        yaml_path = os.path.join(ws, "review-rules", "review-checklist.yaml")
        data = load_yaml(yaml_path)
        for rule in data.get("rules", []) or []:
            rid = (rule.get("id") or rule.get("rule_id") or "").strip()
            if not rid:
                continue
            inventory[rid].append({
                "workspace": ws_name,
                "name": rule.get("name", ""),
                "severity": rule.get("severity", ""),
                "impact_score": rule.get("impact_score", 0),
                "description": rule.get("description", ""),
                "upgraded": is_upgraded(rule),
                "raw": rule,
            })
    return dict(inventory)


def detect_inconsistencies(inventory: dict[str, list]) -> list[dict]:
    """同 rule_id 在不同 workspace 内容是否一致 (除了 upgrade 字段)."""
    issues = []
    for rid, copies in inventory.items():
        if len(copies) <= 1:
            continue
        # 把 raw 里 example/fire_when 等 L3 字段剥掉, 比较核心字段
        cores = []
        for c in copies:
            r = c["raw"]
            cores.append((
                r.get("name", ""),
                r.get("severity", ""),
                r.get("description", "").strip(),
                r.get("impact_score", None),
            ))
        if len(set(cores)) > 1:
            issues.append({
                "rule_id": rid,
                "variants": [
                    {"workspace": c["workspace"], "core": cores[i]}
                    for i, c in enumerate(copies)
                ],
            })
    return issues


def scan_review_items(root: str) -> dict[str, dict]:
    """扫所有 workspace*/output/**/review_items_*.json, 算频次."""
    stats: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"total": 0, "retract": 0, "downgrade": 0, "ws_set": set()}
    )

    for entry in os.listdir(root):
        if not entry.startswith("workspace"):
            continue
        ws_name = entry
        out_dir = os.path.join(root, entry, "output")
        if not os.path.isdir(out_dir):
            continue
        # 递归找 review_items_*.json (含 _archive_*)
        for dirpath, _, filenames in os.walk(out_dir):
            for fn in filenames:
                if not (fn.startswith("review_items") and fn.endswith(".json")):
                    continue
                full = os.path.join(dirpath, fn)
                try:
                    with open(full, "r", encoding="utf-8") as f:
                        items = json.load(f)
                except Exception:
                    continue
                if not isinstance(items, list):
                    continue
                for it in items:
                    if not isinstance(it, dict):
                        continue
                    rid = it.get("rule_id", "")
                    if not rid:
                        continue
                    s = stats[rid]
                    s["total"] += 1
                    s["ws_set"].add(ws_name)
                    # 状态判定: 多种字段名兼容
                    review_state = (
                        it.get("review_state")
                        or it.get("status")
                        or it.get("eagle_review", {}).get("decision", "")
                        or ""
                    ).lower()
                    if "retract" in review_state or "drop" in review_state:
                        s["retract"] += 1
                    elif "downgrade" in review_state or "demote" in review_state:
                        s["downgrade"] += 1
    # 转换 set → list 方便序列化
    out = {}
    for rid, s in stats.items():
        out[rid] = {
            "total": s["total"],
            "retract": s["retract"],
            "downgrade": s["downgrade"],
            "ws_count": len(s["ws_set"]),
            "ws_list": sorted(s["ws_set"]),
        }
    return out


def select_candidates(
    inventory: dict[str, list], freq: dict[str, dict], target: int = 28
) -> list[dict]:
    """选 25-30 条候选: must/should + 未升级 + 高频/跨 ws 优先."""
    cands = []
    for rid, copies in inventory.items():
        # 只看任一 workspace 都没升级的规则 (包含还没全部升级的)
        upgraded_anywhere = any(c["upgraded"] for c in copies)
        if upgraded_anywhere:
            # 已经在某个 ws 升级 → 跳过 (eg RC-004/005/010/013)
            continue
        # 取最完整的副本 (有 description 的)
        primary = max(copies, key=lambda c: len(c.get("description", "")))
        sev = primary["severity"]
        if sev not in ("must", "should"):
            continue
        f = freq.get(rid, {"total": 0, "retract": 0, "downgrade": 0, "ws_count": 0})
        score = (
            f["total"] * 1.0
            + f["ws_count"] * 5.0
            + (1 if sev == "must" else 0) * 3.0
            + primary.get("impact_score", 0) * 2.0
        )
        cands.append({
            "rule_id": rid,
            "name": primary["name"],
            "severity": sev,
            "description": primary["description"],
            "impact_score": primary.get("impact_score", 0),
            "freq_total": f["total"],
            "freq_retract": f["retract"],
            "freq_downgrade": f["downgrade"],
            "freq_ws_count": f["ws_count"],
            "rank_score": round(score, 3),
            "in_workspaces": [c["workspace"] for c in copies],
        })
    cands.sort(key=lambda c: c["rank_score"], reverse=True)
    return cands[:target]


def main() -> int:
    workspaces = find_workspaces(_ROOT)
    safe_print(f"[1/4] 发现 {len(workspaces)} 个 workspace 含 review-checklist.yaml:")
    for w in workspaces:
        safe_print(f"      {os.path.basename(w)}")

    inventory = collect_inventory(workspaces)
    safe_print(f"\n[2/4] 全量规则: {len(inventory)} 个唯一 rule_id, "
               f"{sum(len(v) for v in inventory.values())} 个 workspace 副本")

    upgraded_rids = sorted(
        rid for rid, copies in inventory.items() if any(c["upgraded"] for c in copies)
    )
    safe_print(f"      已 L3 升级: {len(upgraded_rids)} 条 — {upgraded_rids}")

    inconsistencies = detect_inconsistencies(inventory)
    safe_print(f"      跨 workspace 不一致: {len(inconsistencies)} 条")
    for inc in inconsistencies[:5]:
        safe_print(f"      ! {inc['rule_id']}: {len({tuple(v['core']) for v in inc['variants']})} 种核心变体")

    safe_print("\n[3/4] 扫历史 review_items_*.json …")
    freq = scan_review_items(_ROOT)
    total_findings = sum(f["total"] for f in freq.values())
    safe_print(f"      累计 {total_findings} 条 finding 引用了 {len(freq)} 个 rule_id")

    top = sorted(freq.items(), key=lambda kv: kv[1]["total"], reverse=True)[:15]
    safe_print("      TOP15 引用频次:")
    for rid, s in top:
        safe_print(f"      {rid:<10} total={s['total']:<4} ws={s['ws_count']} "
                   f"retract={s['retract']} downgrade={s['downgrade']}")

    safe_print("\n[4/4] 选 28 条升级候选 …")
    cands = select_candidates(inventory, freq, target=28)
    safe_print(f"      选出 {len(cands)} 条候选")
    for c in cands[:20]:
        safe_print(f"      {c['rule_id']:<8} [{c['severity']:<6}] "
                   f"freq={c['freq_total']:<3} ws={c['freq_ws_count']} "
                   f"score={c['rank_score']:<6} — {c['name']}")

    # 落盘
    out_dir = os.path.join(_ROOT, "_ssot_analysis")
    os.makedirs(out_dir, exist_ok=True)

    inv_export = {
        rid: {
            "copies_count": len(copies),
            "upgraded_anywhere": any(c["upgraded"] for c in copies),
            "in_workspaces": [c["workspace"] for c in copies],
            "primary": {
                k: v for k, v in copies[0].items() if k != "raw"
            },
        }
        for rid, copies in inventory.items()
    }
    with open(os.path.join(out_dir, "_ssot_rule_inventory.json"), "w", encoding="utf-8") as f:
        json.dump(inv_export, f, ensure_ascii=False, indent=2)
    with open(os.path.join(out_dir, "_ssot_rule_frequency.json"), "w", encoding="utf-8") as f:
        json.dump(freq, f, ensure_ascii=False, indent=2)
    with open(os.path.join(out_dir, "_ssot_upgrade_candidates.json"), "w", encoding="utf-8") as f:
        json.dump(cands, f, ensure_ascii=False, indent=2)
    with open(os.path.join(out_dir, "_ssot_inconsistencies.json"), "w", encoding="utf-8") as f:
        json.dump(inconsistencies, f, ensure_ascii=False, indent=2)

    safe_print(f"\n[done] 落盘 -> {out_dir}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
