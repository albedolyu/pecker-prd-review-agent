"""啄木鸟 v2 KG 健康度检查 — 跨 workspace 报告.

健康度维度:
1. 规模: entity / relation 计数
2. 结构: 孤岛 entity 比例 (无 relation 连接) — 越低越健康
3. alias 覆盖率: 有 alias 的 entity / 总 entity
4. 类型分布: by_type 是否覆盖核心类型 (data_table / field / spec_doc 等)
5. 新鲜度: meta.json built_at 距今天数
6. 失败页: pages_failed 数
7. 增量索引存在: file_index.json 是否存在 (没有则增量机制未启用)

输出:
- 每 workspace 写 wiki/_kg/health.md (markdown 表格 + warning 列表)
- 跨 workspace 汇总写 logs/kg_health_summary.md

用法:
    python scripts/kg_health_check.py --all
    python scripts/kg_health_check.py --workspaces 产品召回,侵权软件
    python scripts/kg_health_check.py --workspace 产品召回 --no-write   # 仅打印
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "scripts"))

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass


# ============================================================
# 健康度阈值 (生产化经验值, 后续可放进 config)
# ============================================================
THRESHOLDS = {
    "min_entities": 10,             # 业务 wiki 至少 10 entity 才算"覆盖"
    "max_orphan_ratio": 0.30,       # 孤岛 entity 比例 ≤ 30%
    "min_alias_coverage": 0.20,     # alias 覆盖率 ≥ 20%
    "max_age_days": 30,             # 30 天内更新过算新鲜
    "min_relations_per_entity": 0.8,  # avg relations / entity ≥ 0.8
}


def _load_kg(workspace_dir: Path) -> Optional[Dict[str, Any]]:
    """读 entities/relations/meta. 不存在或损坏返 None."""
    base = workspace_dir / "wiki" / "_kg"
    e_path = base / "entities.json"
    r_path = base / "relations.json"
    m_path = base / "meta.json"
    if not e_path.is_file() or not r_path.is_file():
        return None
    try:
        with open(e_path, "r", encoding="utf-8") as f:
            ents = json.load(f)
        with open(r_path, "r", encoding="utf-8") as f:
            rels = json.load(f)
        meta = {}
        if m_path.is_file():
            with open(m_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        return {"_error": str(exc)}
    return {"entities": ents, "relations": rels, "meta": meta, "kg_dir": str(base)}


def _compute_health(workspace_dir: Path) -> Dict[str, Any]:
    """计算单 workspace KG 健康度. 返 dict (含 markdown 段)."""
    name = workspace_dir.name
    wiki_dir = workspace_dir / "wiki"
    kg_dir = wiki_dir / "_kg"

    # 业务页计数 (用于覆盖率参考)
    biz_pages = 0
    if wiki_dir.is_dir():
        for fn in os.listdir(wiki_dir):
            if not fn.endswith(".md") or fn.startswith("."):
                continue
            bn = fn.lower()
            if bn in ("index.md", "log.md", "readme.md", "toc.md"):
                continue
            biz_pages += 1

    data = _load_kg(workspace_dir)
    if data is None:
        return {
            "workspace": name,
            "status": "no_kg",
            "biz_pages": biz_pages,
            "warnings": ["KG 不存在 (entities.json 缺失). 跑 build_kg_all 生成."],
            "health_score": 0,
        }
    if "_error" in data:
        return {
            "workspace": name,
            "status": "corrupted",
            "biz_pages": biz_pages,
            "warnings": [f"KG 数据损坏: {data['_error']}"],
            "health_score": 0,
        }

    entities = data["entities"]
    relations = data["relations"]
    meta = data.get("meta", {})

    # ---- 计算指标 ----
    n_e = len(entities)
    n_r = len(relations)
    rel_per_ent = round(n_r / max(1, n_e), 2)

    # 孤岛: entity 没出现在任何 relation 的 source/target
    connected = set()
    for r in relations:
        if r.get("source_id"):
            connected.add(r["source_id"])
        if r.get("target_id"):
            connected.add(r["target_id"])
    orphan_count = sum(1 for e in entities if e.get("id") not in connected)
    orphan_ratio = round(orphan_count / max(1, n_e), 2)

    # alias 覆盖率
    alias_yes = sum(1 for e in entities if e.get("aliases"))
    alias_coverage = round(alias_yes / max(1, n_e), 2)

    # 类型分布
    by_type: Dict[str, int] = {}
    for e in entities:
        by_type[e.get("type", "?")] = by_type.get(e.get("type", "?"), 0) + 1

    # 新鲜度
    age_days = None
    built_at = meta.get("built_at")
    if built_at:
        try:
            t = time.strptime(built_at, "%Y-%m-%d %H:%M:%S")
            age_days = (time.time() - time.mktime(t)) / 86400
        except (ValueError, TypeError):
            pass

    # 失败页
    failed_pages = meta.get("pages_failed", []) or []

    # 增量索引存在
    has_file_index = (kg_dir / "file_index.json").is_file()

    # ---- 计算健康分 (0-100) ----
    score = 100
    warnings: List[str] = []
    if n_e < THRESHOLDS["min_entities"]:
        score -= 20
        warnings.append(f"实体数偏少 ({n_e} < {THRESHOLDS['min_entities']})")
    if orphan_ratio > THRESHOLDS["max_orphan_ratio"]:
        score -= 15
        warnings.append(f"孤岛比例偏高 ({orphan_ratio:.0%} > {THRESHOLDS['max_orphan_ratio']:.0%})")
    if alias_coverage < THRESHOLDS["min_alias_coverage"]:
        score -= 10
        warnings.append(f"alias 覆盖率偏低 ({alias_coverage:.0%} < {THRESHOLDS['min_alias_coverage']:.0%})")
    if rel_per_ent < THRESHOLDS["min_relations_per_entity"]:
        score -= 10
        warnings.append(f"关系密度偏低 ({rel_per_ent} < {THRESHOLDS['min_relations_per_entity']})")
    if age_days is not None and age_days > THRESHOLDS["max_age_days"]:
        score -= 10
        warnings.append(f"KG 数据陈旧 ({int(age_days)} 天前更新)")
    if failed_pages:
        score -= min(15, len(failed_pages) * 5)
        warnings.append(f"{len(failed_pages)} 个页面抽取失败: {failed_pages[:3]}")
    if not has_file_index:
        warnings.append("file_index.json 缺失, 增量机制未启用; 跑 incremental_kg_update --rebuild-index")
    score = max(0, score)

    return {
        "workspace": name,
        "status": "ok",
        "biz_pages": biz_pages,
        "entities": n_e,
        "relations": n_r,
        "rel_per_entity": rel_per_ent,
        "orphan_count": orphan_count,
        "orphan_ratio": orphan_ratio,
        "alias_coverage": alias_coverage,
        "by_type": by_type,
        "age_days": int(age_days) if age_days is not None else None,
        "built_at": built_at,
        "failed_pages": failed_pages,
        "has_file_index": has_file_index,
        "warnings": warnings,
        "health_score": score,
    }


# ============================================================
# Markdown 渲染
# ============================================================

def _render_workspace_md(h: Dict[str, Any]) -> str:
    """渲染单 workspace health.md."""
    lines = []
    lines.append(f"# KG 健康度报告 — {h['workspace']}")
    lines.append("")
    lines.append(f"_生成时间: {time.strftime('%Y-%m-%d %H:%M:%S')}_")
    lines.append("")

    if h["status"] == "no_kg":
        lines.append("## 状态: KG 不存在")
        lines.append("")
        lines.append(f"业务页数: {h['biz_pages']}")
        lines.append("")
        lines.append("**建议**: 运行 `python scripts/build_kg_all.py --workspaces " + h["workspace"].replace("workspace-", "") + "`")
        return "\n".join(lines)

    if h["status"] == "corrupted":
        lines.append("## 状态: KG 数据损坏")
        for w in h["warnings"]:
            lines.append(f"- {w}")
        return "\n".join(lines)

    score = h["health_score"]
    badge = "🟢" if score >= 80 else "🟡" if score >= 60 else "🔴"
    lines.append(f"## 健康分: {badge} {score}/100")
    lines.append("")
    lines.append("## 指标")
    lines.append("")
    lines.append("| 项 | 值 |")
    lines.append("|---|---|")
    lines.append(f"| 业务页 | {h['biz_pages']} |")
    lines.append(f"| 实体数 | {h['entities']} |")
    lines.append(f"| 关系数 | {h['relations']} |")
    lines.append(f"| 关系密度 (rel/ent) | {h['rel_per_entity']} |")
    lines.append(f"| 孤岛实体数 | {h['orphan_count']} ({h['orphan_ratio']:.0%}) |")
    lines.append(f"| alias 覆盖率 | {h['alias_coverage']:.0%} |")
    lines.append(f"| 数据陈旧度 | {h['age_days']} 天 |")
    lines.append(f"| 构建时间 | {h['built_at']} |")
    lines.append(f"| 失败页 | {len(h['failed_pages'])} |")
    lines.append(f"| 增量索引启用 | {'是' if h['has_file_index'] else '否'} |")
    lines.append("")
    lines.append("## 类型分布")
    lines.append("")
    lines.append("| 类型 | 数量 |")
    lines.append("|---|---|")
    for t, c in sorted(h["by_type"].items(), key=lambda x: -x[1]):
        lines.append(f"| {t} | {c} |")
    lines.append("")
    if h["warnings"]:
        lines.append("## 告警")
        lines.append("")
        for w in h["warnings"]:
            lines.append(f"- ⚠ {w}")
    else:
        lines.append("## 告警")
        lines.append("")
        lines.append("无, KG 健康")
    return "\n".join(lines) + "\n"


def _render_summary_md(healths: List[Dict[str, Any]]) -> str:
    """跨 workspace 汇总 markdown."""
    lines = []
    lines.append("# 啄木鸟 KG 健康度跨 workspace 汇总")
    lines.append("")
    lines.append(f"_生成时间: {time.strftime('%Y-%m-%d %H:%M:%S')}_")
    lines.append("")
    lines.append("## 总览")
    lines.append("")
    lines.append("| workspace | 状态 | biz | ents | rels | 孤岛% | alias% | 健康分 |")
    lines.append("|---|---|---:|---:|---:|---:|---:|---:|")
    total_e = total_r = 0
    for h in healths:
        if h["status"] == "no_kg":
            lines.append(f"| {h['workspace']} | 缺 KG | {h['biz_pages']} | - | - | - | - | 0 |")
            continue
        if h["status"] == "corrupted":
            lines.append(f"| {h['workspace']} | 损坏 | {h['biz_pages']} | - | - | - | - | 0 |")
            continue
        badge = "🟢" if h["health_score"] >= 80 else "🟡" if h["health_score"] >= 60 else "🔴"
        lines.append(
            f"| {h['workspace']} | ok | {h['biz_pages']} | {h['entities']} | {h['relations']} | "
            f"{h['orphan_ratio']:.0%} | {h['alias_coverage']:.0%} | {badge} {h['health_score']} |"
        )
        total_e += h["entities"]
        total_r += h["relations"]
    lines.append("")
    lines.append(f"**合计**: {total_e} entities / {total_r} relations 跨 {len(healths)} workspaces")
    lines.append("")
    # 重点告警 workspace
    bad = [h for h in healths if h.get("warnings")]
    if bad:
        lines.append("## 需关注 workspace")
        lines.append("")
        for h in bad:
            lines.append(f"### {h['workspace']} ({h.get('health_score', 0)}/100)")
            for w in h["warnings"]:
                lines.append(f"- {w}")
            lines.append("")
    return "\n".join(lines) + "\n"


# ============================================================
# CLI
# ============================================================

def _resolve_workspaces(args, root: Path) -> List[Path]:
    if args.all:
        out = []
        for p in sorted(root.iterdir()):
            if p.is_dir() and p.name.startswith("workspace-") and (p / "wiki").is_dir():
                out.append(p)
        return out
    names_raw = args.workspaces or args.workspace
    if not names_raw:
        print("[ERR] 必须传 --all / --workspace / --workspaces", file=sys.stderr)
        sys.exit(2)
    names = [n.strip() for n in names_raw.split(",") if n.strip()]
    out = []
    for n in names:
        cand = (root / n) if n.startswith("workspace-") else (root / f"workspace-{n}")
        if cand.is_dir() and (cand / "wiki").is_dir():
            out.append(cand)
    return out


def main():
    parser = argparse.ArgumentParser(description="跨 workspace KG 健康度检查 + 报告")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--workspace", default="")
    parser.add_argument("--workspaces", default="")
    parser.add_argument("--no-write", action="store_true",
                        help="只打印不落 health.md / summary.md")
    args = parser.parse_args()

    workspaces = _resolve_workspaces(args, _ROOT)
    if not workspaces:
        print("[ERR] 没匹配到 workspace", file=sys.stderr)
        sys.exit(2)

    print(f"=== 检查 {len(workspaces)} 个 workspace ===\n")
    healths: List[Dict[str, Any]] = []
    for ws in workspaces:
        h = _compute_health(ws)
        healths.append(h)
        score = h.get("health_score", 0)
        badge = "[OK]" if score >= 80 else "[WARN]" if score >= 60 else "[BAD]"
        if h["status"] == "no_kg":
            print(f"{badge} {h['workspace']}: KG 不存在 (biz={h['biz_pages']})")
        elif h["status"] == "corrupted":
            print(f"[ERR] {h['workspace']}: KG 损坏")
        else:
            print(f"{badge} {h['workspace']}: score={score}, "
                  f"ents={h['entities']}, rels={h['relations']}, "
                  f"孤岛={h['orphan_ratio']:.0%}, alias={h['alias_coverage']:.0%}")
            for w in h.get("warnings", []):
                print(f"      ⚠ {w}")

        if not args.no_write:
            md = _render_workspace_md(h)
            health_path = ws / "wiki" / "_kg" / "health.md"
            health_path.parent.mkdir(parents=True, exist_ok=True)
            with open(health_path, "w", encoding="utf-8") as f:
                f.write(md)

    # summary
    if not args.no_write:
        summary_md = _render_summary_md(healths)
        summary_path = _ROOT / "logs" / "kg_health_summary.md"
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        with open(summary_path, "w", encoding="utf-8") as f:
            f.write(summary_md)
        print(f"\n=== 写入 ===")
        print(f"  各 workspace: wiki/_kg/health.md")
        print(f"  汇总: {summary_path}")


if __name__ == "__main__":
    main()
