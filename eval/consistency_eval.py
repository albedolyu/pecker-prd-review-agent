"""
一致性评测 -- 同一 PRD 跑 N 次评审，计算改进项 overlap rate
用法:
  python eval/consistency_eval.py workspace/prd/劳动仲裁需求文档-v4.11.md --runs 3
  python eval/consistency_eval.py workspace/prd/劳动仲裁需求文档-v4.11.md --runs 3 --mode quick
"""

import argparse
import json
import os
import sys
import time
from collections import Counter
from difflib import SequenceMatcher

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"), override=True)
os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)


def _review_single_standalone(client, prd_content, model):
    """快速模式单模型评审（不依赖 app.py，避免 Streamlit 副作用）"""
    import re as _re
    system = """你是啄木鸟 PRD 评审 Agent。评审以下 PRD，输出结构化改进项。

要求：
1. 每条改进项必须有依据，找不到依据的改动不得提出
2. 按四个维度检查：结构层、质量层、AI Coding 友好度、数据质量
3. 输出 JSON 数组，每条包含：id, location, issue, suggestion, severity(must/should), evidence_type(A/B/C), evidence_content, dimension"""

    response = client.create(
        model=model, max_tokens=4096, system=system,
        messages=[{"role": "user", "content": f"请评审：\n\n{prd_content}"}],
    )
    text = response.content[0].text if response.content else ""
    m = _re.search(r'\[[\s\S]*\]', text)
    try:
        items = json.loads(m.group()) if m else []
    except (json.JSONDecodeError, AttributeError):
        items = []
    return {"items": items, "usage": response.usage, "mode": "quick"}


def run_single_review(client, prd_content, wiki_pages, model_tiers, mode):
    """执行一次评审，返回改进项列表"""
    if mode == "quick":
        result = _review_single_standalone(client, prd_content, model_tiers["sonnet"])
    else:
        import asyncio
        from parallel_review import parallel_review
        if sys.platform == "win32":
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        result = asyncio.run(parallel_review(client, prd_content, wiki_pages, model_tiers))
        result = {"items": result["merged_items"], "usage": result.get("total_usage", {})}
    return result.get("items", [])


def normalize_item(item):
    """提取改进项的核心特征，用于跨轮次比较"""
    return {
        "rule_id": (item.get("rule_id") or "").strip(),
        "location": (item.get("location") or "").strip(),
        "issue": (item.get("issue") or "").strip(),
        "severity": item.get("severity", "should"),
        "dimension": item.get("dimension", ""),
    }


def items_similar(a, b, threshold=0.6):
    """判断两条改进项是否指向同一个问题"""
    # 优先用 rule_id 匹配：同一规则编号 = 同一条规则的判定
    if a["rule_id"] and b["rule_id"] and a["rule_id"] == b["rule_id"]:
        return True
    # 没有 rule_id 时降级为文本匹配
    loc_sim = SequenceMatcher(None, a["location"], b["location"]).ratio()
    if loc_sim < 0.3 and a["location"] and b["location"]:
        return False
    issue_sim = SequenceMatcher(None, a["issue"], b["issue"]).ratio()
    return issue_sim >= threshold


def calculate_overlap(runs_items):
    """
    计算多轮评审的 overlap rate
    返回:
      - pairwise_overlaps: 每对轮次之间的重合率
      - stable_items: 出现在所有轮次中的改进项
      - frequency: 每条改进项出现的频次
    """
    n = len(runs_items)
    # 每条改进项标准化
    normalized_runs = []
    for items in runs_items:
        normalized_runs.append([normalize_item(i) for i in items])

    # 两两比较 overlap
    pairwise = []
    for i in range(n):
        for j in range(i + 1, n):
            a_items = normalized_runs[i]
            b_items = normalized_runs[j]
            # 从 a 找在 b 中有匹配的
            a_matched = set()
            b_matched = set()
            for ai, a_item in enumerate(a_items):
                for bi, b_item in enumerate(b_items):
                    if bi not in b_matched and items_similar(a_item, b_item):
                        a_matched.add(ai)
                        b_matched.add(bi)
                        break
            # Jaccard-like：匹配数 / 并集大小
            matched = len(a_matched)
            union = len(a_items) + len(b_items) - matched
            overlap = matched / union if union > 0 else 1.0
            pairwise.append({
                "run_a": i + 1, "run_b": j + 1,
                "a_count": len(a_items), "b_count": len(b_items),
                "matched": matched, "overlap": overlap,
            })

    # 找"稳定项"：在所有轮次都出现的改进项
    if n < 2:
        return pairwise, [], []

    # 以第一轮为基准，看每条在多少轮出现
    base = normalized_runs[0]
    frequency = []
    for bi, b_item in enumerate(base):
        count = 1  # 自身算 1 次
        for run_idx in range(1, n):
            for item in normalized_runs[run_idx]:
                if items_similar(b_item, item):
                    count += 1
                    break
        frequency.append({
            "issue": b_item["issue"][:60],
            "location": b_item["location"][:30],
            "severity": b_item["severity"],
            "appeared_in": count,
            "rate": count / n,
        })

    # 也统计非第一轮独有的
    for run_idx in range(1, n):
        for item in normalized_runs[run_idx]:
            found_in_base = any(items_similar(item, b) for b in base)
            if not found_in_base:
                count = 1
                for other_idx in range(n):
                    if other_idx == run_idx:
                        continue
                    if any(items_similar(item, o) for o in normalized_runs[other_idx]):
                        count += 1
                frequency.append({
                    "issue": item["issue"][:60],
                    "location": item["location"][:30],
                    "severity": item["severity"],
                    "appeared_in": count,
                    "rate": count / n,
                })

    # 去重 frequency（同一条可能被多轮统计）
    seen = set()
    deduped = []
    for f in frequency:
        key = f["issue"]
        if key not in seen:
            seen.add(key)
            deduped.append(f)
    frequency = sorted(deduped, key=lambda x: -x["rate"])

    stable = [f for f in frequency if f["rate"] >= 1.0]
    return pairwise, stable, frequency


def generate_report(prd_name, runs_items, pairwise, stable, frequency, mode, output_path):
    """生成一致性评测报告"""
    n = len(runs_items)
    avg_overlap = sum(p["overlap"] for p in pairwise) / len(pairwise) if pairwise else 0
    avg_count = sum(len(items) for items in runs_items) / n

    lines = [
        "# 一致性评测报告", "",
        f"**PRD**: {prd_name}",
        f"**评审模式**: {mode}",
        f"**评审轮次**: {n}",
        f"**生成时间**: {time.strftime('%Y-%m-%d %H:%M')}",
        "",
        "---",
        "",
        "## 总览",
        "",
        f"| 指标 | 值 |",
        f"|------|-----|",
        f"| 平均改进项数 | {avg_count:.1f} |",
        f"| 平均 overlap rate | {avg_overlap:.1%} |",
        f"| 稳定项数（每轮都出现） | {len(stable)} |",
        "",
    ]

    # 一致性评级
    if avg_overlap >= 0.8:
        grade = "A（高一致性）"
    elif avg_overlap >= 0.6:
        grade = "B（中等一致性）"
    elif avg_overlap >= 0.4:
        grade = "C（较低一致性）"
    else:
        grade = "D（低一致性，需改进规则）"
    lines += [f"**一致性评级: {grade}**", ""]

    # 两两对比
    lines += ["## 两两对比", "", "| 轮次 A | 轮次 B | A 项数 | B 项数 | 匹配数 | Overlap |", "|--------|--------|--------|--------|--------|---------|"]
    for p in pairwise:
        lines.append(f"| {p['run_a']} | {p['run_b']} | {p['a_count']} | {p['b_count']} | {p['matched']} | {p['overlap']:.1%} |")
    lines.append("")

    # 稳定项
    lines += ["## 稳定项（每轮都出现）", ""]
    if stable:
        for s in stable:
            lines.append(f"- **[{s['severity']}]** {s['location']}: {s['issue']}")
    else:
        lines.append("*无稳定项*")
    lines.append("")

    # 频次分布
    lines += ["## 改进项频次分布", "", "| 出现率 | 严重度 | 位置 | 问题 |", "|--------|--------|------|------|"]
    for f in frequency[:30]:
        lines.append(f"| {f['rate']:.0%} | {f['severity']} | {f['location']} | {f['issue']} |")
    lines.append("")

    # 每轮原始数据
    lines += ["## 各轮次改进项数", ""]
    for i, items in enumerate(runs_items):
        must = sum(1 for it in items if it.get("severity") == "must")
        should = len(items) - must
        lines.append(f"- 第 {i+1} 轮: {len(items)} 条 (must={must}, should={should})")
    lines.append("")

    report = "\n".join(lines)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(report)
    return report, avg_overlap


def main():
    parser = argparse.ArgumentParser(description="一致性评测：同一 PRD 跑 N 次评审")
    parser.add_argument("prd_file", help="PRD 文件路径")
    parser.add_argument("--runs", type=int, default=3, help="评审轮次（默认 3）")
    parser.add_argument("--mode", choices=["quick", "standard"], default="standard", help="评审模式")
    parser.add_argument("--output", help="报告输出路径（默认 eval/results/consistency_*.md）")
    args = parser.parse_args()

    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    # 读取 PRD
    prd_path = os.path.join(base_dir, args.prd_file) if not os.path.isabs(args.prd_file) else args.prd_file
    with open(prd_path, "r", encoding="utf-8") as f:
        prd_content = f.read()
    prd_name = os.path.basename(prd_path).replace(".md", "")

    # 初始化客户端
    from api_adapter import create_client
    from agent_config import MODEL_TIERS
    client = create_client()

    # 扫描 wiki
    wiki_path = os.environ.get("WIKI_PATH", os.path.join(base_dir, "shared-wiki"))
    wiki_pages = {}
    if os.path.isdir(wiki_path):
        for fname in os.listdir(wiki_path):
            if fname.endswith(".md") and fname not in ("index.md", "log.md"):
                with open(os.path.join(wiki_path, fname), "r", encoding="utf-8", errors="replace") as f:
                    wiki_pages[fname.replace(".md", "")] = f.read()

    # 执行 N 轮评审
    all_items = []
    for i in range(args.runs):
        print(f"\n{'='*50}")
        print(f"第 {i+1}/{args.runs} 轮评审（{args.mode} 模式）")
        print(f"{'='*50}")
        t0 = time.time()
        items = run_single_review(client, prd_content, wiki_pages, MODEL_TIERS, args.mode)
        elapsed = time.time() - t0
        print(f"  完成: {len(items)} 条改进项, 耗时 {elapsed:.1f}s")
        all_items.append(items)

    # 计算一致性
    pairwise, stable, frequency = calculate_overlap(all_items)

    # 生成报告
    output = args.output or os.path.join(
        base_dir, "eval", "results",
        f"consistency_{prd_name}_{time.strftime('%Y%m%d_%H%M')}.md"
    )
    os.makedirs(os.path.dirname(output), exist_ok=True)
    report, avg_overlap = generate_report(prd_name, all_items, pairwise, stable, frequency, args.mode, output)

    print(f"\n{'='*50}")
    print(f"一致性评测完成")
    print(f"{'='*50}")
    print(f"  平均 overlap rate: {avg_overlap:.1%}")
    print(f"  稳定项: {len(stable)} 条")
    print(f"  报告: {output}")

    # 同时保存原始数据
    raw_path = output.replace(".md", "_raw.json")
    with open(raw_path, "w", encoding="utf-8") as f:
        json.dump({
            "prd_name": prd_name,
            "mode": args.mode,
            "runs": args.runs,
            "avg_overlap": avg_overlap,
            "pairwise": pairwise,
            "stable_count": len(stable),
            "items_per_run": [len(items) for items in all_items],
            "all_items": all_items,
        }, f, ensure_ascii=False, indent=2)
    print(f"  原始数据: {raw_path}")


if __name__ == "__main__":
    main()
