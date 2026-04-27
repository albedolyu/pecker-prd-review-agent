"""evaluation 数据集 + loader 冒烟测.

确保 CI 每次跑都能 catch 数据集结构破坏 (字段缺失 / 文件路径漂移 / 分布失衡).
所有测试离线跑, 不调任何 LLM/外部 API.
"""
from __future__ import annotations

import os
from collections import Counter
from pathlib import Path

import pytest

DATASET_NAMES = [
    "business_prd_gt",
    "template_prd",
    "advisor_conflicts",
    "hallucination",
    "intent",
]


# ----- 基础: 5 个数据集都能 load 且非空 -----

@pytest.mark.parametrize("name", DATASET_NAMES)
def test_load_dataset_returns_non_empty_list(name: str) -> None:
    """所有数据集 load 后必须返回非空 list[dict]."""
    from eval.route_eval.datasets.loader import load_dataset
    records = load_dataset(name)
    assert isinstance(records, list), f"dataset {name} 必须返回 list, 实际是 {type(records)}"
    assert len(records) > 0, f"dataset {name} 返回空列表"
    assert all(isinstance(r, dict) for r in records), f"dataset {name} 元素必须都是 dict"


def test_load_unknown_dataset_raises() -> None:
    """未知数据集名必须抛 ValueError 而不是默默返回空."""
    from eval.route_eval.datasets.loader import load_dataset
    with pytest.raises(ValueError, match="未知数据集"):
        load_dataset("nonexistent_xxx")


def test_list_datasets_returns_all_five() -> None:
    """list_datasets 必须返回 5 个数据集名."""
    from eval.route_eval.datasets.loader import list_datasets
    names = list_datasets()
    assert set(names) == set(DATASET_NAMES), f"期望 {DATASET_NAMES}, 实际 {names}"


# ----- 各数据集 schema -----

def test_business_prd_gt_schema() -> None:
    """业务 PRD GT: 每条含 prd_path / workspace / ground_truth (list[dict])."""
    from eval.route_eval.datasets.loader import load_dataset
    records = load_dataset("business_prd_gt")
    assert len(records) >= 3, f"应至少 3 个 workspace, 实际 {len(records)}"
    for r in records:
        assert "prd_path" in r and isinstance(r["prd_path"], str)
        assert "workspace" in r and isinstance(r["workspace"], str)
        assert "ground_truth" in r and isinstance(r["ground_truth"], list)
        # GT 至少有 3-5 条 issues
        assert len(r["ground_truth"]) >= 3, (
            f"workspace {r['workspace']} GT 太少: {len(r['ground_truth'])} (要求 >=3)"
        )
        for gt in r["ground_truth"]:
            assert "issue" in gt, f"GT 缺 issue 字段 in {r['workspace']}"
            assert "severity" in gt, f"GT 缺 severity 字段 in {r['workspace']}"


def test_business_prd_gt_files_exist() -> None:
    """manifest 引用的 PRD 文件实际必须存在 (catch 文件被删/重命名)."""
    from eval.route_eval.datasets.loader import load_dataset
    # loader 在加载时会 stat 文件存在性, 这里只要正常 load 即视为通过
    # 但也直接 double-check 一次
    project_root = Path(__file__).resolve().parent.parent
    records = load_dataset("business_prd_gt")
    for r in records:
        prd_abs = project_root / r["prd_path"]
        assert prd_abs.exists(), f"PRD 文件不存在: {prd_abs}"


def test_template_prd_schema() -> None:
    """模板 PRD: 每条含 prd_path / workspace / note."""
    from eval.route_eval.datasets.loader import load_dataset
    records = load_dataset("template_prd")
    assert len(records) >= 1
    for r in records:
        assert "prd_path" in r and isinstance(r["prd_path"], str)
        assert "workspace" in r and isinstance(r["workspace"], str)
        assert "note" in r and isinstance(r["note"], str)
    # 也要校验 PRD 文件存在
    project_root = Path(__file__).resolve().parent.parent
    for r in records:
        assert (project_root / r["prd_path"]).exists(), f"模板 PRD 不存在: {r['prd_path']}"


def test_advisor_conflicts_schema() -> None:
    """苍鹰冲突调解: 每条含 id / workspace / worker_outputs / ground_truth_resolution."""
    from eval.route_eval.datasets.loader import load_dataset
    records = load_dataset("advisor_conflicts")
    assert len(records) >= 5, f"应至少 5 条 (placeholder), 实际 {len(records)}"
    for r in records:
        assert "id" in r and isinstance(r["id"], str)
        assert "workspace" in r and isinstance(r["workspace"], str)
        assert "worker_outputs" in r and isinstance(r["worker_outputs"], list)
        assert len(r["worker_outputs"]) >= 2, f"{r['id']} worker_outputs 太少 (冲突至少 2 项)"
        # 每个 worker_output 至少含 id/issue/severity
        for w in r["worker_outputs"]:
            assert "id" in w
            assert "issue" in w
            assert "severity" in w
        assert "ground_truth_resolution" in r
        gtr = r["ground_truth_resolution"]
        assert isinstance(gtr, dict)
        assert "merged" in gtr and isinstance(gtr["merged"], list)
        assert "dropped" in gtr and isinstance(gtr["dropped"], list)
        assert "conflict_severity_correct" in gtr
        assert gtr["conflict_severity_correct"] in ("must", "should", "could")


def test_advisor_conflicts_placeholder_marker() -> None:
    """占位数据必须显式标 is_placeholder=true (PM 后补时才知道哪些待标)."""
    from eval.route_eval.datasets.loader import load_dataset
    records = load_dataset("advisor_conflicts")
    for r in records:
        gtr = r["ground_truth_resolution"]
        assert "is_placeholder" in gtr, f"{r['id']} 缺 is_placeholder 标记"
    # 至少一条 placeholder (当前阶段所有都是)
    placeholder_count = sum(
        1 for r in records if r["ground_truth_resolution"].get("is_placeholder") is True
    )
    assert placeholder_count >= 1, "advisor_conflicts 应至少 1 条 placeholder (待 PM 标注)"


def test_hallucination_schema() -> None:
    """幻觉: 每条含 id / item / wiki_pages / is_hallucination / construction_method."""
    from eval.route_eval.datasets.loader import load_dataset
    records = load_dataset("hallucination")
    assert len(records) >= 50
    valid_methods = {"real", "fake_ref", "fake_content", "paraphrase_only", "ungrounded_inference"}
    for r in records:
        assert "id" in r
        assert "item" in r and isinstance(r["item"], dict)
        assert "issue" in r["item"]
        assert "evidence_content" in r["item"]
        assert "wiki_pages" in r and isinstance(r["wiki_pages"], dict)
        # wiki_pages 每条 ≤ 500 字符
        for page_name, content in r["wiki_pages"].items():
            assert len(content) <= 500, (
                f"{r['id']} wiki page {page_name} 超过 500 字符: {len(content)}"
            )
        assert isinstance(r["is_hallucination"], bool)
        assert r["construction_method"] in valid_methods, (
            f"{r['id']} method 不在 {valid_methods}: {r['construction_method']}"
        )


def test_hallucination_balance() -> None:
    """假/真 30:30 ±5 (实际 30:30 精确)."""
    from eval.route_eval.datasets.loader import load_dataset
    records = load_dataset("hallucination")
    real_count = sum(1 for r in records if not r["is_hallucination"])
    fake_count = sum(1 for r in records if r["is_hallucination"])
    assert abs(real_count - 30) <= 5, f"real_count={real_count}, 应在 25-35 之间"
    assert abs(fake_count - 30) <= 5, f"fake_count={fake_count}, 应在 25-35 之间"


def test_hallucination_construction_method_distribution() -> None:
    """4 种构造手法 (假依据) 大致等量分布: fake_ref/fake_content 各 8, paraphrase/inference 各 7."""
    from eval.route_eval.datasets.loader import load_dataset
    records = load_dataset("hallucination")
    dist = Counter(r["construction_method"] for r in records if r["is_hallucination"])
    # 等量构造允许 ±2 浮动
    assert abs(dist["fake_ref"] - 8) <= 2, f"fake_ref={dist['fake_ref']}, 应在 6-10"
    assert abs(dist["fake_content"] - 8) <= 2, f"fake_content={dist['fake_content']}, 应在 6-10"
    assert abs(dist["paraphrase_only"] - 7) <= 2, f"paraphrase_only={dist['paraphrase_only']}"
    assert abs(dist["ungrounded_inference"] - 7) <= 2, (
        f"ungrounded_inference={dist['ungrounded_inference']}"
    )


def test_intent_schema() -> None:
    """意图: 每条含 prd_name / user_instruction / expected_tier."""
    from eval.route_eval.datasets.loader import load_dataset
    records = load_dataset("intent")
    valid_tiers = {"opus", "sonnet", "haiku", "reject"}
    for r in records:
        assert "prd_name" in r and isinstance(r["prd_name"], str)
        assert "user_instruction" in r and isinstance(r["user_instruction"], str)
        assert r["expected_tier"] in valid_tiers, (
            f"unknown tier: {r['expected_tier']} for {r['prd_name']}"
        )
        # prd_name 不能是 test1/test2 这种占位
        assert not r["prd_name"].lower().startswith(("test1", "test2", "demo", "example")), (
            f"prd_name 太敷衍: {r['prd_name']}"
        )


def test_intent_label_distribution() -> None:
    """各 tier 至少 10 条 (reject 至少 5 条)."""
    from eval.route_eval.datasets.loader import load_dataset
    records = load_dataset("intent")
    dist = Counter(r["expected_tier"] for r in records)
    assert dist["opus"] >= 15, f"opus={dist['opus']}, 期望 >=15"
    assert dist["sonnet"] >= 15, f"sonnet={dist['sonnet']}, 期望 >=15"
    assert dist["haiku"] >= 10, f"haiku={dist['haiku']}, 期望 >=10"
    assert dist["reject"] >= 5, f"reject={dist['reject']}, 期望 >=5"


# ----- 路径 / 工作目录无关性 -----

def test_loader_works_from_any_cwd(tmp_path, monkeypatch) -> None:
    """loader 必须工作目录无关 (用 __file__ 算根, 不用 os.getcwd)."""
    monkeypatch.chdir(tmp_path)
    from eval.route_eval.datasets.loader import load_dataset
    # 切到 tmp_path 后仍能正常加载
    for name in DATASET_NAMES:
        records = load_dataset(name)
        assert len(records) > 0, f"切 cwd 后 {name} 加载失败"
