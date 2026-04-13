"""
伯劳 (Shrike) — PR 审核 Agent
审核啄木鸟评审产出的质量：安全红线、wiki 一致性、报告完整性

用法：
  python shrike_review.py --workspace ./workspace                    # 审核本地产出
  python shrike_review.py --workspace ./workspace --output report.md # 输出审核报告
"""

import argparse
import os
import re
import glob as glob_module
import datetime


# ============================================================
# 伯劳 ASCII Art
# ============================================================

SHRIKE_ART = r"""
       \   /
        \ /
        (o)>    伯劳开始审核...
         |      "报告不完整别想过关"
        / \
"""


# ============================================================
# 检查函数
# ============================================================

def check_security_redlines(workspace):
    """安全红线检查：raw/ 和 review-rules/ 是否被修改"""
    issues = []

    # 检查 git diff 看 raw/ 和 review-rules/ 是否有变更
    import subprocess
    git_dir = os.path.join(workspace, ".git")
    if os.path.isdir(git_dir):
        result = subprocess.run(
            ["git", "diff", "--name-only", "HEAD"],
            capture_output=True, text=True, cwd=workspace,
        )
        changed = result.stdout.strip().split("\n") if result.stdout.strip() else []
        for f in changed:
            if f.startswith("raw/"):
                issues.append(f"raw/ 目录被修改: {f}")
            if f.startswith("review-rules/"):
                issues.append(f"review-rules/ 目录被修改: {f}")

    # 检查敏感信息
    output_dir = os.path.join(workspace, "output")
    if os.path.isdir(output_dir):
        sensitive_patterns = [
            r"sk-[a-zA-Z0-9]{20,}",
            r"ghp_[a-zA-Z0-9]{20,}",
            r"password\s*[=:]\s*\S+",
        ]
        for f in os.listdir(output_dir):
            fp = os.path.join(output_dir, f)
            if not f.endswith(".md") or not os.path.isfile(fp):
                continue
            with open(fp, "r", encoding="utf-8", errors="replace") as fh:
                content = fh.read()
            for pattern in sensitive_patterns:
                if re.search(pattern, content):
                    issues.append(f"敏感信息泄漏: {f} 中匹配到 {pattern}")

    return issues


def check_wiki_consistency(wiki_path):
    """Wiki 一致性检查"""
    issues = []

    if not os.path.isdir(wiki_path):
        issues.append("wiki/ 目录不存在")
        return issues

    # 获取所有 md 文件
    pages = [f for f in os.listdir(wiki_path) if f.endswith(".md") and f not in ("_scratchpad.md",)]
    page_names = {f.replace(".md", "") for f in pages}

    # 命名规范
    valid_prefixes = ("概念-", "场景-", "竞品-", "约束-", "决策-", "实体-", "规则提案-", "index", "log")
    for f in pages:
        name = f.replace(".md", "")
        if not any(name.startswith(p) for p in valid_prefixes):
            issues.append(f"命名不规范: {f}（缺少标准前缀）")

    # Frontmatter 检查
    required_fields = {"source", "created", "tags"}
    for f in pages:
        if f in ("index.md", "log.md"):
            continue
        fp = os.path.join(wiki_path, f)
        with open(fp, "r", encoding="utf-8", errors="replace") as fh:
            content = fh.read()
        # 检查 frontmatter
        if content.startswith("---"):
            fm_end = content.find("---", 3)
            if fm_end > 0:
                fm = content[3:fm_end]
                for field in required_fields:
                    if f"{field}:" not in fm:
                        issues.append(f"缺少 frontmatter 字段 '{field}': {f}")
            else:
                issues.append(f"frontmatter 格式不完整: {f}")
        else:
            issues.append(f"缺少 frontmatter: {f}")

    # 断链检查
    for f in pages:
        fp = os.path.join(wiki_path, f)
        with open(fp, "r", encoding="utf-8", errors="replace") as fh:
            content = fh.read()
        links = re.findall(r"\[\[(.+?)\]\]", content)
        for link in links:
            if link not in page_names:
                issues.append(f"断链: {f} 引用了不存在的 [[{link}]]")

    # index.md 检查
    index_path = os.path.join(wiki_path, "index.md")
    if os.path.exists(index_path):
        with open(index_path, "r", encoding="utf-8") as fh:
            index_content = fh.read()
        for f in pages:
            if f in ("index.md", "log.md"):
                continue
            name = f.replace(".md", "")
            if name not in index_content:
                issues.append(f"index.md 未收录: {f}")
    else:
        issues.append("index.md 不存在")

    # log.md 检查
    log_path = os.path.join(wiki_path, "log.md")
    if not os.path.exists(log_path):
        issues.append("log.md 不存在")

    return issues


def check_report_completeness(output_dir):
    """评审报告完整性检查"""
    issues = []

    if not os.path.isdir(output_dir):
        issues.append("output/ 目录不存在")
        return issues

    files = os.listdir(output_dir)
    md_files = [f for f in files if f.endswith(".md")]

    # 三件齐全
    has_report = any("改动报告" in f for f in md_files)
    has_diff = any("差异报告" in f for f in md_files)
    has_record = any("交互记录" in f for f in md_files)

    if not has_report:
        issues.append("缺少改动报告")
    if not has_diff:
        issues.append("缺少差异报告")
    if not has_record:
        issues.append("缺少交互记录")

    # 检查改动报告结构
    report_files = [f for f in md_files if "改动报告" in f]
    for f in report_files:
        fp = os.path.join(output_dir, f)
        with open(fp, "r", encoding="utf-8", errors="replace") as fh:
            content = fh.read()

        # 必须有的章节
        required_sections = ["评审概览", "人工复核提醒"]
        for section in required_sections:
            if section not in content:
                issues.append(f"{f}: 缺少「{section}」章节")

        # 检查改进项是否有残留的"待确认"
        if "待确认" in content and "确认状态" in content:
            # 统计待确认数量
            pending = content.count("待确认")
            if pending > 2:  # 允许标题和说明中出现
                issues.append(f"{f}: 有 {pending} 处「待确认」残留")

    return issues


# ============================================================
# 汇总与报告
# ============================================================

def run_review(workspace):
    """执行完整审核"""
    wiki_path = os.path.join(workspace, "wiki")
    output_dir = os.path.join(workspace, "output")

    print(SHRIKE_ART)

    results = {
        "security": check_security_redlines(workspace),
        "wiki": check_wiki_consistency(wiki_path),
        "report": check_report_completeness(output_dir),
    }

    total_issues = sum(len(v) for v in results.values())
    passed = total_issues == 0

    return results, passed


def format_review(results, passed):
    """格式化审核报告"""
    lines = []

    if passed:
        lines.append("## PASS  伯劳审核通过\n")
        lines.append("所有检查项通过。")
        lines.append('"这次的产出还算像样。" —— 伯劳\n')
    else:
        lines.append("## FAIL  伯劳审核：需要修改\n")

    # 安全红线
    security = results["security"]
    lines.append(f"### 安全红线 {'PASS' if not security else 'FAIL'}")
    if security:
        for issue in security:
            lines.append(f"  - {issue}")
    else:
        lines.append("  全部通过")
    lines.append("")

    # Wiki 一致性
    wiki = results["wiki"]
    wiki_status = "PASS" if not wiki else f"FAIL ({len(wiki)} issues)"
    lines.append(f"### Wiki 一致性 {wiki_status}")
    if wiki:
        for issue in wiki[:10]:
            lines.append(f"  - {issue}")
        if len(wiki) > 10:
            lines.append(f"  ... 还有 {len(wiki) - 10} 个问题")
    else:
        lines.append("  全部通过")
    lines.append("")

    # 报告完整性
    report = results["report"]
    report_status = "PASS" if not report else f"FAIL ({len(report)} issues)"
    lines.append(f"### 报告完整性 {report_status}")
    if report:
        for issue in report:
            lines.append(f"  - {issue}")
    else:
        lines.append("  全部通过")
    lines.append("")

    # 总结
    total = sum(len(v) for v in results.values())
    if not passed:
        lines.append(f"共 {total} 个问题需要修复。")
        lines.append('"这些问题不解决，我不会让它通过。" —— 伯劳')

    return "\n".join(lines)


# ============================================================
# CLI 入口
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="伯劳 (Shrike) — 审核啄木鸟评审产出",
    )
    parser.add_argument("--workspace", required=True, help="工作目录路径")
    parser.add_argument("--output", help="审核报告输出路径（默认只打印）")
    args = parser.parse_args()

    workspace = os.path.abspath(args.workspace)
    if not os.path.isdir(workspace):
        print(f"ERROR: 工作目录不存在: {workspace}")
        return

    results, passed = run_review(workspace)
    report = format_review(results, passed)
    print(report)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(report)
        print(f"\n报告已写入: {args.output}")

    return 0 if passed else 1


if __name__ == "__main__":
    exit(main())
