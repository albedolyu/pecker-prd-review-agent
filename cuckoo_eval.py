"""
杜鹃 (Cuckoo) Eval Agent — 啄木鸟评审质量评测

对抗性验证：试图推翻啄木鸟的评审结果，而非确认。
三态判定：PASS / FAIL / PARTIAL

用法：
  # 完整评测：匹配预埋 bug + 依据验证
  python cuckoo_eval.py --report output/PRD_改动报告_20260411.md --test-case eval/test_cases/劳动仲裁.json

  # 仅做依据验证（不需要测试用例）
  python cuckoo_eval.py --report output/PRD_改动报告_20260411.md --workspace ./workspace

  # 从已有报告反向生成测试用例
  python cuckoo_eval.py --generate-test-case output/PRD_改动报告_20260411.md -o eval/test_cases/劳动仲裁.json
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime

from cuckoo_parser import parse_review_report
from cuckoo_scorer import match_items_to_bugs, verify_evidence, calculate_scores

# 向后兼容：其他模块可能直接从 cuckoo_eval 导入
from cuckoo_parser import parse_review_report, _parse_markdown_items, _parse_loose_items, _extract_fields_from_block
from cuckoo_scorer import match_items_to_bugs, verify_evidence, calculate_scores


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
    "PASS": "这只啄木鸟还算靠谱。",
    "FAIL": "这只啄木鸟该回炉重造了。",
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
    lines.append(f"- 啄木鸟改进项数: {detail['total_items']}")
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


# ── CLI 入口 ──

def main():
    parser = argparse.ArgumentParser(
        description="杜鹃 (Cuckoo) — 啄木鸟 PRD 评审质量评测",
        epilog=(
            "示例:\n"
            "  python cuckoo_eval.py --report output/PRD_改动报告_20260411.md --test-case eval/test_cases/劳动仲裁.json\n"
            "  python cuckoo_eval.py --report output/PRD_改动报告_20260411.md --workspace ./workspace\n"
            "  python cuckoo_eval.py --generate-test-case output/PRD_改动报告_20260411.md -o eval/test_cases/劳动仲裁.json\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument("--report", help="啄木鸟评审报告路径")
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

        # 生成报告
        report = generate_eval_report(test_case, scores, matches, evidence_results)

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
