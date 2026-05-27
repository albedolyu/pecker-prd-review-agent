"""
杜鹃 (Cuckoo) Eval Agent — Pecker评审质量评测

⚠ 已废弃 (DEPRECATED, 2026-04-29):
  - 本工具是早期手卷 eval, 与规则无强绑定, 缺乏 P/R baseline 概念
  - **替代品**: scripts/rule_regression.py — 规则级 P/R 回归 + baseline gate + CI 集成
  - **保留原因**:
    1. 向后兼容: 历史 test_case JSON 还在被引用, 不强行删
    2. cuckoo_scorer 内部函数 (match_items_to_bugs / calculate_scores) 还被
       eval/route_eval/scorers/cuckoo_adapter.py 复用 — 那是 adapter 层有效用
    3. _safe_get / _atomic_write_json / append_eval_history 等 helper 仍是
       cuckoo_eval_hardening 测试覆盖范围
  - **退役 trigger**: 当 rule_regression baseline 覆盖所有现役规则
    (workspace-sample/review-rules/review-checklist.yaml 全部 rule 都有
    positive_example + negative_example), 且历史 test_case JSON 全迁移完毕,
    再删本文件. 详见 docs/v1_vs_v2_feedback_strategy.md

对抗性验证：试图推翻Pecker的评审结果，而非确认。
三态判定：PASS / FAIL / PARTIAL

用法：
  # 完整评测：匹配预埋 bug + 依据验证
  python cuckoo_eval.py --report output/PRD_改动报告_20260411.md --test-case eval/test_cases/sample-case.json

  # 仅做依据验证（不需要测试用例）
  python cuckoo_eval.py --report output/PRD_改动报告_20260411.md --workspace ./workspace

  # 从已有报告反向生成测试用例
  python cuckoo_eval.py --generate-test-case output/PRD_改动报告_20260411.md -o eval/test_cases/sample-case.json
"""

import argparse
import json
import os
import re
import sys
import warnings
from datetime import datetime

# 模块级 deprecation warning — 仅在 CLI 直接调用时打印, 避免污染 cuckoo_scorer adapter 路径
# 调用 main() 时会显式 emit, import 路径不打扰 (otherwise 测试输出会被噪音淹没).
#
# 但 import 路径仍 emit 一次轻量 DeprecationWarning, 让走 -W error::DeprecationWarning
# 跑测试 / lint 的人能 catch 到误用 (而不是直接 silently 让老调用 fall-through).
# 关键点: 用 stacklevel=2 让 warning 指向 importer 而不是本文件;
# 而且 default filter 下 DeprecationWarning 仅在 __main__ 触发时打印,
# 测试 / 普通 import 不会被噪音淹没. 详见 docs/MIGRATION_v1_to_v2.md.
warnings.warn(
    "cuckoo_eval 已废弃 — 改用 scripts/rule_regression.py (P/R baseline + CI gate). "
    "详见 docs/MIGRATION_v1_to_v2.md.",
    DeprecationWarning,
    stacklevel=2,
)

from cuckoo_parser import parse_review_report
from cuckoo_scorer import (
    match_items_to_bugs,
    verify_evidence,
    calculate_scores,
    aggregate_rule_metrics,
    update_rule_performance_history,
    calculate_rule_coverage_matrix,
)

# 向后兼容：其他模块可能直接从 cuckoo_eval 导入
from cuckoo_parser import parse_review_report, _parse_markdown_items, _parse_loose_items, _extract_fields_from_block


# ── ASCII Art ──

CUCKOO_ART = r"""
        ,-.
       / \  `.  __..-,O
      :   \ --''_..-'.'
      |    . .-' `. '.
      :     .     .`.'
       \     `.  /  ..
        \      `.   ' .
         `,       `.   \
        ,|,`.        `-.\
       '.||  ``-....__..`
        |  |
        |__|
        /||\
       //||\\
      // || \\
   __//__||__\__
  '--------------'
"""

# 杜鹃吐槽语
VERDICT_QUIPS = {
    "PASS": "这只Pecker还算靠谱。",
    "FAIL": "这只Pecker该回炉重造了。",
    "PARTIAL": "勉强及格，但杜鹃保留意见。",
}


# ── Eval 报告生成 ──

def generate_eval_report(test_case, scores, matches, evidence_results):
    """生成 Markdown 格式的评测报告"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    verdict = scores["overall_verdict"]
    detail = scores["detail"]
    _, _, ev_details = evidence_results

    lines = []

    # 杜鹃登场
    lines.append(CUCKOO_ART)
    lines.append(f"# 杜鹃评测报告")
    lines.append("")
    lines.append(f"> VERDICT: **{verdict}** -- {VERDICT_QUIPS[verdict]}")
    lines.append("")

    # 测试概览
    lines.append("## 测试概览")
    lines.append("")
    lines.append(f"- 测试名称: {test_case.get('name', '未命名')}")
    lines.append(f"- PRD 文件: {test_case.get('prd_file', '未指定')}")
    lines.append(f"- 预埋 bug 数: {detail['total_bugs']}")
    lines.append(f"- Pecker改进项数: {detail['total_items']}")
    lines.append(f"- 评测时间: {now}")
    lines.append("")

    # 各维度得分
    lines.append("## 各维度得分")
    lines.append("")
    lines.append("| 维度 | 得分 | 权重 | 说明 |")
    lines.append("|------|------|------|------|")
    lines.append(f"| 召回率 (Recall) | {scores['recall']:.1%} | 30% | 命中 {detail['hit_count']} / 预埋 {detail['total_bugs']} |")
    lines.append(f"| 精确率 (Precision) | {scores['precision']:.1%} | 20% | 真阳 {detail['hit_count']} / 总发现 {detail['total_items']} |")
    lines.append(f"| 位置准确率 | {scores['location_accuracy']:.1%} | 10% | 位置匹配正确数 / 命中数 |")
    lines.append(f"| 依据可靠度 | {scores['evidence_reliability']:.1%} | 20% | 验证通过 {detail['verified_evidence']} / 总依据 {detail['verified_evidence'] + detail['failed_evidence']} |")
    lines.append(f"| 严重度准确率 | {scores['severity_accuracy']:.1%} | 10% | 分级正确数 / 命中数 |")
    lines.append(f"| 格式完整度 | {scores['format_completeness']:.1%} | 10% | 字段齐全的改进项 / 总改进项 |")
    lines.append(f"| **综合得分** | **{scores['overall_score']:.1%}** | - | 加权平均 |")
    lines.append("")

    # 命中明细
    lines.append("## 命中明细")
    lines.append("")
    if matches["hits"]:
        for h in matches["hits"]:
            bug = h["bug"]
            item = h["item"]
            lines.append(f"### {bug['id']} -> {item['id']}")
            lines.append(f"- Bug: [{bug['type']}] {bug['description']}")
            lines.append(f"- Bug 位置: {bug['location']}")
            lines.append(f"- 改进项: {item['problem']}")
            lines.append(f"- 改进项位置: {item['location']}")
            lines.append(f"- 匹配分: {h['score']} | 位置匹配: {'Y' if h['location_match'] else 'N'} | 关键词命中: {h['keyword_hits']} | 严重度: {'Y' if h['severity_match'] else 'N'}")
            lines.append("")
    else:
        lines.append("（无命中）")
        lines.append("")

    # 漏报明细
    lines.append("## 漏报明细")
    lines.append("")
    if matches["misses"]:
        for bug in matches["misses"]:
            lines.append(f"### {bug['id']} -- 漏报!")
            lines.append(f"- 类型: {bug['type']}")
            lines.append(f"- 位置: {bug['location']}")
            lines.append(f"- 严重度: {bug['severity']}")
            lines.append(f"- 描述: {bug['description']}")
            lines.append(f"- 关键词: {', '.join(bug.get('keywords', []))}")
            lines.append("")
    else:
        lines.append("（无漏报）")
        lines.append("")

    # 误报明细
    lines.append("## 误报 / 额外发现")
    lines.append("")
    if matches["false_positives"]:
        for item in matches["false_positives"]:
            lines.append(f"### {item['id']} -- 未匹配预埋 bug")
            lines.append(f"- 位置: {item['location']}")
            lines.append(f"- 问题: {item['problem']}")
            lines.append(f"- 严重度: {item.get('severity', '未标注')}")
            lines.append(f"- 依据: [{item.get('evidence_type', '?')}] {item.get('evidence_content', '无')[:100]}")
            lines.append("")
    else:
        lines.append("（无误报）")
        lines.append("")

    # 依据验证明细
    lines.append("## 依据验证明细")
    lines.append("")
    if ev_details:
        lines.append("| 改进项 | 依据类型 | 验证结果 | 说明 |")
        lines.append("|--------|----------|----------|------|")
        for d in ev_details:
            status = "PASS" if d["verified"] else "FAIL"
            lines.append(f"| {d['item_id']} | {d['evidence_type']} | {status} | {d['reason'][:80]} |")
        lines.append("")
    else:
        lines.append("（无依据需要验证）")
        lines.append("")

    # 最终判定
    lines.append("---")
    lines.append("")
    lines.append(f"## VERDICT: {verdict}")
    lines.append("")
    lines.append(f"> {VERDICT_QUIPS[verdict]}")
    lines.append("")

    return "\n".join(lines)


def generate_evidence_only_report(evidence_results, review_items):
    """生成仅包含依据验证的报告（不需要测试用例时使用）"""
    verified, failed, details = evidence_results
    total = verified + failed
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    reliability = verified / total if total > 0 else 0.0
    if reliability >= 0.80:
        verdict = "PASS"
    elif reliability >= 0.50:
        verdict = "PARTIAL"
    else:
        verdict = "FAIL"

    lines = []
    lines.append(CUCKOO_ART)
    lines.append("# 杜鹃依据验证报告")
    lines.append("")
    lines.append(f"> VERDICT: **{verdict}** -- {VERDICT_QUIPS[verdict]}")
    lines.append("")
    lines.append("## 概览")
    lines.append("")
    lines.append(f"- 改进项总数: {len(review_items)}")
    lines.append(f"- 依据验证通过: {verified}")
    lines.append(f"- 依据验证失败: {failed}")
    lines.append(f"- 依据可靠度: {reliability:.1%}")
    lines.append(f"- 评测时间: {now}")
    lines.append("")

    lines.append("## 验证明细")
    lines.append("")
    if details:
        lines.append("| 改进项 | 依据类型 | 验证结果 | 说明 |")
        lines.append("|--------|----------|----------|------|")
        for d in details:
            status = "PASS" if d["verified"] else "FAIL"
            lines.append(f"| {d['item_id']} | {d['evidence_type']} | {status} | {d['reason'][:80]} |")
        lines.append("")

        # 失败项详情
        failed_items = [d for d in details if not d["verified"]]
        if failed_items:
            lines.append("## 失败项详情")
            lines.append("")
            for d in failed_items:
                lines.append(f"### {d['item_id']}")
                lines.append(f"- 依据类型: {d['evidence_type']}")
                lines.append(f"- 依据内容: {d['evidence_content']}")
                lines.append(f"- 失败原因: {d['reason']}")
                lines.append("")

    lines.append("---")
    lines.append("")
    lines.append(f"## VERDICT: {verdict}")
    lines.append("")
    lines.append(f"> {VERDICT_QUIPS[verdict]}")
    lines.append("")

    return "\n".join(lines)


# ── 预设测试用例生成器 ──

def generate_test_case_from_report(report_path):
    """从已有的评审报告反向生成测试用例

    把当前改进项作为"预期发现"，方便快速建立 baseline
    """
    items = parse_review_report(report_path)

    if not items:
        print(f"WARNING: 未从报告中解析到任何改进项: {report_path}")
        return None

    # 从报告文件名推断 PRD 名称
    basename = os.path.basename(report_path)
    prd_name = re.sub(r'PRD_改动报告_\d+\.md', '', basename).strip("_")
    if not prd_name:
        prd_name = basename

    planted_bugs = []
    for i, item in enumerate(items, 1):
        # 从改进项的文本中提取关键词
        text = item.get("problem", "") + " " + item.get("suggestion", "")
        # 取最长的名词短语作为关键词（简单策略：按标点分段取前几个词）
        words = re.findall(r'[\u4e00-\u9fa5a-zA-Z]+', text)
        keywords = list(set(words[:5]))  # 取前 5 个不重复的词

        # 推断 bug 类型
        bug_type = _infer_bug_type(text)

        planted_bugs.append({
            "id": f"BUG-{i:03d}",
            "location": item.get("location", ""),
            "type": bug_type,
            "severity": item.get("severity", "should"),
            "description": item.get("problem", "")[:100],
            "keywords": keywords,
        })

    test_case = {
        "name": f"{prd_name} baseline 测试",
        "prd_file": "",  # 需要手动填入
        "generated_from": report_path,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "planted_bugs": planted_bugs,
        "non_issues": [],  # 需要手动填入
    }

    return test_case


def _infer_bug_type(text):
    """从问题描述推断 bug 类型"""
    type_indicators = {
        "笔误": ["笔误", "拼写", "错字", "打错", "typo"],
        "不一致": ["不一致", "矛盾", "冲突", "前后不同", "前后矛盾"],
        "字段类型": ["字段", "类型不匹配", "数据类型", "格式错误"],
        "缺失": ["缺失", "遗漏", "缺少", "未定义", "未说明", "没有提及"],
        "歧义": ["歧义", "模糊", "不明确", "可能有多种理解"],
    }
    text_lower = text.lower()
    for bug_type, indicators in type_indicators.items():
        if any(ind in text_lower for ind in indicators):
            return bug_type
    return "歧义"  # 默认


# ── Eval History 跨次对比 ──

EVAL_HISTORY_FILE = "eval_history.json"


def _get_eval_history_path(workspace):
    """eval_history.json 路径"""
    return os.path.join(workspace, "output", EVAL_HISTORY_FILE)


def _safe_get(scores, key, default=0.0):
    """从 scores 里取值,缺失或类型错误一律走 default(防止旧/降级 scorer shape 崩溃)."""
    v = scores.get(key, default) if isinstance(scores, dict) else default
    try:
        return round(float(v), 4)
    except (TypeError, ValueError):
        return default


def _atomic_write_json(path, data):
    """原子写 JSON: 先写 .tmp 再 rename,避免 crash 中损坏目标文件."""
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, path)  # Windows/Linux 都原子


def append_eval_history(workspace, test_case_name, scores, model=None):
    """每次评测追加一条记录到 eval_history.json

    加固点 (Round 4):
    - 读取:损坏/缺失文件不抛,当作空历史
    - _safe_get:缺 key / 非数值字段降级为 0.0,不抛 KeyError
    - 写入:原子 rename,中途 crash 不污染历史
    """
    history_path = _get_eval_history_path(workspace)

    history = []
    if os.path.isfile(history_path):
        try:
            with open(history_path, "r", encoding="utf-8") as f:
                history = json.load(f)
            if not isinstance(history, list):
                history = []
        except (json.JSONDecodeError, OSError):
            history = []

    detail = scores.get("detail", {}) if isinstance(scores, dict) else {}

    entry = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "test_case": test_case_name,
        "model": model or "unknown",
        "overall_score": _safe_get(scores, "overall_score"),
        "overall_verdict": scores.get("overall_verdict", "UNKNOWN") if isinstance(scores, dict) else "UNKNOWN",
        "recall": _safe_get(scores, "recall"),
        "precision": _safe_get(scores, "precision"),
        "location_accuracy": _safe_get(scores, "location_accuracy"),
        "evidence_reliability": _safe_get(scores, "evidence_reliability"),
        "severity_accuracy": _safe_get(scores, "severity_accuracy"),
        "format_completeness": _safe_get(scores, "format_completeness"),
        "detail": {
            "total_bugs": detail.get("total_bugs", 0),
            "total_items": detail.get("total_items", 0),
            "hit_count": detail.get("hit_count", 0),
        },
    }

    history.append(entry)

    os.makedirs(os.path.dirname(history_path), exist_ok=True)
    _atomic_write_json(history_path, history)

    return entry


def print_eval_trend(workspace, test_case_name=None, last_n=5):
    """打印最近 N 次评测的趋势对比

    Round 4: 加固 — history 文件损坏不抛,静默跳过趋势显示。
    """
    history_path = _get_eval_history_path(workspace)
    if not os.path.isfile(history_path):
        return

    try:
        with open(history_path, "r", encoding="utf-8") as f:
            history = json.load(f)
        if not isinstance(history, list):
            return
    except (json.JSONDecodeError, OSError):
        return

    if test_case_name:
        history = [h for h in history if h.get("test_case") == test_case_name]

    if len(history) < 2:
        return  # 不够对比

    recent = history[-last_n:]
    print("\n" + "=" * 60)
    print("评测趋势对比")
    print("=" * 60)
    print(f"{'时间':<18} {'得分':>6} {'判定':<8} {'召回':>6} {'精确':>6} {'依据':>6} {'bug':>4} {'项':>4} {'命中':>4}")
    print("-" * 78)
    for h in recent:
        print(
            f"{h['timestamp']:<18} "
            f"{h['overall_score']:>5.1%} "
            f"{h['overall_verdict']:<8} "
            f"{h['recall']:>5.1%} "
            f"{h['precision']:>5.1%} "
            f"{h['evidence_reliability']:>5.1%} "
            f"{h['detail']['total_bugs']:>4} "
            f"{h['detail']['total_items']:>4} "
            f"{h['detail']['hit_count']:>4}"
        )

    # 趋势箭头
    if len(recent) >= 2:
        prev = recent[-2]["overall_score"]
        curr = recent[-1]["overall_score"]
        diff = curr - prev
        arrow = "+" if diff > 0 else ""
        print(f"\n  vs 上次: {arrow}{diff:.1%}")


# ── CLI 入口 ──

def _emit_deprecation_notice():
    """CLI 入口打印 deprecation notice. import 路径不打扰."""
    msg = (
        "[DEPRECATED] cuckoo_eval.py 已废弃, 建议迁移到 scripts/rule_regression.py "
        "(规则级 P/R 回归 + baseline gate). 详见 docs/v1_vs_v2_feedback_strategy.md."
    )
    # 走 stderr 避免污染 stdout 报告; 同时 warnings 让 -W error 模式能 catch
    print(msg, file=sys.stderr)
    warnings.warn(msg, DeprecationWarning, stacklevel=2)


def main():
    _emit_deprecation_notice()

    parser = argparse.ArgumentParser(
        description="杜鹃 (Cuckoo) — Pecker PRD 评审质量评测 [DEPRECATED, 用 scripts/rule_regression.py]",
        epilog=(
            "示例:\n"
            "  python cuckoo_eval.py --report output/PRD_改动报告_20260411.md --test-case eval/test_cases/sample-case.json\n"
            "  python cuckoo_eval.py --report output/PRD_改动报告_20260411.md --workspace ./workspace\n"
            "  python cuckoo_eval.py --generate-test-case output/PRD_改动报告_20260411.md -o eval/test_cases/sample-case.json\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument("--report", help="Pecker评审报告路径")
    parser.add_argument("--test-case", help="测试用例 JSON 文件路径")
    parser.add_argument("--workspace", default="./workspace", help="工作目录路径（默认 ./workspace）")
    parser.add_argument("--generate-test-case", metavar="REPORT", help="从评审报告反向生成测试用例")
    parser.add_argument("-o", "--output", help="输出文件路径（报告或测试用例）")

    args = parser.parse_args()

    # 模式1：从报告生成测试用例
    if args.generate_test_case:
        report_path = os.path.abspath(args.generate_test_case)
        if not os.path.isfile(report_path):
            print(f"ERROR: 报告文件不存在: {report_path}")
            sys.exit(1)

        print(CUCKOO_ART)
        print("杜鹃正在从评审报告反向生成测试用例...\n")

        test_case = generate_test_case_from_report(report_path)
        if not test_case:
            sys.exit(1)

        if args.output:
            out_path = os.path.abspath(args.output)
            os.makedirs(os.path.dirname(out_path), exist_ok=True)
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(test_case, f, ensure_ascii=False, indent=2)
            print(f"测试用例已写入: {out_path}")
            print(f"预埋 bug 数: {len(test_case['planted_bugs'])}")
            print("\n注意：请手动检查并补充 prd_file 和 non_issues 字段")
        else:
            print(json.dumps(test_case, ensure_ascii=False, indent=2))

        sys.exit(0)

    # 后续模式都需要 --report
    if not args.report:
        parser.print_help()
        sys.exit(1)

    report_path = os.path.abspath(args.report)
    if not os.path.isfile(report_path):
        print(f"ERROR: 报告文件不存在: {report_path}")
        sys.exit(1)

    workspace = os.path.abspath(args.workspace)

    print(CUCKOO_ART)
    print("杜鹃开始评测...\n")

    # 解析评审报告
    review_items = parse_review_report(report_path)
    print(f"从报告中解析到 {len(review_items)} 条改进项")

    if not review_items:
        print("WARNING: 未解析到任何改进项，杜鹃无事可做")
        sys.exit(0)

    # 依据验证（不管有没有测试用例都做）
    print("正在验证依据...")
    evidence_results = verify_evidence(review_items, workspace)
    verified, failed, _ = evidence_results
    print(f"依据验证: 通过 {verified}, 失败 {failed}")

    # 模式2：完整评测（有测试用例）
    if args.test_case:
        tc_path = os.path.abspath(args.test_case)
        if not os.path.isfile(tc_path):
            print(f"ERROR: 测试用例文件不存在: {tc_path}")
            sys.exit(1)

        with open(tc_path, "r", encoding="utf-8") as f:
            test_case = json.load(f)

        planted_bugs = test_case.get("planted_bugs", [])
        print(f"测试用例: {test_case.get('name', '未命名')}")
        print(f"预埋 bug 数: {len(planted_bugs)}")

        # 匹配
        print("正在匹配改进项与预埋 bug...")
        matches = match_items_to_bugs(review_items, planted_bugs)
        print(f"命中: {len(matches['hits'])}, 漏报: {len(matches['misses'])}, 误报/额外: {len(matches['false_positives'])}")

        # 评分
        scores = calculate_scores(matches, evidence_results, review_items)
        print(f"\n综合得分: {scores['overall_score']:.1%}")
        print(f"VERDICT: {scores['overall_verdict']} -- {VERDICT_QUIPS[scores['overall_verdict']]}\n")

        # F2: 规则级指标聚合 + 写回 rule_performance_history.json
        print("正在聚合规则级指标...")
        rule_metrics = aggregate_rule_metrics(matches, review_items)
        if rule_metrics:
            prd_label = test_case.get("name", "未命名")
            updated = update_rule_performance_history(workspace, rule_metrics, prd_name=prd_label)
            print(f"规则级指标: 覆盖 {len(rule_metrics)} 条规则, 已回写 {updated} 条到 rule_performance_history.json")

            # 单独输出 rule_level_metrics.json 便于观测
            metrics_path = os.path.join(workspace, "output", "rule_level_metrics.json")
            os.makedirs(os.path.dirname(metrics_path), exist_ok=True)
            with open(metrics_path, "w", encoding="utf-8") as f:
                json.dump({
                    "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
                    "test_case": prd_label,
                    "rules": rule_metrics,
                }, f, ensure_ascii=False, indent=2)
            print(f"规则级指标报告: {metrics_path}")

        # 规则覆盖矩阵 (借鉴百灵 scenario_coverage)
        coverage = calculate_rule_coverage_matrix(review_items, workspace)
        coverage_path = os.path.join(workspace, "output", "rule_coverage_matrix.json")
        with open(coverage_path, "w", encoding="utf-8") as f:
            json.dump({
                "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
                "test_case": test_case.get("name", "未命名"),
                **coverage,
            }, f, ensure_ascii=False, indent=2)
        print(
            f"规则覆盖率: {coverage['covered_rules']}/{coverage['total_rules']} "
            f"({coverage['coverage_rate']:.1%}),未覆盖 {len(coverage['uncovered_rule_ids'])} 条 "
            f"-> {coverage_path}"
        )

        # 生成报告
        report = generate_eval_report(test_case, scores, matches, evidence_results)

        # 追加 eval history 并打印趋势
        append_eval_history(workspace, test_case.get("name", "未命名"), scores)
        print_eval_trend(workspace, test_case.get("name"))

    # 模式3：仅依据验证（无测试用例）
    else:
        print("\n未提供测试用例，仅执行依据验证\n")
        report = generate_evidence_only_report(evidence_results, review_items)

    # 输出报告
    if args.output:
        out_path = os.path.abspath(args.output)
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(report)
        print(f"评测报告已写入: {out_path}")
    else:
        print(report)


if __name__ == "__main__":
    main()
