"""
杜鹃 (Cuckoo) — 评审报告解析模块

负责将啄木鸟输出的 Markdown/YAML 格式报告解析为结构化改进项列表。

B4 (Phase 5): 解析时根据 evidence_type 附加 confidence_score 字段,
供伯劳门禁分档和 merge_reviews 合并共识项加权使用。

⚠ DEPRECATED (2026-04-29): parse_review_report 是老报告格式解析器,
新规则级 P/R 回归已不再依赖本模块. 历史 caller (cuckoo_eval / merge_reviews)
仍用, 不强删. 替代方案: scripts/rule_regression.py 直接消费 worker JSON 输出,
不需要再做正则解析. 详见 docs/MIGRATION_v1_to_v2.md.
"""

import os
import re
import warnings

from review.confidence import (
    EVIDENCE_CONFIDENCE_BASE,
    GOSHAWK_SUPPLEMENT_DECAY,
    compute_confidence,
)


# 仅在直接调用 parse_review_report 时 emit 一次, import 不打扰
# (importer 太多, 启动期 emit 一遍会刷屏)
_PARSE_DEPRECATION_EMITTED = False


def _emit_parse_deprecation():
    global _PARSE_DEPRECATION_EMITTED
    if _PARSE_DEPRECATION_EMITTED:
        return
    _PARSE_DEPRECATION_EMITTED = True
    warnings.warn(
        "cuckoo_parser.parse_review_report 已废弃 — 新流程用 scripts/rule_regression.py "
        "直接消费 worker JSON 输出, 不再做报告正则解析. 详见 docs/MIGRATION_v1_to_v2.md.",
        DeprecationWarning,
        stacklevel=3,
    )


def parse_review_report(report_path):
    """从啄木鸟的改动报告中提取改进项列表

    解析 R-XXX 编号、位置、问题描述、严重度、依据
    返回结构化列表
    """
    _emit_parse_deprecation()
    with open(report_path, "r", encoding="utf-8") as f:
        content = f.read()

    items = []

    # 策略1：解析 YAML 风格的改进项块（啄木鸟标准输出格式）
    # 匹配 "- id: R-001" 开头的块
    yaml_pattern = re.compile(
        r'-\s*id:\s*(R-\d+)\s*\n'
        r'(?:\s+位置:\s*["\']?(.+?)["\']?\s*\n)?'
        r'(?:\s+问题:\s*["\']?(.+?)["\']?\s*\n)?'
        r'(?:\s+建议:\s*["\']?(.+?)["\']?\s*\n)?'
        r'(?:\s+严重度:\s*(must|should)\s*\n)?'
        r'(?:\s+依据类型:\s*([ABC])\s*\n)?'
        r'(?:\s+依据内容:\s*["\']?(.+?)["\']?\s*\n)?',
        re.MULTILINE
    )

    for m in yaml_pattern.finditer(content):
        evi_type = (m.group(6) or "").strip()
        items.append({
            "id": m.group(1),
            "location": (m.group(2) or "").strip(),
            "problem": (m.group(3) or "").strip(),
            "suggestion": (m.group(4) or "").strip(),
            "severity": (m.group(5) or "").strip(),
            "evidence_type": evi_type,
            "evidence_content": (m.group(7) or "").strip(),
            "confidence_score": compute_confidence(evi_type),  # B4
            "raw_text": m.group(0),
        })

    # 策略2：如果 YAML 风格没解析到，尝试 Markdown 表格或列表格式
    if not items:
        items = _parse_markdown_items(content)

    # 策略3：兜底 — 用正则捞所有 R-XXX 编号行
    if not items:
        items = _parse_loose_items(content)

    return items


def _parse_markdown_items(content):
    """解析 Markdown 格式的改进项

    支持多种格式：
    - #### R-001 ✅ 已确认
    - ### R-001
    - **R-001**
    """
    items = []

    # 按 #### R-XXX 或 ### R-XXX 分割成块
    block_pattern = re.compile(
        r'(?:#{2,4})\s*(R-\d+)\s*.*?\n(.*?)(?=\n#{2,4}\s*R-\d+|\n## |\Z)',
        re.DOTALL
    )

    for m in block_pattern.finditer(content):
        item_id = m.group(1)
        block_text = m.group(2).strip()
        # 避免重复
        if any(it["id"] == item_id for it in items):
            continue
        items.append(_extract_fields_from_block(item_id, block_text))

    return items


def _parse_loose_items(content):
    """兜底解析：找所有 R-XXX 出现的行及上下文"""
    items = []
    lines = content.split("\n")

    for i, line in enumerate(lines):
        match = re.search(r'(R-\d+)', line)
        if match:
            item_id = match.group(1)
            # 已经解析过这个 ID 就跳过
            if any(it["id"] == item_id for it in items):
                continue
            # 取当前行及后续几行作为上下文
            context = "\n".join(lines[i:min(i + 8, len(lines))])
            items.append(_extract_fields_from_block(item_id, context))

    return items


def _extract_fields_from_block(item_id, block_text):
    """从一块文本中提取改进项的各个字段

    兼容两种格式：
    - **位置**：xxx（啄木鸟 Markdown 输出）
    - 位置：xxx（YAML 风格）
    """
    def _find(field_name, text):
        """在文本中搜索字段值，兼容 **字段** 和 字段 两种格式

        2026-04-28 PM 报告优化: 新增 ' · ' 分隔符边界识别, 支持单行多字段紧凑格式:
            <sub>**位置**: X · **严重度**: must · **依据类型**: A</sub>
        """
        # 边界: 行末 / ' · ' (PM 友好紧凑行) / '</sub>' (sub 标签收尾)
        boundary = r'(?:\n|$|\s+·\s+|</sub>)'
        # 先试 **字段**：格式
        m = re.search(rf'\*\*{field_name}\*\*[：:]\s*(.+?){boundary}', text)
        if m:
            return m.group(1).strip()
        # 再试 - **字段**：格式（列表项）
        m = re.search(rf'-\s*\*\*{field_name}\*\*[：:]\s*(.+?){boundary}', text)
        if m:
            return m.group(1).strip()
        # 最后试纯文本格式
        m = re.search(rf'{field_name}[：:]\s*(.+?){boundary}', text)
        if m:
            return m.group(1).strip()
        return ""

    location = _find("位置", block_text)
    problem = _find("问题", block_text)
    suggestion = _find("建议", block_text)
    evidence_content = _find("依据", block_text) or _find("依据内容", block_text)

    # 严重度
    sev_match = re.search(r'(?:\*\*)?严重度(?:\*\*)?[：:]\s*(must|should)', block_text)
    severity = sev_match.group(1) if sev_match else ""

    # 依据类型
    evi_type_match = re.search(r'(?:\*\*)?依据类型(?:\*\*)?[：:]\s*([ABC])', block_text)
    evidence_type = evi_type_match.group(1) if evi_type_match else ""

    # 如果没提取到依据类型，从依据内容推断
    if not evidence_type and evidence_content:
        if "[[" in evidence_content:
            evidence_type = "A"
        elif re.search(r'(?:RC-|BMAD|V-)\d+', evidence_content):
            evidence_type = "B"
        elif "竞品" in evidence_content or "行业" in evidence_content:
            evidence_type = "C"

    # 如果没提取到问题描述，用整块文本的第一行
    if not problem:
        first_line = block_text.split("\n")[0].strip()
        # 去掉 ID 前缀
        first_line = re.sub(r'^R-\d+\s*[：:．.]?\s*', '', first_line)
        problem = first_line[:200] if first_line else ""

    return {
        "id": item_id,
        "location": location,
        "problem": problem,
        "suggestion": suggestion,
        "severity": severity,
        "evidence_type": evidence_type,
        "evidence_content": evidence_content,
        "confidence_score": compute_confidence(evidence_type),  # B4
        "raw_text": block_text[:500],
    }
