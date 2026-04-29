#!/usr/bin/env python
"""啄木鸟 v2 — 一次性迁移工具 — 把 inline yaml 收敛到 extends 模式.

扫所有 workspace*/review-rules/review-checklist.yaml, 对老 schema (直接列 rules):
1. 备份原文件 → review-checklist.yaml.bak
2. 跟 SSOT (review-rules-shared/review-checklist.yaml) 对比, 找出 workspace 独有的 rule
3. 写新 yaml: extends + additional_rules (仅含 workspace 独有内容)

工作流 (推荐):
    python scripts/migrate_to_ssot_yaml.py --dry-run    # 看 diff 不改文件
    python scripts/migrate_to_ssot_yaml.py --apply      # 实际改

兼容 Windows GBK 控制台.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from typing import Any

import yaml

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
_SSOT_PATH = os.path.join(_ROOT, "review-rules-shared", "review-checklist.yaml")


def safe_print(text: str) -> None:
    try:
        print(text)
    except UnicodeEncodeError:
        print(text.encode("gbk", errors="replace").decode("gbk", errors="replace"))


def load_yaml(path: str) -> dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception as e:
        safe_print(f"[err] load fail {path}: {e}")
        return {}


def find_workspace_yamls(root: str) -> list[str]:
    out = []
    for name in sorted(os.listdir(root)):
        if not name.startswith("workspace"):
            continue
        p = os.path.join(root, name, "review-rules", "review-checklist.yaml")
        if os.path.isfile(p):
            out.append(p)
    return out


def is_already_extends(yaml_content: dict) -> bool:
    """已是 extends 模式 → 不再迁移."""
    return "extends" in yaml_content


def compute_relative_extends_path(workspace_yaml: str) -> str:
    """从 workspace yaml 算出 extends 的相对路径."""
    ws_dir = os.path.dirname(workspace_yaml)
    rel = os.path.relpath(_SSOT_PATH, ws_dir)
    # 用 forward slash, 跨平台
    return rel.replace(os.sep, "/")


def diff_rules(workspace_rules: list, ssot_rules: list) -> dict:
    """算 workspace 独有的规则 / 与 SSOT 内容不同的覆盖项."""
    ssot_by_id = {
        (r.get("id") or r.get("rule_id")): r
        for r in ssot_rules
        if isinstance(r, dict)
    }
    workspace_unique = []
    workspace_overrides = []
    workspace_identical = []

    for r in workspace_rules:
        if not isinstance(r, dict):
            continue
        rid = r.get("id") or r.get("rule_id")
        if not rid:
            continue
        if rid not in ssot_by_id:
            workspace_unique.append(r)
            continue
        # 比"判定关键字段" — 只看 severity + impact_score 是否变化.
        # description 微差异 (标点/语序) 不算 override (SSOT 是权威定义),
        # 否则迁移产物会把老 description 全 echo 回来等于没收敛.
        ssot_r = ssot_by_id[rid]
        core_ws = (
            r.get("severity", ""),
            r.get("impact_score"),
        )
        core_ssot = (
            ssot_r.get("severity", ""),
            ssot_r.get("impact_score"),
        )
        if core_ws == core_ssot:
            workspace_identical.append(rid)
        else:
            workspace_overrides.append(r)

    return {
        "unique": workspace_unique,
        "overrides": workspace_overrides,
        "identical": workspace_identical,
    }


def write_extends_yaml(target_path: str, extends_rel: str, additional: list) -> str:
    """写新格式 yaml. 返回内容字符串."""
    parts = [
        "# =============================================================",
        f"# {os.path.basename(os.path.dirname(os.path.dirname(target_path)))}"
        " review-checklist (SSOT extends 模式)",
        "# =============================================================",
        "# 由 scripts/migrate_to_ssot_yaml.py 自动生成 (一次性迁移).",
        "# 老规则定义已收敛到 review-rules-shared/review-checklist.yaml,",
        "# 本文件只列 workspace 独有 / 覆盖项.",
        "# =============================================================",
        "",
        f"extends: {extends_rel}",
        "",
        "additional_rules:",
    ]
    if not additional:
        parts[-1] = "additional_rules: []"
    else:
        for r in additional:
            # 简化序列化 (yaml.dump 即可)
            block = yaml.dump([r], allow_unicode=True, sort_keys=False, indent=2)
            for line in block.splitlines():
                parts.append("  " + line if not line.startswith("- ") else line)
    return "\n".join(parts) + "\n"


def migrate_one(yaml_path: str, ssot_rules: list, dry_run: bool) -> dict:
    """迁移一个 workspace yaml. 返回 diff stats."""
    content = load_yaml(yaml_path)
    if not content:
        return {"path": yaml_path, "skipped": "empty/broken"}

    if is_already_extends(content):
        return {"path": yaml_path, "skipped": "already extends"}

    workspace_rules = content.get("rules") or []
    if not isinstance(workspace_rules, list):
        return {"path": yaml_path, "skipped": "rules not list"}

    diff = diff_rules(workspace_rules, ssot_rules)

    extends_rel = compute_relative_extends_path(yaml_path)
    additional = diff["overrides"] + diff["unique"]

    new_content = write_extends_yaml(yaml_path, extends_rel, additional)

    result = {
        "path": yaml_path,
        "ws_total": len(workspace_rules),
        "identical_to_ssot": len(diff["identical"]),
        "overrides": len(diff["overrides"]),
        "unique": len(diff["unique"]),
        "extends_rel": extends_rel,
    }

    if dry_run:
        result["new_content_preview"] = new_content[:500]
    else:
        backup = yaml_path + ".bak"
        if not os.path.exists(backup):
            shutil.copy2(yaml_path, backup)
            result["backup"] = backup
        with open(yaml_path, "w", encoding="utf-8") as f:
            f.write(new_content)
        result["written"] = True

    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="迁移 workspace yaml 到 SSOT extends 模式")
    parser.add_argument("--dry-run", action="store_true", help="仅显示 diff, 不改文件")
    parser.add_argument("--apply", action="store_true", help="实际写入 (备份原文件到 .bak)")
    args = parser.parse_args()

    if not args.dry_run and not args.apply:
        safe_print("用法: --dry-run 看 diff / --apply 实际改")
        return 2

    # 加载 SSOT
    ssot_data = load_yaml(_SSOT_PATH)
    ssot_rules = ssot_data.get("rules", [])
    safe_print(f"[ssot] {_SSOT_PATH}")
    safe_print(f"[ssot] {len(ssot_rules)} 条规则可作为 extends 基础\n")

    workspace_yamls = find_workspace_yamls(_ROOT)
    safe_print(f"[scan] 发现 {len(workspace_yamls)} 个 workspace yaml\n")

    results = []
    for yp in workspace_yamls:
        r = migrate_one(yp, ssot_rules, dry_run=args.dry_run)
        results.append(r)

    safe_print("=" * 70)
    for r in results:
        ws = os.path.basename(os.path.dirname(os.path.dirname(r["path"])))
        if "skipped" in r:
            safe_print(f"  [skip] {ws:<30} ({r['skipped']})")
            continue
        safe_print(
            f"  {ws:<30} ws_rules={r['ws_total']:<3} "
            f"identical={r['identical_to_ssot']:<2} "
            f"overrides={r['overrides']:<2} unique={r['unique']:<2}"
            + (" [WRITTEN]" if r.get("written") else " [DRY-RUN]")
        )

    safe_print("\n=" + "=" * 69)
    if args.dry_run:
        safe_print("[dry-run] 没有改任何文件; 跑 --apply 实际迁移")
    else:
        safe_print(f"[apply done] 已写入. 原文件备份在 *.bak")
    return 0


if __name__ == "__main__":
    sys.exit(main())
