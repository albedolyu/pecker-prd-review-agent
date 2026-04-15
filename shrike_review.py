"""
伯劳 (Shrike) — 啄木鸟评审产出质量门禁
纯静态分析，不调 API。在 git push 前拦截不合格的评审产出。

v1.2(B1): 六关检查(第 6 关可选)
1. 报告完整性：改动报告必需章节是否齐全
2. 编号一致性：改动报告/差异报告/交互记录的 R-xxx 编号交叉比对
3. Wiki 质量：新增页面 frontmatter/命名前缀/双向链接
4. 安全扫描：产出文件不含 API key/密码/内网 IP
5. 格式规范：改进项必填字段完整度
6. 依据可靠性(可选)：当 parallel_result 传入时,检查依据可靠率和撤回原因分布

用法：
    python shrike_review.py --workspace ./workspace
    python shrike_review.py --workspace ./workspace --wiki ./workspace/wiki
"""

import argparse
import os
import re
import glob as glob_module
import sys


# ============================================================
# ASCII Art
# ============================================================

SHRIKE_ART = r"""
       \   /
        \ /
        (o)>    伯劳质量门禁
         |      "报告不完整别想合进来"
        / \
"""


# ============================================================
# Gate 1: 报告完整性
# ============================================================

# 改动报告必须包含的章节关键词（子串匹配）
REQUIRED_SECTIONS = ["评审概览", "已确认", "待确定", "已驳回", "人工复核提醒"]


def check_report_completeness(output_dir):
    """Gate 1: 改动报告必需章节完整性检查"""
    if not os.path.isdir(output_dir):
        return {"passed": False, "details": ["output/ 目录不存在"]}

    # 找最新的改动报告
    pattern = os.path.join(output_dir, "PRD_改动报告_*.md")
    files = sorted(glob_module.glob(pattern))
    if not files:
        return {"passed": False, "details": ["找不到 PRD_改动报告_*.md 文件"]}

    latest = files[-1]
    with open(latest, "r", encoding="utf-8", errors="replace") as fh:
        content = fh.read()

    missing = [s for s in REQUIRED_SECTIONS if s not in content]

    return {
        "passed": len(missing) == 0,
        "details": [f"缺少章节「{s}」" for s in missing],
    }


# ============================================================
# Gate 2: 编号一致性
# ============================================================

def _extract_ids(filepath):
    """从文件中提取所有 R-xxx 编号"""
    with open(filepath, "r", encoding="utf-8", errors="replace") as fh:
        content = fh.read()
    return set(re.findall(r"R-\d+", content))


def check_id_consistency(output_dir):
    """Gate 2: 三份报告的 R-xxx 编号交叉比对"""
    if not os.path.isdir(output_dir):
        return {"passed": False, "details": ["output/ 目录不存在"]}

    # 找各文件（取最新）
    def latest(pattern):
        files = sorted(glob_module.glob(os.path.join(output_dir, pattern)))
        return files[-1] if files else None

    report_file = latest("PRD_改动报告_*.md")
    diff_file   = latest("PRD_差异报告_*.md")
    record_file = latest("PRD_交互记录_*.md")

    if not report_file:
        return {"passed": False, "details": ["找不到 PRD_改动报告_*.md，无法比对编号"]}

    ids_report = _extract_ids(report_file)
    details = []

    # 改动报告 vs 差异报告
    if diff_file:
        ids_diff = _extract_ids(diff_file)
        # 改动报告中有但差异报告没有的
        only_in_report = ids_report - ids_diff
        for rid in sorted(only_in_report):
            details.append(f"{rid} 在改动报告中有，差异报告中缺失")
        # 差异报告中有但改动报告没有的（异常）
        only_in_diff = ids_diff - ids_report
        for rid in sorted(only_in_diff):
            details.append(f"{rid} 在差异报告中有，改动报告中缺失")

    # 改动报告 vs 交互记录
    if record_file:
        ids_record = _extract_ids(record_file)
        only_in_report_2 = ids_report - ids_record
        for rid in sorted(only_in_report_2):
            details.append(f"{rid} 在改动报告中有，交互记录中缺失")
        only_in_record = ids_record - ids_report
        for rid in sorted(only_in_record):
            details.append(f"{rid} 在交互记录中有，改动报告中缺失")

    return {"passed": len(details) == 0, "details": details}


# ============================================================
# Gate 3: Wiki 质量
# ============================================================

# 跳过这些文件，不检查
WIKI_SKIP = {"index.md", "log.md", "_scratchpad.md"}

# 合法的命名前缀
WIKI_PREFIXES = ("概念-", "场景-", "竞品-", "约束-", "决策-", "实体-")


def check_wiki_quality(wiki_path):
    """Gate 3: Wiki 页面 frontmatter / 命名前缀 / 双向链接"""
    if not wiki_path or not os.path.isdir(wiki_path):
        # wiki 不存在时直接跳过，视为通过（可选目录）
        return {"passed": True, "details": []}

    pages = [
        f for f in os.listdir(wiki_path)
        if f.endswith(".md") and f not in WIKI_SKIP
    ]

    issues_per_page = []

    for fname in sorted(pages):
        fpath = os.path.join(wiki_path, fname)
        with open(fpath, "r", encoding="utf-8", errors="replace") as fh:
            content = fh.read()

        page_issues = []

        # 检查 frontmatter（以 --- 开头）
        if not content.startswith("---"):
            page_issues.append("缺少 frontmatter（文件需以 --- 开头）")

        # 检查命名前缀
        if not any(fname.startswith(p) for p in WIKI_PREFIXES):
            page_issues.append(f"命名前缀不合规（需以 {'／'.join(WIKI_PREFIXES)} 之一开头）")

        # 检查至少一个双向链接 [[...]]
        links = re.findall(r"\[\[.+?\]\]", content)
        if not links:
            page_issues.append("缺少双向链接 [[...]]")

        if page_issues:
            issues_per_page.append({"file": fname, "issues": page_issues})

    return {
        "passed": len(issues_per_page) == 0,
        "details": issues_per_page,
    }


# ============================================================
# Gate 4: 安全扫描
# ============================================================

# 敏感信息正则列表
SECURITY_PATTERNS = [
    (r"sk-[a-zA-Z0-9]{20,}",                                   "API Key (sk-)"),
    (r"ghp_[a-zA-Z0-9]{20,}",                                  "GitHub Token (ghp_)"),
    (r"password\s*[=:]\s*\S+",                                  "明文密码 (password=)"),
    (r"passwd\s*[=:]\s*\S+",                                    "明文密码 (passwd=)"),
    (
        r"\b(?:10|172\.(?:1[6-9]|2\d|3[01])|192\.168)\.\d{1,3}\.\d{1,3}\b",
        "内网 IP"
    ),
    (
        r"(?:mysql|postgresql|postgres|mongodb|redis)://[^/\s]*:[^@\s]+@",
        "含凭据的连接串"
    ),
]


def _scan_file(filepath):
    """扫描单个文件，返回命中列表 [(line_no, pattern_name, snippet), ...]"""
    hits = []
    with open(filepath, "r", encoding="utf-8", errors="replace") as fh:
        for lineno, line in enumerate(fh, 1):
            for pattern, name in SECURITY_PATTERNS:
                if re.search(pattern, line, re.IGNORECASE):
                    snippet = line.strip()[:80]
                    hits.append((lineno, name, snippet))
    return hits


def check_security(output_dir, wiki_path=None):
    """Gate 4: 扫描 output/ 和 wiki/ 中的敏感信息"""
    details = []

    # 收集要扫描的目录
    scan_dirs = []
    if output_dir and os.path.isdir(output_dir):
        scan_dirs.append(output_dir)
    if wiki_path and os.path.isdir(wiki_path):
        scan_dirs.append(wiki_path)

    for scan_dir in scan_dirs:
        for fname in os.listdir(scan_dir):
            fpath = os.path.join(scan_dir, fname)
            if not os.path.isfile(fpath):
                continue
            hits = _scan_file(fpath)
            for lineno, name, snippet in hits:
                details.append({
                    "file": os.path.relpath(fpath, start=os.path.dirname(scan_dir)),
                    "line": lineno,
                    "type": name,
                    "snippet": snippet,
                })

    return {"passed": len(details) == 0, "details": details}


# ============================================================
# Gate 5: 格式规范
# ============================================================

# 改进项的必填字段（在文本块中以 key: value 形式存在）
REQUIRED_FIELDS = ["位置", "问题", "建议", "严重度", "依据"]

# 通过率阈值
FORMAT_PASS_THRESHOLD = 0.9


def _parse_review_items(content):
    """
    从改动报告正文中解析 R-xxx 条目块。
    策略：用 #### R-xxx 标题行定位条目边界，提取到下一个同级标题前的内容。
    回退：如果没有 #### 格式，用 re.split 裸切（去重）。
    """
    # 优先用 #### R-xxx 标题行切分
    block_pattern = re.compile(
        r'#{2,4}\s*(R-\d+)\s*.*?\n(.*?)(?=\n#{2,4}\s*R-\d+|\n#{1,2}\s[^#]|\Z)',
        re.DOTALL
    )
    matches = list(block_pattern.finditer(content))
    if matches:
        items = []
        seen = set()
        for m in matches:
            rid = m.group(1)
            if rid not in seen:
                seen.add(rid)
                items.append((rid, m.group(2)))
        return items

    # 回退：裸 R-xxx 切分（去重，只保留第一次出现）
    parts = re.split(r"(R-\d+)", content)
    items = []
    seen_ids = set()
    i = 1
    while i < len(parts) - 1:
        rid = parts[i]
        body = parts[i + 1] if i + 1 < len(parts) else ""
        if rid not in seen_ids:
            seen_ids.add(rid)
            items.append((rid, body))
        i += 2
    return items


def check_format_compliance(output_dir):
    """Gate 5: 改进项必填字段完整度，通过率 >= 90%"""
    if not os.path.isdir(output_dir):
        return {"passed": False, "rate": 0.0, "details": ["output/ 目录不存在"]}

    pattern = os.path.join(output_dir, "PRD_改动报告_*.md")
    files = sorted(glob_module.glob(pattern))
    if not files:
        return {"passed": False, "rate": 0.0, "details": ["找不到 PRD_改动报告_*.md"]}

    latest = files[-1]
    with open(latest, "r", encoding="utf-8", errors="replace") as fh:
        content = fh.read()

    items = _parse_review_items(content)
    if not items:
        # 报告里没有任何条目，视为通过（空集情况）
        return {"passed": True, "rate": 1.0, "details": []}

    details = []
    pass_count = 0

    for rid, body in items:
        missing = []
        for field in REQUIRED_FIELDS:
            # 兼容纯文本 "位置：xxx" 和 Markdown "**位置**：xxx" 和列表 "- **位置**：xxx"
            if not re.search(rf"(?:\*\*)?{field}(?:\*\*)?\s*[：:]\s*\S", body):
                missing.append(field)
        if missing:
            details.append({"id": rid, "missing_fields": missing})
        else:
            pass_count += 1

    total = len(items)
    rate = pass_count / total
    passed = rate >= FORMAT_PASS_THRESHOLD

    return {"passed": passed, "rate": rate, "details": details}


# ============================================================
# 主入口函数
# ============================================================

#: 依据可靠率阈值(低于此值 → Gate 6 FAIL)
EVIDENCE_RELIABILITY_THRESHOLD = 0.80


def check_evidence_reliability(parallel_result):
    """Gate 6: 依据可靠性 — 基于 parallel_review 的 verification_summary

    v1.2(B1) 新增。只有当 parallel_result 传入时才检查,否则标记为 skipped。

    判定规则:
    - 可靠率 >= 0.80 → PASS
    - 可靠率 < 0.80 → FAIL
    - 额外关注: A/B 类依据缺失(wiki/rule 找不到)是"硬失败",要在 details 里高亮
    """
    if parallel_result is None:
        return {
            "passed": True,  # 默认放行(未传数据,不阻断)
            "skipped": True,
            "details": ["parallel_result 未传入,依据可靠性检查跳过"],
        }

    summary = parallel_result.get("verification_summary")
    if not summary:
        return {
            "passed": True,
            "skipped": True,
            "details": ["verification_summary 缺失(可能是旧版 parallel_result),跳过"],
        }

    reliability = summary.get("reliability", 1.0)
    total = summary.get("total", 0)
    retracted = summary.get("retracted", 0)
    caveat = summary.get("caveat", 0)
    by_code = summary.get("retracted_by_reason_code", {})

    details = [
        f"总 item: {total} | 通过: {summary.get('verified', 0)} | "
        f"撤回: {retracted} | 待确认(C 类): {caveat}",
        f"可靠率: {reliability:.0%} (阈值 {EVIDENCE_RELIABILITY_THRESHOLD:.0%})",
    ]

    # A/B 类硬失败的具体分布(苍鹰/Worker 编造依据的红灯)
    hard_fail_keys = ["A_missing_wiki_page", "B_missing_rule"]
    for code in hard_fail_keys:
        count = by_code.get(code, 0)
        if count > 0:
            label = {
                "A_missing_wiki_page": "A 类 wiki 页面未找到",
                "B_missing_rule": "B 类 review-rule 未找到",
            }.get(code, code)
            details.append(f"  ⚠ {label}: {count} 条")

    passed = reliability >= EVIDENCE_RELIABILITY_THRESHOLD
    return {"passed": passed, "rate": reliability, "details": details}


def shrike_review(workspace, wiki_path=None, parallel_result=None):
    """
    执行全部六关质量检查，返回结构化结果字典。

    v1.2(B1): 新增 parallel_result 参数用于依据可靠性检查(Gate 6)

    Args:
        workspace: 工作目录路径（含 output/ 子目录）
        wiki_path: wiki 目录路径，默认为 workspace/wiki
        parallel_result: 并行评审结果(含 verification_summary),可选
    """
    output_dir = os.path.join(workspace, "output")
    if wiki_path is None:
        wiki_path = os.path.join(workspace, "wiki")

    gates = {
        "report_completeness":  check_report_completeness(output_dir),
        "id_consistency":       check_id_consistency(output_dir),
        "wiki_quality":         check_wiki_quality(wiki_path),
        "security_scan":        check_security(output_dir, wiki_path),
        "format_compliance":    check_format_compliance(output_dir),
        "evidence_reliability": check_evidence_reliability(parallel_result),
    }

    # skipped 的关不计入总数,但 passed(skipped=True 的都 passed=True)仍加进去
    passed_count = sum(1 for g in gates.values() if g["passed"])
    # verdict: 所有非 skipped 的关都 pass 才 PASS
    non_skipped = [k for k, g in gates.items() if not g.get("skipped")]
    all_non_skipped_passed = all(gates[k]["passed"] for k in non_skipped)
    verdict = "PASS" if all_non_skipped_passed else "FAIL"

    return {
        "verdict": verdict,
        "passed": passed_count,
        "total": len(gates),
        "gates": gates,
    }


# ============================================================
# 报告格式化
# ============================================================

def format_shrike_report(result):
    """将 shrike_review() 结果格式化为 Markdown 字符串"""
    lines = []

    verdict = result["verdict"]
    passed  = result["passed"]
    total   = result["total"]

    if verdict == "PASS":
        lines.append(f"## PASS  伯劳质量门禁通过 ({passed}/{total})\n")
        lines.append('"这次产出像样，可以推。" —— 伯劳\n')
    else:
        lines.append(f"## FAIL  伯劳质量门禁：不合格 ({passed}/{total} 通过)\n")

    gate_labels = {
        "report_completeness": "Gate 1  报告完整性",
        "id_consistency":      "Gate 2  编号一致性",
        "wiki_quality":        "Gate 3  Wiki 质量",
        "security_scan":       "Gate 4  安全扫描",
        "format_compliance":   "Gate 5  格式规范",
        "evidence_reliability": "Gate 6  依据可靠性",
    }

    for gate_key, label in gate_labels.items():
        gate = result["gates"].get(gate_key)
        if gate is None:
            continue
        if gate.get("skipped"):
            lines.append(f"### {label}  [SKIPPED]")
        else:
            status = "PASS" if gate["passed"] else "FAIL"
            lines.append(f"### {label}  [{status}]")

        details = gate.get("details", [])

        # 格式规范额外输出通过率
        if gate_key == "format_compliance":
            rate = gate.get("rate", 0.0)
            lines.append(f"  通过率: {rate:.0%}（阈值 90%）")

        if not details:
            lines.append("  全部通过")
        else:
            # wiki_quality 的 details 是 [{file, issues}]，其余是字符串或 dict
            for item in details:
                if isinstance(item, dict):
                    if "file" in item and "issues" in item:
                        # wiki_quality
                        lines.append(f"  - {item['file']}")
                        for issue in item["issues"]:
                            lines.append(f"      · {issue}")
                    elif "id" in item and "missing_fields" in item:
                        # format_compliance
                        missing = ", ".join(item["missing_fields"])
                        lines.append(f"  - {item['id']} 缺少字段: {missing}")
                    elif "file" in item and "line" in item:
                        # security_scan
                        lines.append(
                            f"  - {item['file']}:{item['line']}  [{item['type']}]  {item['snippet']}"
                        )
                    else:
                        lines.append(f"  - {item}")
                else:
                    lines.append(f"  - {item}")

        lines.append("")

    if verdict == "FAIL":
        lines.append('"这些问题不解决，我不会让它过。" —— 伯劳')

    return "\n".join(lines)


# ============================================================
# CLI 入口
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="伯劳 (Shrike) — 啄木鸟评审产出质量门禁（纯静态分析）",
    )
    parser.add_argument("--workspace", required=True, help="工作目录路径（需含 output/ 子目录）")
    parser.add_argument("--wiki", default=None, help="wiki 路径，默认 workspace/wiki")
    args = parser.parse_args()

    workspace = os.path.abspath(args.workspace)
    if not os.path.isdir(workspace):
        print(f"ERROR: 工作目录不存在: {workspace}")
        sys.exit(1)

    wiki_path = os.path.abspath(args.wiki) if args.wiki else None

    print(SHRIKE_ART)

    result = shrike_review(workspace, wiki_path=wiki_path)
    report = format_shrike_report(result)
    print(report)

    sys.exit(0 if result["verdict"] == "PASS" else 1)


if __name__ == "__main__":
    main()
