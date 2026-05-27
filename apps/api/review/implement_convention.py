"""下游实现约定标记。

Pecker评审项不是终点,后续通常会交给实现 agent。这里把当前约定写成
机器可读字段,避免只在报告里靠自然语言提醒。
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List


IMPLEMENT_CONVENTION_VERSION = "v1"
IMPLEMENT_CONVENTION_DOC = "docs/pecker_implement_convention_v1_2026_04_28.md"
IMPLEMENT_CONVENTION_REQUIRED = True


def annotate_review_items(items: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """给 review items 补充实现约定版本,返回浅拷贝列表。"""
    annotated: List[Dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        out = dict(item)
        out.setdefault("implement_convention_version", IMPLEMENT_CONVENTION_VERSION)
        out.setdefault("implement_convention_required", IMPLEMENT_CONVENTION_REQUIRED)
        out.setdefault("implement_convention_doc", IMPLEMENT_CONVENTION_DOC)
        annotated.append(out)
    return annotated


def build_report_notice() -> str:
    """报告头部的下游执行提示。"""
    return (
        "## 下游实现约定\n\n"
        f"- `implement_convention_version`: `{IMPLEMENT_CONVENTION_VERSION}`\n"
        f"- `implement_convention_required`: `{str(IMPLEMENT_CONVENTION_REQUIRED).lower()}`\n"
        f"- 约定文档: `{IMPLEMENT_CONVENTION_DOC}`\n"
        "- 实现 agent 必须先定位真实代码和测试入口,再按 item 修改;不得只改文档或生成演示性产物。\n"
    )
