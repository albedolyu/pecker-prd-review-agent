"""Pecker v2 — review-checklist.yaml SSOT 加载器.

支持:
- 老 schema (workspace 直接列 rules): 100% 向后兼容, 不需要任何改动
- 新 schema (workspace 用 extends 引用 SSOT): 自动合并 SSOT + 本地 additional_rules

新 schema 范例 (workspace yaml):

    extends: ../../review-rules-shared/review-checklist.yaml
    additional_rules:
      - id: RC-099
        name: workspace 自定义规则
        ...

合并语义:
- SSOT 加载后作为基础 list
- additional_rules 追加在后, 同 id 覆盖 SSOT (允许 workspace 微调)
- include 同时可加多个 (extends 也接受 list, 按顺序 merge)

加载入口:
    rules = load_review_checklist(workspace_path)  # 返回 list[dict]

Loader 已被 review/prompting.py / review/schema_registry.py 引用 (如启用).
向后兼容由 _load_legacy_workspace_yaml 调用本 loader 实现.
"""

from __future__ import annotations

import os
from typing import Any

import yaml

from logger import get_logger

log = get_logger("rule_loader")


_CHECKLIST_FILENAME = "review-checklist.yaml"


def _resolve_extends_path(extends_value: str, base_dir: str) -> str:
    """把 extends 字段的相对路径解析成绝对路径.

    extends 可以是:
    - 相对路径 (相对于 yaml 文件本身的目录), 如 '../../review-rules-shared/review-checklist.yaml'
    - 绝对路径
    """
    if os.path.isabs(extends_value):
        return os.path.normpath(extends_value)
    return os.path.normpath(os.path.join(base_dir, extends_value))


def _load_yaml_file(path: str) -> dict[str, Any]:
    """安全加载 yaml 文件. 损坏返回空 dict + warn."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = yaml.safe_load(f) or {}
        if not isinstance(content, dict):
            log.warning(f"[rule_loader] {path}: 顶层非 dict, 返回空")
            return {}
        return content
    except (OSError, yaml.YAMLError) as e:
        log.warning(f"[rule_loader] 加载失败 {path}: {e}")
        return {}


def _merge_rules(base: list[dict], overlay: list[dict]) -> list[dict]:
    """合并两个 rule list. 同 id 时 overlay 覆盖 base (位置保持 base 顺序, 新增追加)."""
    if not overlay:
        return list(base)
    by_id = {r.get("id") or r.get("rule_id"): r for r in base if isinstance(r, dict)}
    for r in overlay:
        if not isinstance(r, dict):
            continue
        rid = r.get("id") or r.get("rule_id")
        if not rid:
            continue
        by_id[rid] = r
    # 保持原顺序: base 已存在的按原顺序, 新增的追加
    out = []
    seen = set()
    for r in base:
        if not isinstance(r, dict):
            continue
        rid = r.get("id") or r.get("rule_id")
        if rid and rid not in seen:
            out.append(by_id[rid])
            seen.add(rid)
    for r in overlay:
        if not isinstance(r, dict):
            continue
        rid = r.get("id") or r.get("rule_id")
        if rid and rid not in seen:
            out.append(by_id[rid])
            seen.add(rid)
    return out


def _resolve_extends_chain(
    yaml_content: dict[str, Any], base_dir: str, visited: set[str] | None = None
) -> list[dict]:
    """递归解析 extends, 返回合并后的 rules list.

    支持 extends 是 str (单文件) 或 list (多文件, 按顺序 merge).
    防递归: visited 跟踪已加载文件, 循环引用直接 break + warn.
    """
    if visited is None:
        visited = set()

    extends_val = yaml_content.get("extends")
    base_rules: list[dict] = []

    if extends_val:
        extend_paths = (
            extends_val if isinstance(extends_val, list) else [extends_val]
        )
        for ext_path_raw in extend_paths:
            if not isinstance(ext_path_raw, str):
                continue
            full = _resolve_extends_path(ext_path_raw, base_dir)
            if full in visited:
                log.warning(f"[rule_loader] extends 循环引用, 跳过: {full}")
                continue
            visited.add(full)
            if not os.path.isfile(full):
                log.warning(f"[rule_loader] extends 目标不存在: {full}")
                continue
            ext_content = _load_yaml_file(full)
            ext_base_dir = os.path.dirname(full)
            # 递归解析 extends 的 extends
            ext_rules = _resolve_extends_chain(ext_content, ext_base_dir, visited)
            # 合并: 当前 extend 文件自己的 rules + 它的 extends 链
            self_rules = ext_content.get("rules") or []
            if not isinstance(self_rules, list):
                self_rules = []
            merged = _merge_rules(ext_rules, self_rules)
            base_rules = _merge_rules(base_rules, merged)

    return base_rules


def load_review_checklist(workspace: str) -> list[dict]:
    """加载 workspace/review-rules/review-checklist.yaml, 解析 extends, 合并 additional_rules.

    支持三种 yaml 形态:

    1. 老 schema (无 extends, 直接列 rules) — 100% 兼容:
        rules:
          - id: RC-004
            ...

    2. 新 schema (有 extends, 引用 SSOT):
        extends: ../../review-rules-shared/review-checklist.yaml
        additional_rules:
          - id: RC-099
            ...

    3. 混合 (同时有 extends 和 rules, 不推荐但兼容):
        extends: ../../review-rules-shared/review-checklist.yaml
        rules:
          - id: RC-099
            ...

    Args:
        workspace: workspace 绝对路径, 如 'C:/.../workspace-sample-case'

    Returns:
        list[dict] — 合并后的 rules. 文件不存在 / 损坏 → 空 list + log warn.
    """
    if not workspace or not os.path.isdir(workspace):
        return []

    yaml_path = os.path.join(workspace, "review-rules", _CHECKLIST_FILENAME)
    if not os.path.isfile(yaml_path):
        return []

    content = _load_yaml_file(yaml_path)
    if not content:
        return []

    base_dir = os.path.dirname(yaml_path)
    visited: set[str] = {yaml_path}

    # 1. 解析 extends 链, 拿到 SSOT (或空 list)
    base_rules = _resolve_extends_chain(content, base_dir, visited)

    # 2. 合并本 workspace 自己的 rules (向后兼容 老 schema 无 extends 的直接 rules)
    self_rules = content.get("rules") or []
    if not isinstance(self_rules, list):
        self_rules = []

    additional_rules = content.get("additional_rules") or []
    if not isinstance(additional_rules, list):
        additional_rules = []

    # 老 schema 直接走 rules; 新 schema 推荐用 additional_rules 但 rules 也兼容
    overlay = list(self_rules) + list(additional_rules)

    return _merge_rules(base_rules, overlay)


def get_rule_by_id(workspace: str, rule_id: str) -> dict | None:
    """便捷查询: 按 id 获取规则 dict."""
    for r in load_review_checklist(workspace):
        if isinstance(r, dict) and (r.get("id") == rule_id or r.get("rule_id") == rule_id):
            return r
    return None


def list_rule_ids(workspace: str) -> list[str]:
    """便捷查询: 返回 workspace 全部 rule id 列表."""
    out = []
    for r in load_review_checklist(workspace):
        if not isinstance(r, dict):
            continue
        rid = r.get("id") or r.get("rule_id")
        if rid:
            out.append(rid)
    return out
