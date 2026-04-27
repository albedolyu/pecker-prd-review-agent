"""统一评测数据集 loader.

调用约定:
    from eval.route_eval.datasets.loader import load_dataset
    records = load_dataset("business_prd_gt")  # -> list[dict]

未知数据集名抛 ValueError.

数据存储约定:
- 所有 manifest / 数据文件在 ``eval/route_eval/datasets/data/<name>/``
- manifest 用相对路径 (相对项目根), 工作目录无关
- loader 必须能离线跑, 不调任何 LLM/外部 API

数据集字段契约 见 ``__init__.py`` 与 plan.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable

# 项目根 (datasets -> route_eval -> eval -> 项目根)
_DATASETS_DIR = Path(__file__).resolve().parent
_DATA_ROOT = _DATASETS_DIR / "data"
_PROJECT_ROOT = _DATASETS_DIR.parent.parent.parent  # eval/route_eval/datasets -> repo


def _read_json(path: Path) -> Any:
    """读取 JSON, 文件不存在时抛清晰错误."""
    if not path.exists():
        raise FileNotFoundError(f"数据集文件不存在: {path}")
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _read_text(path: Path) -> str:
    """读取文本文件, 不存在时抛清晰错误."""
    if not path.exists():
        raise FileNotFoundError(f"PRD 文件不存在: {path}")
    return path.read_text(encoding="utf-8")


def _resolve_path(rel_path: str) -> Path:
    """相对项目根的路径转绝对路径."""
    return _PROJECT_ROOT / rel_path


# ----- 各数据集加载函数 -----

def _load_business_prd_gt() -> list[dict]:
    """业务 PRD + ground truth.

    manifest 引用 PRD 文件路径 + GT 文件路径; 这里不读 PRD 全文 (大), 只读 GT.
    返回字段: prd_path / workspace / ground_truth (list[dict]).
    """
    manifest_path = _DATA_ROOT / "business_prd_gt" / "manifest.json"
    manifest = _read_json(manifest_path)
    out: list[dict] = []
    for entry in manifest["entries"]:
        prd_path = entry["prd_path"]
        # 校验 PRD 文件实际存在 (不读内容, 仅 stat)
        prd_abs = _resolve_path(prd_path)
        if not prd_abs.exists():
            raise FileNotFoundError(f"manifest 引用的 PRD 文件不存在: {prd_abs}")
        # 读 GT
        gt_path = entry.get("gt_path")
        if gt_path:
            gt_abs = _resolve_path(gt_path)
            gt_raw = _read_json(gt_abs)
            ground_truth = _normalize_ground_truth(gt_raw, gt_abs.name)
        else:
            # 用 manifest 内联 GT (积分抵扣支付/风鸟诉前调解 fallback)
            ground_truth = entry.get("inline_ground_truth", [])
        out.append({
            "prd_path": prd_path,
            "workspace": entry["workspace"],
            "ground_truth": ground_truth,
        })
    return out


def _normalize_ground_truth(raw: Any, source_name: str) -> list[dict]:
    """把不同形态的 GT 文件统一成 list[{rule_id?, issue, severity, ...}].

    支持两种形态:
    - planted_bugs (现有 test_cases/*_planted.json): {"planted_bugs": [...]}
    - 内联 list (manifest inline): [{...}]
    """
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict) and "planted_bugs" in raw:
        out: list[dict] = []
        for bug in raw["planted_bugs"]:
            out.append({
                "rule_id": bug.get("id") or bug.get("rule_id", "UNKNOWN"),
                "issue": bug.get("description", ""),
                "severity": bug.get("severity", "must"),
                "location": bug.get("location", ""),
                "type": bug.get("type", ""),
                "keywords": bug.get("keywords", []),
            })
        return out
    raise ValueError(f"GT 文件 {source_name} 格式不识别, 既不是 list 也没有 planted_bugs 字段")


def _load_template_prd() -> list[dict]:
    """模板 PRD (侵权软件) — 已知 sampling noise 大, 用于稳定性校准."""
    manifest_path = _DATA_ROOT / "template_prd" / "manifest.json"
    manifest = _read_json(manifest_path)
    out: list[dict] = []
    for entry in manifest["entries"]:
        prd_abs = _resolve_path(entry["prd_path"])
        if not prd_abs.exists():
            raise FileNotFoundError(f"template_prd 引用的 PRD 不存在: {prd_abs}")
        out.append({
            "prd_path": entry["prd_path"],
            "workspace": entry["workspace"],
            "note": entry.get("note", ""),
        })
    return out


def _load_advisor_conflicts() -> list[dict]:
    """苍鹰冲突调解评测.

    现阶段 5 条 placeholder, 待 PM 补 10 条到 N=15.
    每条返回: id / workspace / worker_outputs / ground_truth_resolution.
    """
    path = _DATA_ROOT / "advisor_conflicts" / "conflicts.json"
    raw = _read_json(path)
    return list(raw.get("cases", []))


def _load_hallucination() -> list[dict]:
    """幻觉评测.

    30 真 + 30 假 (±5), 4 种 construction_method 等量构造假依据.
    """
    path = _DATA_ROOT / "hallucination" / "cases.json"
    raw = _read_json(path)
    return list(raw.get("cases", []))


def _load_intent() -> list[dict]:
    """意图分类评测 (路由到 opus/sonnet/haiku/reject)."""
    path = _DATA_ROOT / "intent" / "cases.json"
    raw = _read_json(path)
    return list(raw.get("cases", []))


# ----- 注册表 + 公共入口 -----

_DATASET_REGISTRY: dict[str, Callable[[], list[dict]]] = {
    "business_prd_gt": _load_business_prd_gt,
    "template_prd": _load_template_prd,
    "advisor_conflicts": _load_advisor_conflicts,
    "hallucination": _load_hallucination,
    "intent": _load_intent,
}


def load_dataset(name: str) -> list[dict]:
    """加载评测数据集.

    参数:
        name: 数据集名 (business_prd_gt / template_prd / advisor_conflicts /
              hallucination / intent).

    返回:
        list[dict], 字段契约见各 _load_* 函数 docstring.

    异常:
        ValueError: 未知数据集名.
        FileNotFoundError: 数据文件缺失 (说明数据集损坏, 应让 CI 立即 fail).
    """
    loader = _DATASET_REGISTRY.get(name)
    if loader is None:
        known = ", ".join(sorted(_DATASET_REGISTRY.keys()))
        raise ValueError(f"未知数据集: {name!r} (可用: {known})")
    return loader()


def list_datasets() -> list[str]:
    """列出所有可用数据集名."""
    return sorted(_DATASET_REGISTRY.keys())
