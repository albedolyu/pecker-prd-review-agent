from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def _rules_by_id() -> dict[str, dict]:
    with (ROOT / "review-rules-shared" / "review-checklist.yaml").open(
        encoding="utf-8"
    ) as f:
        data = yaml.safe_load(f)
    return {rule["id"]: rule for rule in data["rules"]}


def test_pm_rejection_reasons_are_encoded_as_rule_noise_guards() -> None:
    """Rejected PM feedback should narrow noisy triggers without deleting rules."""

    rules = _rules_by_id()

    v06_guard = rules["V-06"]["dont_fire_when"]
    assert "团队默认" in v06_guard
    assert "每页 10 条" in v06_guard
    assert "技术约定" in v06_guard

    ev01_guard = rules["EV-01"]["dont_fire_when"]
    assert "统一验收流程" in ev01_guard
    assert "验收负责人" in ev01_guard

    rc004_fire = rules["RC-004"]["fire_when"]
    assert "接口" in rc004_fire
    assert "跨系统" in rc004_fire

    rc004_guard = rules["RC-004"]["dont_fire_when"]
    assert "平台默认约定" in rc004_guard
    assert "普通 UI" in rc004_guard


def test_worker_prompt_contains_pm_rejection_noise_guards() -> None:
    text = (ROOT / "review-dimensions.yaml").read_text(encoding="utf-8")

    assert "2026-05-09 PM 驳回降噪" in text
    assert "分页默认为每页 10 条" in text
    assert "统一验收流程" in text
    assert "普通 UI / 文案 / 配置类 PRD" in text
