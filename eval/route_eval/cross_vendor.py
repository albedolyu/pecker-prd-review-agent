"""跨 vendor 偏差度量 -- Cohen's κ + 漏报互补率 + 分歧率.

P2 双苍鹰决策核心. 跑同一组输入到两 vendor, 用以下三个独立指标判定:
    - kappa (Cohen's): 两 judge 一致性, 校准 chance agreement
    - complementary_recall: A/B 各自的独占召回 + 联合召回 + 互补率
    - disagreement_rate: 两 judge 在同一项上判不同分类的比例
"""
from __future__ import annotations

from collections import Counter
from typing import Any, Dict, Iterable, List, Set


def cohens_kappa(labels_a: List[Any], labels_b: List[Any]) -> float:
    """Cohen's κ -- 两 rater 在同一组样本上的标签一致性 (校准了 chance agreement).

    κ = (Po - Pe) / (1 - Pe)
        Po = observed agreement rate
        Pe = expected agreement by chance (基于各类别边际频率)

    Args:
        labels_a, labels_b: 等长 list, 每个元素是 hashable 标签 (e.g. severity, decision)

    Returns:
        float in [-1, 1], 1=完美一致, 0=随机一致, <0=系统性反向
    """
    if len(labels_a) != len(labels_b):
        raise ValueError(
            f"cohens_kappa: labels_a/b 长度不一致 ({len(labels_a)} vs {len(labels_b)})"
        )
    n = len(labels_a)
    if n == 0:
        return 0.0

    # observed agreement
    agree = sum(1 for a, b in zip(labels_a, labels_b) if a == b)
    po = agree / n

    # expected by chance: 各类别边际概率乘积之和
    cnt_a = Counter(labels_a)
    cnt_b = Counter(labels_b)
    all_labels: Set[Any] = set(cnt_a.keys()) | set(cnt_b.keys())
    pe = sum((cnt_a[lbl] / n) * (cnt_b[lbl] / n) for lbl in all_labels)

    if pe >= 1.0:
        # 全员同标签时 chance agreement = 1, 退化场景, 直接返 1
        return 1.0
    return round((po - pe) / (1 - pe), 4)


def complementary_recall(
    set_a: Iterable[Any],
    set_b: Iterable[Any],
    ground_truth: Iterable[Any],
) -> Dict[str, float]:
    """A/B 互补召回率分析 -- 用于决定是否值得跑双 advisor.

    Args:
        set_a, set_b: A/B 各自抓到的 hit_id 集合
        ground_truth: 完整 GT id 集合

    Returns:
        {
            a_recall: A 单独召回率,
            b_recall: B 单独召回率,
            joint_recall: A∪B 联合召回率,
            a_only_recall: A 独占贡献 (GT∩A∩~B / GT),
            b_only_recall: B 独占贡献,
            complementary_pct: (joint - max(a, b)) / max(a, b) -- 增量价值,
        }
    """
    sa = set(set_a)
    sb = set(set_b)
    gt = set(ground_truth)
    n_gt = len(gt) if gt else 0

    if n_gt == 0:
        return {
            "a_recall": 0.0, "b_recall": 0.0, "joint_recall": 0.0,
            "a_only_recall": 0.0, "b_only_recall": 0.0,
            "complementary_pct": 0.0,
        }

    a_hits = sa & gt
    b_hits = sb & gt
    joint = (sa | sb) & gt
    a_only = a_hits - b_hits
    b_only = b_hits - a_hits

    a_recall = len(a_hits) / n_gt
    b_recall = len(b_hits) / n_gt
    joint_recall = len(joint) / n_gt
    max_solo = max(a_recall, b_recall)
    comp_pct = ((joint_recall - max_solo) / max_solo) if max_solo > 0 else 0.0

    return {
        "a_recall": round(a_recall, 4),
        "b_recall": round(b_recall, 4),
        "joint_recall": round(joint_recall, 4),
        "a_only_recall": round(len(a_only) / n_gt, 4),
        "b_only_recall": round(len(b_only) / n_gt, 4),
        "complementary_pct": round(comp_pct, 4),
    }


def disagreement_rate(decisions_a: List[Any], decisions_b: List[Any]) -> float:
    """两 judge 在同一组样本上判不同决策的比例.

    Args:
        decisions_a, decisions_b: 等长决策列表 (e.g. ["keep", "drop", "merge", ...])

    Returns:
        float in [0, 1], 0=完全一致, 1=完全分歧
    """
    if len(decisions_a) != len(decisions_b):
        raise ValueError(
            f"disagreement_rate: 长度不一致 ({len(decisions_a)} vs {len(decisions_b)})"
        )
    n = len(decisions_a)
    if n == 0:
        return 0.0
    diff = sum(1 for a, b in zip(decisions_a, decisions_b) if a != b)
    return round(diff / n, 4)
