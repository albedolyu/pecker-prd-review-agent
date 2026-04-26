"""claim-level provenance — 把 wiki 权威 tier 从「整页一刀切」推进到「逐 claim 细粒度」.

设计参考: obsidian-wiki (Ar9av/obsidian-wiki) 的 inline marker 语法.
- ^[inferred]: 推断/未直接证实的 claim
- ^[ambiguous]: 多源证据矛盾的 claim
- ^[verified]: 已校对的 claim
- 没标 = untagged, 对 generated/contextual wiki 视为可疑 (lint warn)

本模块**独立**于 review/evidence_verify.py, 后续由 evidence_verify 来 import 接入.
不在此处直接调用 _wiki_authority_tier, 避免与 Day3+ 未提交改动冲突.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

ClaimTag = Literal["inferred", "ambiguous", "verified", "untagged"]


@dataclass
class Claim:
    """切分后的单条 claim."""

    text: str          # 不含 marker 的纯文本 (已 strip)
    tag: ClaimTag
    start: int         # 在原文中的起始字符位置
    end: int           # 结束位置 (含 marker, 不含尾断句符)


@dataclass
class ClaimLintWarning:
    """lint 单条警告."""

    file: Path
    line: int          # 1-based 行号
    claim_text: str
    reason: str        # "untagged_factual_claim" / "marker_typo" / "duplicate_marker"


# ---------------------------------------------------------------------------
# 强断言关键词 / 正则 (放模块顶部方便扩展)
# ---------------------------------------------------------------------------

# 强断言中文关键词: 「是」/「等于」/「支持」/「必须」/「采用」/「使用」/「为」 + 后接名词
# 「为」单字过于宽泛, 限定为「为 + 中文/英文/数字」开头(排除"行为"等词中嵌字)
# 「使用/采用/支持」要后跟实词, 不能是行内副词
_STRONG_ASSERTION_CN = [
    re.compile(r"是\s*[A-Za-z0-9\u4e00-\u9fa5]"),       # 是 + 实词
    re.compile(r"等于\s*[A-Za-z0-9\u4e00-\u9fa5]"),
    re.compile(r"支持\s*[A-Za-z0-9\u4e00-\u9fa5]"),
    re.compile(r"必须\s*[A-Za-z0-9\u4e00-\u9fa5]"),
    re.compile(r"采用\s*[A-Za-z0-9\u4e00-\u9fa5]"),
    re.compile(r"使用\s*[A-Za-z0-9\u4e00-\u9fa5]"),
    # 「为」前面接名词后接实词 (避免命中"行为"/"作为"); 用「上限为/状态为/默认为」类
    re.compile(r"[\u4e00-\u9fa5]+为\s*[A-Za-z0-9\u4e00-\u9fa5]"),
]

# 数字断言: "5 张/天", "10%", "上限 100 条" 之类
# 至少含: 数字 + (单位/百分号/中文量词/路径标点)
_STRONG_ASSERTION_NUMERIC = re.compile(
    r"\d+\s*(张|条|次|个|秒|分钟|小时|天|月|年|%|％|/天|/分|/秒|MB|KB|GB|s|ms)"
)

# 英文断言: "X is Y", "X must Y", "X equals Y"
_STRONG_ASSERTION_EN = re.compile(
    r"\b(is|are|must|equals|equal\s+to)\s+[A-Za-z0-9]",
    re.IGNORECASE,
)

# Marker 正则: ^[ verified ] / ^[verified] / ^[ inferred] 等
# 严格匹配三种 tag, 中间允许空白; group(1) = tag 本身
_MARKER_PATTERN = re.compile(r"\^\[\s*(verified|inferred|ambiguous)\s*\]")

# 句末断句符:
# - 中文「。！？」一律切
# - 英文「!?」一律切
# - 英文「.」只在后面是空白/行末/中文 时才切 (避开 pages.json / 0.5 这类)
# 用 split + capturing group 不好控, 改用正则 finditer 收集断句点位置后手切.
_SENTENCE_TERMINATOR = re.compile(
    r"[。！？!?]"            # 中英强断句符 — 总是切
    r"|"
    r"\.(?=\s|$|[\u4e00-\u9fa5])"   # 英文 「.」 仅在后跟空白/行末/中文 时切
)


# ---------------------------------------------------------------------------
# parse_claim_markers
# ---------------------------------------------------------------------------


def parse_claim_markers(text: str) -> list[Claim]:
    """把一段文本切分为 claim list.

    切分逻辑:
    - 用「。！？.!?」做断句, 换行符独立成段(每行各自再断句)
    - 每个 claim 末尾如果跟着 ^[xxx] (允许中间空格), 提取 tag
    - 否则 tag = "untagged"
    - 空白片段被丢弃

    Args:
        text: 原始文本(可含 marker, 中英混排)

    Returns:
        Claim list, 顺序与原文一致
    """
    claims: list[Claim] = []
    if not text or not text.strip():
        return claims

    cursor = 0  # 字符级游标, 用于回填 start/end
    for line in text.split("\n"):
        # 每行内部再用断句符切; 跟踪行内位置
        line_start = cursor
        # 行内切句: 用 finditer 找断句点, 把各段(含尾断句符)切出来
        terminators = list(_SENTENCE_TERMINATOR.finditer(line))
        pieces: list[str] = []
        prev = 0
        for m in terminators:
            pieces.append(line[prev: m.end()])
            prev = m.end()
        if prev < len(line):
            pieces.append(line[prev:])

        line_offset = 0
        for piece in pieces:
            if not piece:
                line_offset += 0
                continue
            piece_abs_start = line_start + line_offset
            line_offset += len(piece)
            stripped = piece.strip()
            if not stripped:
                continue
            # 找尾部 marker: 允许 marker 后接断句符 (^[verified]。)
            tag: ClaimTag = "untagged"
            text_no_marker = stripped
            # 寻找最后一个 marker (一般只有一个, 但放心起见用 findall 取最后)
            markers = list(_MARKER_PATTERN.finditer(stripped))
            if markers:
                last = markers[-1]
                tag = last.group(1)  # type: ignore[assignment]
                # 把 marker 从 text 中剔除 (保留断句符)
                text_no_marker = (
                    stripped[: last.start()] + stripped[last.end():]
                ).strip()
            # 构造 Claim 的 start/end (相对原 text)
            # 用 piece 在原文中的真实位置 (含前导空白)
            real_start = text.find(stripped, piece_abs_start)
            if real_start < 0:
                real_start = piece_abs_start
            real_end = real_start + len(stripped)
            claims.append(
                Claim(
                    text=text_no_marker,
                    tag=tag,
                    start=real_start,
                    end=real_end,
                )
            )
        cursor = line_start + len(line) + 1  # +1 for '\n'

    return claims


# ---------------------------------------------------------------------------
# lint_wiki_claims
# ---------------------------------------------------------------------------


def _is_strong_assertion(sentence: str) -> bool:
    """启发式判断一句是否含强断言.

    - 中文关键词 (是/等于/支持/必须/采用/使用/为) + 实词
    - 数字断言 (5 张/天, 10%)
    - 英文 is/are/must/equals + 实词
    """
    if _STRONG_ASSERTION_NUMERIC.search(sentence):
        return True
    if _STRONG_ASSERTION_EN.search(sentence):
        return True
    for pat in _STRONG_ASSERTION_CN:
        if pat.search(sentence):
            return True
    return False


def _strip_frontmatter(content: str) -> tuple[str, int]:
    """剥掉首段 ``---...---`` frontmatter.

    Returns:
        (剩余正文, frontmatter 占了几行)
    """
    m = re.match(r"^\s*---\s*\n.*?\n---\s*\n", content, re.DOTALL)
    if not m:
        return content, 0
    fm_text = m.group(0)
    line_count = fm_text.count("\n")
    return content[m.end():], line_count


def lint_wiki_claims(
    wiki_path: Path,
    authority: ClaimTag | str = "contextual",
) -> list[ClaimLintWarning]:
    """对 generated/contextual 级别的 wiki 文件, 扫描 untagged 强断言句.

    - canonical / trusted 不扫 (它们由 PM 校对过)
    - 跳过 frontmatter 区域 (首个 ``---...---``)
    - 启发式: 见 _is_strong_assertion

    Args:
        wiki_path: wiki 文件路径
        authority: 该 wiki 的 authority tier; 仅 generated/contextual 才扫

    Returns:
        warning 列表, 按行号升序
    """
    if authority not in ("generated", "contextual"):
        return []

    wiki_path = Path(wiki_path)
    try:
        raw = wiki_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []

    body, fm_lines = _strip_frontmatter(raw)

    warnings: list[ClaimLintWarning] = []
    for idx, line in enumerate(body.split("\n"), start=1):
        # 真实行号 = frontmatter 占行数 + 当前行号
        real_line = fm_lines + idx
        # 跳过表格行(以 | 开头) / 代码块标记 / 标题
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith(("#", "|", "```", "<!--", "- [[", "- [")):
            continue
        # 切句, 检查每句
        claims = parse_claim_markers(line)
        for c in claims:
            if c.tag != "untagged":
                continue
            if _is_strong_assertion(c.text):
                warnings.append(
                    ClaimLintWarning(
                        file=wiki_path,
                        line=real_line,
                        claim_text=c.text,
                        reason="untagged_factual_claim",
                    )
                )

    warnings.sort(key=lambda w: w.line)
    return warnings


__all__ = [
    "Claim",
    "ClaimLintWarning",
    "ClaimTag",
    "parse_claim_markers",
    "lint_wiki_claims",
]
