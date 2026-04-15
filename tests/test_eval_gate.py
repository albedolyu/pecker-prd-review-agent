"""
F4: Eval CI Gate — 评审质量回归门禁

用 scorer 层的 calculate_scores 做纯计算回归,不跑真实 LLM 评审。
pytest 默认跳过(需要 -m eval 触发),避免常规 pytest 被拖慢。

运行方式:
    pytest -m eval                    # 跑 CI gate
    PECKER_ENV=prod pytest -m eval    # 用生产阈值

阈值从 config 读:
    - EVAL_MIN_OVERALL_SCORE
    - EVAL_MIN_RECALL
    - EVAL_MIN_PRECISION

测试设计:
1. 构造固定的 mock review_items + planted bugs(受控数据)
2. 跑 match_items_to_bugs + verify_evidence + calculate_scores
3. 断言输出稳定在阈值以上

这保证的是 scorer 逻辑本身的稳定性,不保证 LLM 评审质量。
LLM 质量回归由 `cuckoo_eval.py` 真实跑一次后检查 overall_verdict 来覆盖。
"""
import pytest
from config import EVAL_MIN_OVERALL_SCORE, EVAL_MIN_RECALL, EVAL_MIN_PRECISION
from cuckoo_scorer import match_items_to_bugs, verify_evidence, calculate_scores


def _fixture_review_items():
    """固定的 review 输出 — 6 条改进项,覆盖 4 类依据"""
    return [
        {
            "id": "R-001",
            "location": "3.7",
            "problem": "开庭公告排序规则笔误,切换方向与默认相同",
            "severity": "must",
            "evidence_type": "A",
            "evidence_content": "wiki/概念-排序规则.md",
            "rule_id": "V-10",
        },
        {
            "id": "R-002",
            "location": "4.2",
            "problem": "筛选项仲裁机构与发布机构三处不一致",
            "severity": "must",
            "evidence_type": "B",
            "evidence_content": "RC-008",
            "rule_id": "RC-008",
        },
        {
            "id": "R-003",
            "location": "2.2",
            "problem": "字段映射 A 或 B 无降级说明",
            "severity": "must",
            "evidence_type": "B",
            "evidence_content": "RC-015",
            "rule_id": "RC-015",
        },
        {
            "id": "R-004",
            "location": "4",
            "problem": "UI 四态缺失(加载中/失败/空数据/无结果)",
            "severity": "must",
            "evidence_type": "C",
            "evidence_content": "待确定",
            "rule_id": "V-08",
        },
        {
            "id": "R-005",
            "location": "1.1",
            "problem": "误报项 - 完全不相关",
            "severity": "should",
            "evidence_type": "A",
            "evidence_content": "wiki/不存在的页面.md",
            "rule_id": "V-02",
        },
        {
            "id": "R-006",
            "location": "1.2",
            "problem": "页面信息提供方未定义",
            "severity": "should",
            "evidence_type": "B",
            "evidence_content": "RC-004",
            "rule_id": "RC-004",
        },
    ]


def _fixture_test_case():
    """固定的 planted bugs — 5 条,命中 4 条,漏 1 条"""
    return {
        "name": "fixture",
        "planted_bugs": [
            {
                "id": "BUG-001",
                "location": "3.7",
                "type": "笔误",
                "severity": "must",
                "description": "开庭公告排序切换方向相同",
                "keywords": ["排序", "切换", "从晚到早"],
            },
            {
                "id": "BUG-002",
                "location": "4.2",
                "type": "不一致",
                "severity": "must",
                "description": "仲裁机构与发布机构不一致",
                "keywords": ["仲裁机构", "发布机构", "不一致"],
            },
            {
                "id": "BUG-003",
                "location": "2.2",
                "type": "歧义",
                "severity": "must",
                "description": "字段映射 A 或 B 无降级",
                "keywords": ["字段映射", "或", "降级"],
            },
            {
                "id": "BUG-004",
                "location": "4",
                "type": "缺失",
                "severity": "must",
                "description": "UI 四态缺失",
                "keywords": ["四态", "加载中", "空数据"],
            },
            {
                "id": "BUG-005",
                "location": "1.2",
                "type": "缺失",
                "severity": "should",
                "description": "页面信息提供方未定义",
                "keywords": ["信息提供方", "定义"],
            },
        ],
        "non_issues": [
            {"location": "1.1", "reason": "1.1 本身不是问题"},
        ],
    }


@pytest.mark.eval
def test_scorer_meets_overall_threshold(tmp_path):
    """F4: scorer 对固定 fixture 的 overall_score 必须 >= 阈值"""
    items = _fixture_review_items()
    test_case = _fixture_test_case()

    matches = match_items_to_bugs(items, test_case["planted_bugs"])
    # 构造最小 workspace(verify_evidence 需要读 wiki 目录)
    (tmp_path / "wiki").mkdir()
    evidence_results = verify_evidence(items, str(tmp_path))
    scores = calculate_scores(matches, evidence_results, items)

    print(f"\nF4 gate scores: overall={scores['overall_score']:.2f}, "
          f"recall={scores['recall']:.2f}, precision={scores['precision']:.2f}")
    print(f"F4 thresholds: overall>={EVAL_MIN_OVERALL_SCORE}, "
          f"recall>={EVAL_MIN_RECALL}, precision>={EVAL_MIN_PRECISION}")

    assert scores["overall_score"] >= EVAL_MIN_OVERALL_SCORE, (
        f"overall_score {scores['overall_score']:.2f} < {EVAL_MIN_OVERALL_SCORE}"
    )
    assert scores["recall"] >= EVAL_MIN_RECALL, (
        f"recall {scores['recall']:.2f} < {EVAL_MIN_RECALL}"
    )
    assert scores["precision"] >= EVAL_MIN_PRECISION, (
        f"precision {scores['precision']:.2f} < {EVAL_MIN_PRECISION}"
    )


@pytest.mark.eval
def test_scorer_verdict_is_not_fail(tmp_path):
    """F4: scorer 的 overall_verdict 不能是 FAIL"""
    items = _fixture_review_items()
    test_case = _fixture_test_case()

    matches = match_items_to_bugs(items, test_case["planted_bugs"])
    (tmp_path / "wiki").mkdir()
    evidence_results = verify_evidence(items, str(tmp_path))
    scores = calculate_scores(matches, evidence_results, items)

    assert scores["overall_verdict"] != "FAIL", (
        f"Eval 判定 FAIL: {scores}"
    )
