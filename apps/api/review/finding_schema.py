"""Pecker v2 — Internal vs Rendered Finding 双 schema (PR-Agent 模式).

借鉴 PR-Agent 的 KeyIssuesComponentLink: internal 模型字段全 (给苍鹰/verifier/eval),
rendered 模型只 surface 3-4 个 PM 真正看的字段 (title 含位置 / 问题 / 改法 / 原文引用).

为什么不直接拆 dict: dict 没有静态约束, 报告渲染层和评审链路任何一方加字段都不知会
对方, 演变成"能 .get() 到就用"的 brittle 代码 (现已出现: report_builder 直接读 9 个
字段, 加新字段没人提醒). dataclass 版本给 IDE 类型提示 + 渲染只挑明确 surface 的字段,
避免 PM 报告意外被新加字段污染。

向后兼容: 现有 review_items.json 是裸 dict 列表, 转换函数 InternalFinding.from_dict
能容忍缺字段 (走默认值), 不强制全量迁移到 dataclass.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional


# 严重度三档 (沿用 worker.py / aggregation.py 现有约定)
SEVERITY_MUST = "must"
SEVERITY_SHOULD = "should"
SEVERITY_COULD = "could"

# evidence_type 三档 (review.confidence.EVIDENCE_CONFIDENCE_BASE 对应)
EVIDENCE_A = "A"  # wiki 引用
EVIDENCE_B = "B"  # 规则编号
EVIDENCE_C = "C"  # 经验/竞品/外部


@dataclass
class InternalFinding:
    """内部完整 finding — 苍鹰交叉校验、verifier、eval 全链路用.

    8+ 字段, 包含 issue 原文 / evidence 链 / verification 状态 / confidence
    全部上下文, 用于:
    - 苍鹰冲突合并 (facet_of / advisor_note)
    - verifier 验证 (verification_status / verification_reason)
    - cuckoo eval (confidence_score / evidence_chain)
    - rule_perf 反馈 (rule_id / dimension / severity)

    注: 字段顺序按使用频率 + 必填优先排. 默认值留 "" 而非 None, 让下游
    .get() 链路不需要每处判 None.
    """
    # 必填 (主链路最小契约)
    id: str = ""                          # 如 R-001, 报告内引用编号
    rule_id: str = ""                     # 如 V-04 / RC-005 / EV-01, 关联 review-checklist.yaml
    location: str = ""                    # PRD 章节/位置 — 渲染时拼到标题
    issue: str = ""                       # 问题陈述 (大白话, ≤80 字, prompting.py 约束)
    suggestion: str = ""                  # 改写建议 (≤60 字, "改成 X" 句式)
    severity: str = SEVERITY_SHOULD       # must / should / could

    # 依据三件套 (legacy parser + verify_evidence 用)
    evidence_type: str = ""               # A / B / C / "" (未标)
    evidence_content: str = ""            # 依据正文 — 含 [[页面]] 或 RC-XXX 引用
    evidence_chain: List[Any] = field(default_factory=list)  # 链式引用 (claim_provenance 用)

    # 信号/状态 (post_review + advisor 用)
    confidence_score: float = 0.5         # 0-1, 由 evidence_type + verification 决定
    dimension: str = ""                   # 结构层 / 命名层 / 完整层 / ... (worker 来源)
    status: str = "pending"               # pending / confirmed / rejected
    verification_status: str = ""         # verified / failed / unchecked

    # 可选/上下文 (不全填也不报错)
    facet_of: str = ""                    # 苍鹰冲突合并: 同源条原 R-XXX (could 严重度时拼 [补充·R-X])
    advisor_note: str = ""                # 苍鹰审核备注 (报告里不直接 surface)
    diff_status: str = ""                 # new / unfixed / fixed / carry_confirmed / carry_rejected
    is_cross_section: bool = False        # 跨章节标记
    raw_text: str = ""                    # parser 原始文本 (debug 用)

    # 衍生字段 (verify_evidence 失败时填)
    verification_reason: str = ""

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "InternalFinding":
        """从裸 dict 构建 InternalFinding — 容忍缺字段, 走默认值.

        关键场景: 现有 review_items.json 是裸 dict list, 不强制重写历史数据.
        多余字段会被忽略 (dataclass 不允许动态字段, 这里手动 pick 已声明字段).
        """
        if not isinstance(d, dict):
            return cls()

        known_fields = {f.name for f in cls.__dataclass_fields__.values()}
        kwargs: Dict[str, Any] = {}
        for k in known_fields:
            if k in d:
                kwargs[k] = d[k]

        # 兼容 cuckoo_parser 的 problem 字段 (老 schema 用 problem, 新链路用 issue)
        if "issue" not in kwargs and "problem" in d:
            kwargs["issue"] = d["problem"]

        return cls(**kwargs)

    def to_dict(self) -> Dict[str, Any]:
        """dataclass → dict (便于 json.dump / 测试断言)."""
        return asdict(self)


@dataclass
class RenderedFinding:
    """渲染层 finding — PM 报告 print 只看这 3-4 个字段.

    PR-Agent 的 KeyIssuesComponentLink 同款思路: 报告渲染严格只 surface
    "标题(含位置) + 问题 + 改法 + 可选原文引用" 4 字段, 多余的 evidence_type /
    rule_id / verification_status 全部下沉到 metadata sub 行, parser 仍能抓
    但视觉上不打扰 PM。

    为什么把 location 拼进 title: PM 第一眼看的是"在 PRD 哪里改", 不是
    "这是哪条规则违反". location 不在 title 而在第二行的话, PM 还得多扫一眼。
    """
    title_with_location: str = ""         # "R-001 [必须] · 二、企业主页 / 1.4 脱敏规则"
    problem: str = ""                     # issue 大白话
    fix: str = ""                         # suggestion 或 rewrite_pair 后的具体改法
    optional_quote: str = ""              # PRD 原文引用 (可选, 对位锚点)

    # metadata sub 行用 — parser 仍要抓, 不算 surface 字段, 渲染时单独拼
    meta_location: str = ""
    meta_severity: str = ""
    meta_evidence_type: str = ""
    meta_dimension: str = ""
    meta_rule_id: str = ""
    meta_diff_status: str = ""

    def to_markdown_block(self) -> List[str]:
        """渲染为 markdown 行 list (return list 让 caller 做 join, 与
        现有 report_builder lines.append() 风格一致)。

        输出与 2026-04-28 优化版 (17→10 行) 同结构:
            ### {title_with_location}
            **问题**: {problem}
            **怎么改**: {fix}        (或 ~~原文~~ → **建议**)
            > 原文: {optional_quote} (可选)
            <sub>**位置**: ... · **严重度**: ... · ...</sub>
            *迭代状态: ...*           (有 diff_status 时)
            ---
        """
        out: List[str] = []
        out.append(f"### {self.title_with_location}")
        out.append("")
        out.append(f"**问题**: {self.problem}")
        out.append("")
        out.append(f"**怎么改**: {self.fix}")
        out.append("")
        if self.optional_quote:
            out.append(f"> 原文：{self.optional_quote}")
            out.append("")
        # metadata sub 行 — parser regex 已支持 ' · ' 分隔符
        meta_parts = []
        if self.meta_location:
            meta_parts.append(f"**位置**: {self.meta_location}")
        if self.meta_severity:
            meta_parts.append(f"**严重度**: {self.meta_severity}")
        if self.meta_evidence_type:
            meta_parts.append(f"**依据类型**: {self.meta_evidence_type}")
        if self.meta_dimension or self.meta_rule_id:
            src = f"来源: {self.meta_dimension} {self.meta_rule_id}".strip()
            meta_parts.append(src)
        if meta_parts:
            out.append(f"<sub>{' · '.join(meta_parts)}</sub>")
        if self.meta_diff_status:
            status_labels = {
                "new": "本次新发现",
                "unfixed": "上次已报告但未修复",
                "fixed": "已修复",
                "carry_confirmed": "上次已确认不改",
                "carry_rejected": "上次已驳回",
            }
            label = status_labels.get(self.meta_diff_status, self.meta_diff_status)
            out.append(f"*迭代状态: {label}*")
        out.append("")
        out.append("---")
        out.append("")
        return out


def _severity_badge(severity: str, facet_of: str = "") -> str:
    """生成严重度标签 — 沿用 report_builder.py 原逻辑, 提到 schema 模块复用."""
    if severity == SEVERITY_MUST:
        return "**[必须]**"
    if severity == SEVERITY_COULD:
        return f"[补充·{facet_of}]" if facet_of else "[补充]"
    return "[建议]"


def _build_title(item_id: str, severity: str, location: str, facet_of: str = "") -> str:
    """组装 "R-001 [必须] · 位置" 标题字符串."""
    badge = _severity_badge(severity, facet_of)
    title_loc = f" · {location}" if location else ""
    return f"{item_id} {badge}{title_loc}"


def _extract_rewrite(suggestion: str) -> Dict[str, str]:
    """从 suggestion 抽 "X → Y" 或 "将X改为Y" 改写对.

    与 report_builder.generate_rewrite_pair 同逻辑, 提到 schema 复用.
    返回 {"original": ..., "suggested": ...} 或 {} (无改写对).
    """
    if not suggestion:
        return {}

    # 模式 1: "X" → "Y" 或 「X」 → 「Y」
    m = re.search(r'[「"](.*?)[」"]\s*[→\->]+\s*[「"](.*?)[」"]', suggestion)
    if m:
        return {"original": m.group(1), "suggested": m.group(2)}

    # 模式 2: 将 X 改为 Y
    m = re.search(r'将\s*[「"](.*?)[」"]\s*改[为成]\s*[「"](.*?)[」"]', suggestion)
    if m:
        return {"original": m.group(1), "suggested": m.group(2)}

    # 模式 3: suggestion 本身 (短文本) 直接当建议, 无对照原文
    if len(suggestion) < 100:
        return {"original": "", "suggested": suggestion}

    return {}


def to_rendered(
    item: Any,
    quote: str = "",
    rewrite: Optional[Dict[str, str]] = None,
) -> RenderedFinding:
    """InternalFinding (或裸 dict) → RenderedFinding.

    Args:
        item: InternalFinding 实例 或 dict (裸 review_items.json 元素).
        quote: 从 PRD 原文中抓的引用 (extract_precise_location.quote), 可选.
        rewrite: 改写对 {"original": ..., "suggested": ...}; 不传时从
                 item.suggestion 抽取.

    "怎么改" 字段优先级: rewrite_pair (有原文对照) > suggestion 全文.
    """
    if isinstance(item, dict):
        finding = InternalFinding.from_dict(item)
    elif isinstance(item, InternalFinding):
        finding = item
    else:
        # 容错: 既不是 dict 也不是 InternalFinding, 给个空 RenderedFinding
        return RenderedFinding()

    title = _build_title(finding.id or "?", finding.severity, finding.location, finding.facet_of)

    # 改法字段: 优先 rewrite_pair (PM 报告里能看到 ~~原文~~ → **建议**)
    rw = rewrite if rewrite is not None else _extract_rewrite(finding.suggestion)
    if rw.get("original") and rw.get("suggested"):
        # 有对照: 两段格式
        fix_text = f"\n- ~~{rw['original']}~~\n- **{rw['suggested']}**"
    else:
        fix_text = finding.suggestion

    return RenderedFinding(
        title_with_location=title,
        problem=finding.issue,
        fix=fix_text,
        optional_quote=quote,
        meta_location=finding.location,
        meta_severity=finding.severity,
        meta_evidence_type=finding.evidence_type,
        meta_dimension=finding.dimension,
        meta_rule_id=finding.rule_id,
        meta_diff_status=finding.diff_status,
    )


# ============================================================
# Profile 配置 (chill / strict 二档) — CodeRabbit 风格
# ============================================================

PROFILE_CHILL = "chill"
PROFILE_STRICT = "strict"

# chill 模式下 should 级别的 confidence 阈值 — 高于此值才显示
CHILL_SHOULD_CONFIDENCE_THRESHOLD = 0.8


def filter_by_profile(items: List[Any], profile: str = PROFILE_CHILL) -> List[Any]:
    """按 profile 过滤 items — 返回需要 print 的子集.

    chill: must (Critical+Major) 全展示 + should 中 confidence > 0.8 + could 全部隐藏
    strict: 全部 print (当前行为兼容)

    Args:
        items: 裸 dict list 或 InternalFinding list (混合也支持).
        profile: chill / strict.

    Returns:
        过滤后的 list (保持原元素类型, 不强转 dataclass).

    设计取舍:
    - chill 默认隐藏 could (nitpick), 沿袭 CodeRabbit "Light Mode" 思路: PM
      报告 inbox zero, must / 高置信 should 优先曝光, 低噪场景。
    - strict 不变, 保留全量审计能力 (rule_perf 反馈 + eval 仍能消费全部 items)。
    - 过滤层不修改 items 内容, 只 select; 业务下游 (rule_perf_store) 仍拿全量。
    """
    if profile == PROFILE_STRICT:
        return list(items)

    if profile != PROFILE_CHILL:
        # 未知 profile 走 chill 默认 (容错)
        profile = PROFILE_CHILL

    out = []
    for it in items:
        if isinstance(it, InternalFinding):
            severity = it.severity
            confidence = it.confidence_score
        elif isinstance(it, dict):
            severity = it.get("severity", SEVERITY_SHOULD)
            confidence = it.get("confidence_score", 0.5)
        else:
            continue

        if severity == SEVERITY_MUST:
            out.append(it)
        elif severity == SEVERITY_SHOULD:
            if confidence > CHILL_SHOULD_CONFIDENCE_THRESHOLD:
                out.append(it)
        # SEVERITY_COULD 在 chill 模式下默认隐藏

    return out
