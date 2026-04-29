#!/usr/bin/env python
"""啄木鸟 — Static Rule Check (CI gate, 不调 LLM).

放在 .github/workflows/rule_regression.yml 的 PR pipeline 里跑.
不依赖 codex CLI / DeepSeek API, 只做"yaml schema + token 预算 + baseline 同步"
三项静态检查, 在 dev 机/CI 环境都能跑.

检查项:
  1. review-checklist.yaml schema:
     - rule 必须有 id + name + severity + description
     - L3 升级规则 (有 positive_example 字段) 必须额外有 fire_when + dont_fire_when
     - 全局 rule_id 不能重复
  2. baseline 同步检查:
     - review-checklist.yaml 改动时, baseline.json 中已存在的 rule_id 必须仍能找到
     - 新增 rule 必须在 PR 描述里提及 CHANGELOG (CI 只检查 baseline 不缺失老 id)
  3. prompting.py token 预算估算:
     - 按 review-dimensions.yaml 中每个维度的规则数估 worker prompt 大小
     - 超过 _PROMPT_TOKEN_BUDGET (10K) 时输出 warning
  4. learnings 静态健康 (信鸽 v2 接入后):
     - 检查 workspace/learnings/index.json 是否能与 yaml 同步, 损坏自愈

退出码:
  0  全部通过
  1  失败 (CI gate 阻塞 merge)
  2  CLI 参数错误

用法:
    python scripts/static_rule_check.py
    python scripts/static_rule_check.py --workspace workspace-sample
    python scripts/static_rule_check.py --strict   # warning 也当 fail
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, List, Optional, Tuple

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import yaml


def _safe_print(text: str) -> None:
    try:
        print(text)
    except UnicodeEncodeError:
        encoded = text.encode("gbk", errors="replace").decode("gbk", errors="replace")
        print(encoded)


# ============================================================
# 检查 1: yaml schema
# ============================================================

REQUIRED_BASIC_FIELDS = ("id", "name", "severity", "description")
L3_REQUIRED_FIELDS = ("fire_when", "dont_fire_when")
VALID_SEVERITIES = ("must", "should")


def check_checklist_yaml(yaml_path: str) -> Tuple[List[str], List[str]]:
    """检查 review-checklist.yaml schema. 返回 (errors, warnings)."""
    errors: List[str] = []
    warnings: List[str] = []

    if not os.path.isfile(yaml_path):
        warnings.append(f"review-checklist.yaml 不存在: {yaml_path} (跳过 schema 校验)")
        return errors, warnings

    try:
        with open(yaml_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except yaml.YAMLError as e:
        errors.append(f"yaml 解析失败 ({yaml_path}): {e}")
        return errors, warnings

    rules = data.get("rules", [])
    if not isinstance(rules, list):
        errors.append(f"{yaml_path}: rules 字段必须是 list")
        return errors, warnings

    seen_ids = set()
    for i, rule in enumerate(rules):
        prefix = f"{yaml_path}#rules[{i}]"
        if not isinstance(rule, dict):
            errors.append(f"{prefix}: 不是 dict")
            continue

        # 基础字段
        for field in REQUIRED_BASIC_FIELDS:
            if field == "id":
                # id 用 id 或 rule_id 二者之一
                if not (rule.get("id") or rule.get("rule_id")):
                    errors.append(f"{prefix}: 缺 id (或 rule_id)")
            elif not rule.get(field):
                errors.append(f"{prefix}: 缺 {field}")

        rid = rule.get("id") or rule.get("rule_id")
        if rid:
            if rid in seen_ids:
                errors.append(f"{prefix}: rule_id 重复 ({rid})")
            seen_ids.add(rid)

        # severity 合法性
        sev = rule.get("severity")
        if sev and sev not in VALID_SEVERITIES:
            warnings.append(f"{prefix} ({rid}): severity={sev} 非标准 ({VALID_SEVERITIES})")

        # L3 升级规则 (有 examples 即视为 L3)
        has_examples = bool(rule.get("positive_example") or rule.get("negative_example"))
        if has_examples:
            for field in L3_REQUIRED_FIELDS:
                if not rule.get(field):
                    errors.append(
                        f"{prefix} ({rid}): L3 升级规则 (有 examples) 缺 {field}, "
                        f"会让 worker 失去 fire_when 边界判断依据"
                    )

    return errors, warnings


# ============================================================
# 检查 2: baseline 同步
# ============================================================

def check_baseline_sync(yaml_path: str, baseline_path: str) -> Tuple[List[str], List[str]]:
    """baseline.json 中已记录的 rule_id 必须仍在 yaml 中能找到 (避免 silent rename)."""
    errors: List[str] = []
    warnings: List[str] = []

    if not os.path.isfile(baseline_path):
        warnings.append(f"baseline.json 不存在: {baseline_path} (首次跑时正常)")
        return errors, warnings
    if not os.path.isfile(yaml_path):
        warnings.append(f"review-checklist.yaml 不存在: {yaml_path} (跳过 baseline 同步检查)")
        return errors, warnings

    try:
        with open(baseline_path, "r", encoding="utf-8") as f:
            baseline = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        errors.append(f"baseline.json 损坏: {e}")
        return errors, warnings

    # 2026-04-28: 走 SSOT loader, 自动展开 extends. 老 schema 不带 extends 也兼容.
    try:
        from review.rule_loader import load_review_checklist
        # baseline 同步用 workspace 视角 (workspace 路径就是 yaml 的爷爷目录)
        ws_dir = os.path.dirname(os.path.dirname(yaml_path))
        merged_rules = load_review_checklist(ws_dir)
    except Exception as e:
        errors.append(f"SSOT loader 失败: {e}")
        return errors, warnings

    yaml_ids = set()
    for rule in (merged_rules or []):
        if isinstance(rule, dict):
            rid = rule.get("id") or rule.get("rule_id")
            if rid:
                yaml_ids.add(rid)

    baseline_ids = set((baseline.get("rules") or {}).keys())
    missing = baseline_ids - yaml_ids
    if missing:
        errors.append(
            f"baseline 中以下 rule_id 在 yaml 已找不到 (是否 rename 漏改?): "
            f"{sorted(missing)}"
        )

    new_in_yaml = yaml_ids - baseline_ids
    if new_in_yaml:
        # 新增不报错 (允许), 只 warn 提示需要在 PR 描述/CHANGELOG 提到
        warnings.append(
            f"yaml 中以下 rule_id 是新增 (baseline 无), CHANGELOG 应提及并准备 update-baseline: "
            f"{sorted(new_in_yaml)}"
        )

    return errors, warnings


# ============================================================
# 检查 3: prompting.py token 预算估算
# ============================================================

def check_prompt_token_budget(workspace: str) -> Tuple[List[str], List[str]]:
    """估算每个维度 worker prompt 的字符数, 超 _PROMPT_TOKEN_BUDGET 时 warn."""
    errors: List[str] = []
    warnings: List[str] = []

    try:
        from review.prompting import _PROMPT_TOKEN_BUDGET, _build_examples_block
        from review.dimensions import get_review_dimensions
    except ImportError as e:
        warnings.append(f"prompting / dimensions import 失败 (跳过 token 预算检查): {e}")
        return errors, warnings

    try:
        dims = get_review_dimensions()
    except Exception as e:
        warnings.append(f"get_review_dimensions 失败: {e}")
        return errors, warnings

    for dim_key in dims.keys():
        try:
            block = _build_examples_block(workspace, dim_key, base_token_estimate=0) or ""
        except Exception as e:
            warnings.append(f"dim={dim_key} examples block 渲染失败: {e}")
            continue
        char_count = len(block)
        # 中文 1 字 ≈ 1 token, ascii ≈ 1/4 token, 这里保守按 char_count 当 token
        if char_count > _PROMPT_TOKEN_BUDGET:
            warnings.append(
                f"dim={dim_key} examples block 估 {char_count} token, "
                f"超过 _PROMPT_TOKEN_BUDGET={_PROMPT_TOKEN_BUDGET} (会触发 compact 降级)"
            )

    return errors, warnings


# ============================================================
# 检查 4: learnings 静态健康 (信鸽 v2)
# ============================================================

def check_learnings_health(workspace: str) -> Tuple[List[str], List[str]]:
    """检查 workspace/learnings/index.json 与 yaml 同步; 损坏走自愈路径."""
    errors: List[str] = []
    warnings: List[str] = []

    learnings_dir = os.path.join(workspace, "learnings")
    if not os.path.isdir(learnings_dir):
        return errors, warnings  # 没启用 learnings 是合法状态

    try:
        from review.learnings_store import LearningsStore
    except ImportError as e:
        warnings.append(f"learnings_store import 失败 (跳过 health 检查): {e}")
        return errors, warnings

    try:
        store = LearningsStore(workspace)
        learnings = store.list_all()
    except (OSError, ValueError) as e:
        errors.append(f"LearningsStore 加载失败 ({workspace}): {e}")
        return errors, warnings

    # 数量级 sanity check (CodeRabbit 推荐的 50-200 条)
    if len(learnings) > 500:
        warnings.append(
            f"learnings 数量 {len(learnings)} > 500, 建议清理 stale "
            f"(scripts/learnings_dashboard.py 看 stale 提示)"
        )
    return errors, warnings


# ============================================================
# CLI 主入口
# ============================================================

def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="啄木鸟 Static Rule Check (CI gate)")
    parser.add_argument(
        "--workspace",
        default=os.path.join(_ROOT, "workspace-sample"),
        help="workspace 路径 (默认 workspace-sample)",
    )
    parser.add_argument(
        "--baseline",
        default=os.path.join(_HERE, "fixtures", "regression_baseline.json"),
        help="regression baseline.json 路径",
    )
    parser.add_argument(
        "--strict", action="store_true",
        help="warning 也算 fail",
    )
    args = parser.parse_args(argv)

    workspace = os.path.abspath(args.workspace)
    yaml_path = os.path.join(workspace, "review-rules", "review-checklist.yaml")
    baseline_path = os.path.abspath(args.baseline)

    _safe_print("=" * 70)
    _safe_print("啄木鸟 Static Rule Check (CI gate)")
    _safe_print("=" * 70)
    _safe_print(f"  workspace:  {workspace}")
    _safe_print(f"  yaml:       {yaml_path}")
    _safe_print(f"  baseline:   {baseline_path}")
    _safe_print(f"  strict:     {args.strict}")
    _safe_print("")

    all_errors: List[str] = []
    all_warnings: List[str] = []

    # 1. yaml schema
    _safe_print("[1/4] checklist yaml schema...")
    e, w = check_checklist_yaml(yaml_path)
    all_errors.extend(e)
    all_warnings.extend(w)
    _safe_print(f"     errors={len(e)}  warnings={len(w)}")

    # 2. baseline 同步
    _safe_print("[2/4] baseline 同步...")
    e, w = check_baseline_sync(yaml_path, baseline_path)
    all_errors.extend(e)
    all_warnings.extend(w)
    _safe_print(f"     errors={len(e)}  warnings={len(w)}")

    # 3. token 预算
    _safe_print("[3/4] prompt token 预算...")
    e, w = check_prompt_token_budget(workspace)
    all_errors.extend(e)
    all_warnings.extend(w)
    _safe_print(f"     errors={len(e)}  warnings={len(w)}")

    # 4. learnings 健康
    _safe_print("[4/4] learnings 健康...")
    e, w = check_learnings_health(workspace)
    all_errors.extend(e)
    all_warnings.extend(w)
    _safe_print(f"     errors={len(e)}  warnings={len(w)}")

    _safe_print("")
    _safe_print("-" * 70)
    if all_errors:
        _safe_print(f"ERRORS ({len(all_errors)}):")
        for err in all_errors:
            _safe_print(f"  [E] {err}")
    if all_warnings:
        _safe_print(f"WARNINGS ({len(all_warnings)}):")
        for warn in all_warnings:
            _safe_print(f"  [W] {warn}")

    if not all_errors and not all_warnings:
        _safe_print("ALL GREEN")
        return 0

    fail = bool(all_errors) or (args.strict and bool(all_warnings))
    if fail:
        _safe_print("")
        _safe_print(f"FAIL  errors={len(all_errors)}  warnings={len(all_warnings)}  strict={args.strict}")
        return 1
    _safe_print("")
    _safe_print(f"OK (warnings only, strict 未开启)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
