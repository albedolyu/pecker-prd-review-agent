"""Cluster B — Worker prompt 构建 + wiki/feedback 清单注入.

从 parallel_review.py 拆出 (2026-04-16 继续 SPLIT_PLAN 阶段 4):
- 常量: _WORKER_SHARED_RULES / _WORKER_SYSTEM_TEMPLATE
- wiki 工具: _add_freshness_note / build_wiki_manifest / _maybe_compact_wiki
- system prompt: _build_worker_system / _build_feedback_section / _build_real_refs_section
- user messages: _build_worker_messages

本模块无 Anthropic API 调用, 纯 prompt 构建。依赖 review.dimensions 取维度配置。
parallel_review.py re-export 这些符号, 现有调用方无需改动 import 路径。
"""

import json
import os
import re
import time
from datetime import datetime

from io_utils import try_read_json
from logger import get_logger
from review.dimensions import (
    _cn_label,
    _get_rule_perf_history_path,
    get_review_dimensions,
    get_wiki_keywords,
)
from review.langfuse_prompt_provider import resolve_text_prompt, worker_prompt_name

log = get_logger("parallel")


# ============================================================
# rule_id 抽取 + 错误提示文本: 走 SchemaRegistry 单点 SoT (step 3.5)
# ============================================================


def _extract_rule_ids_via_registry(text, workspace=None):
    """从文本抽合法 rule_id 列表 — 走 SchemaRegistry 单点 SoT.

    替代散落硬编码 rule_id 抽取正则 (前 P0-B 是手列 RC/V/EV/FN 4 前缀的固定 regex).
    加新前缀 (如 DQ-/BMAD-) 时只改 yaml, prompting 自动同步.
    """
    if not text:
        return []
    # 复用 evidence_verify._extract_rule_ids — 已是 step 3.4 单点 entry
    from review.evidence_verify import _extract_rule_ids
    return _extract_rule_ids(text, workspace=workspace)


def _b_class_format_hint(workspace=None):
    """生成 B 类 rule_id 格式铁律文本 — 从 SchemaRegistry 动态拼.

    替代 P0-B 落地的"扩 EV-/FN-"硬列举. yaml 加 DQ-/BMAD- 时这里自动同步.

    Returns:
        给 worker 看的一行 markdown bullet, 含合法前缀 + sample.
    """
    from review.schema_registry import SchemaRegistry

    registry = SchemaRegistry.get(workspace=workspace)
    prefixes = registry.valid_prefixes()       # 如 ("EV", "FN", "RC", "V")
    samples = registry.sample_rule_ids(n=3)    # 如 ("EV-01", "FN-01", "RC-009")

    # 拼前缀格式提示 (`V-\d+` / `RC-\d+` / ...)
    prefix_fmt = " / ".join(f"`{p}-\\d+`" for p in prefixes)

    if samples:
        sample_text = "（示例: " + " / ".join(samples) + "）"
    else:
        sample_text = ""

    return (
        f"- **B 类**：`evidence_content` 必须包含 {prefix_fmt} 格式的真实规则号"
        f"{sample_text}（从下表选），禁止只写规则描述。"
    )


def _add_freshness_note(wiki_page_path, content):
    """给 wiki 页面加新鲜度标记（CC memoryAge.ts:33-42 模式）"""
    try:
        mtime = os.path.getmtime(wiki_page_path)
        days = (time.time() - mtime) / 86400
        if days > 7:
            return f"[此页面 {int(days)} 天未更新，内容可能过时，请交叉验证]\n\n{content}"
        elif days > 1:
            return f"[更新于 {int(days)} 天前]\n\n{content}"
    except OSError:
        pass
    return content


def build_wiki_manifest(wiki_pages, wiki_path=None):
    """构建 wiki 页面清单（CC extractMemories manifest 模式）"""
    lines = []
    for title, content in wiki_pages.items():
        mtime_str = ""
        if wiki_path:
            fpath = os.path.join(wiki_path, f"{title}.md")
            try:
                mtime = os.path.getmtime(fpath)
                mtime_str = f" ({datetime.fromtimestamp(mtime).strftime('%Y-%m-%d')})"
            except OSError:
                pass
        desc = content[:80].replace("\n", " ").strip()
        lines.append(f"- {title}{mtime_str}: {desc}")
    return "\n".join(lines)


# ============================================================
# Worker System Prompt 模板
# ============================================================

_WORKER_SHARED_RULES = """## 评审要求
1. 仔细阅读 PRD 内容和相关知识库页面
2. **严格只评审你 owner=自己 的规则** — 缺失 ② Worker 边界互斥:
   review-dimensions.yaml 给每条规则标了 owner,你只输出 owner=本维度的 fail。
   即使你看到其他维度的 owner 的规则违反,也禁止报告(那条规则会被对应 worker 处理)。
   越界报告会被苍鹰交叉校验降权 + 杜鹃 verdict 扣分。
3. 逐条对照检查清单,每条规则都要检查
4. 同一条规则如果在多个位置违反,每个位置单独提交一条(rule_id 相同但 location 不同)
   每条 finding 必须能定位到 PRD 中的具体位置,不能只写"整体/流程/风险"这类笼统位置。
5. 每条改进项必须有明确依据(A=内部知识, B=评审规则, C=外部参考)
6. 找不到依据的改动不得提出
   不要把无关业务场景的 wiki、样例或历史规则迁移成当前 PRD 的硬要求; 只有实体/字段/流程明确匹配时才引用。
7. **允许承认无问题** — 缺失 ④ Worker 拒答出口:
   如果本维度逐条看完没发现 fail,提交空 items 数组并填写 null_finding_reason 说明
   你扫了哪些规则、为什么都 pass。空 items 不是失败。**禁止为了凑数硬找问题**。
8. 评审完成后,使用 submit_review_items 工具提交

## 依据分类
- A(内部知识):引用 wiki 页面,**严格使用 [[页面名]] 双方括号格式**,页面名必须在
  refs 清单中精确匹配(见后面的真实依据清单)。禁止使用《》书名号或其他括号。
- B(评审规则):引用规则编号和原文(RC-XXX 或 V-XX,必须在 refs 清单中)
- C(外部参考):竞品/行业惯例,**必须**标记「⚠️ 待确定」或「外部参考」字样

## 严重度
- must:必须修改,不改会导致 PRD 无法正确指导开发
- should:建议修改,改了会提升 PRD 质量

## issue / suggestion 写作风格 (2026-04-28 PM 反馈: 学术话语太多)
- **issue 用大白话**: 一句话说清"问题在哪 + 为什么是问题",不超过 80 字。
  ❌ "导致开发与测试无法对齐实现, 引入潜在的语义对立风险"
  ✅ "规则写双星号但示例只有 1 颗星, 1 字名到底打几颗?"
- **suggestion 给具体改法**: "改成 X" / "补充 X" / "删除 X", 不超过 60 字。
  ❌ "建议明确该字段的语义边界并补充相应说明"
  ✅ "在 4.3 节加一行: 收藏数量上限 10 条 (VIP 100 条)"
- **不绕弯**: 不要"潜在风险/可能影响/建议关注"这类含糊词, 直接说后果或改法。
- **不重复 PRD 原文**: issue 里别大段抄 PRD, 给位置标识符即可。

## 出口校准 (PR-Agent calibration block)

**优先不报 > 误报**:
- 如果你不能给出"具体场景"说明问题如何 manifest, **不要报**这条 finding。
- "潜在风险/可能影响/建议关注"这类含糊词 = 不要报。
- 跨章节联动推测如果不能从 diff context 直接定位到具体代码路径, **不要报**。

**fire_when / dont_fire_when 是硬约束**:
- 每条规则的 fire_when / dont_fire_when 是 ground truth。
- 看到符合 dont_fire_when 的情形即使其他 worker 都在报, 你也**不能报**。
- 不确定是否触发 fire_when 时按不触发处理,写入 null_finding_reason,不要硬凑 finding。
- 不确定时 80% 倾向不报。

**置信度门**:
- 高置信 (>80%) → 报 must
- 中置信 (50-80%) → 报 should
- 低置信 (<50%) → 不报, 写到 null_finding_reason"""

# 默认 tone_instructions — 没设 PECKER_TONE_INSTRUCTIONS env 时用 (≤250 字符)
_DEFAULT_TONE_INSTRUCTIONS = (
    "用'建议改为...'而不是'此处违反 X 原则', 引用 PRD 行号而不是抽象概念。"
    "issue 一句话点透问题, suggestion 给具体改法, 避免'潜在风险/可能影响'类含糊词。"
)


def _get_tone_instructions() -> str:
    """读取 tone_instructions: PECKER_TONE_INSTRUCTIONS env > 内置默认值. 截到 250 字符."""
    tone = os.environ.get("PECKER_TONE_INSTRUCTIONS", "").strip()
    if not tone:
        tone = _DEFAULT_TONE_INSTRUCTIONS
    if len(tone) > 250:
        tone = tone[:250]
    return tone


def _build_tone_instructions_block() -> str:
    """构造注入 worker system prompt 的 tone_instructions section.

    单独成段, 不动 _WORKER_SHARED_RULES 已有的"prefer not reporting"校准块.
    """
    tone = _get_tone_instructions()
    if not tone:
        return ""
    return f"\n## 团队语气约定 (tone_instructions)\n{tone}\n"


_WORKER_SYSTEM_TEMPLATE = """你是「{codename}」，啄木鸟评审团的 {dimension_name} 评审员。

## 你的逐条打分清单
{dimension_rules}

## 必须打分的规则列表
{checklist_list}

{shared_rules}
{tone_instructions_block}"""


# ============================================================
# Rule examples 渲染 (L3 升级: review-checklist.yaml 新 schema)
# ============================================================
#
# 新 schema 给每条规则可选地加 positive_example / negative_example / fire_when /
# dont_fire_when 字段, 用真实 PRD 文本告诉 worker "什么样子要报 / 什么样子不报",
# 减少幻觉触发. 老 schema 仍然兼容 — 只渲染 description + 默认校准提示.
#
# Token 预算:
# - 新格式 ~200 token/条, 5 条 ≈ 1000 token
# - 老格式 ~30 token/条, 5 条 ≈ 150 token
# - prompt 增量 5-7x, 但 worker 推理质量 worth it
# - 规则 > 10 条时只 must 级展开 examples, should 走 compact 降级

# 校准默认文案 (老 schema 无 fire_when 时用) — PR-Agent 风格的"prefer not reporting"
_DEFAULT_FIRE_WHEN = "PRD 显式违反此规则的描述, 且违反点能定位到具体段落/章节"
_DEFAULT_DONT_FIRE_WHEN = "找不到具体段落支撑, 或问题靠跨章节模糊推测"

# 单条规则 example snippet 的最大字符数 (中文 1 字 ≈ 1 token)
_EXAMPLE_SNIPPET_MAX_CHARS = 80

# Token 预算阈值 — 超过即触发 compact 降级 (should 走老格式)
_PROMPT_TOKEN_BUDGET = 10_000

def _wiki_budget_for_dim(
    dim_key: str | None,
    base_chars: int,
    prd_content: str | None = None,
    wiki_pages: dict | None = None,
    recovery_mode: bool = False,
) -> int:
    from review.adaptive import wiki_budget_for_dim

    return wiki_budget_for_dim(
        dim_key,
        base_chars,
        prd_content=prd_content,
        wiki_pages=wiki_pages,
        recovery_mode=recovery_mode,
    )


def _truncate_snippet(text: str, max_chars: int = _EXAMPLE_SNIPPET_MAX_CHARS) -> str:
    """把示例 snippet 截到 max_chars 字, 保留首部, 末尾加 ... 标识.
    多行 snippet 会先合并空行, 再按字符截断."""
    if not text:
        return ""
    # 合并多余空行 + 行内首尾空格
    cleaned = "\n".join(line.strip() for line in str(text).splitlines() if line.strip())
    if len(cleaned) <= max_chars:
        return cleaned
    return cleaned[:max_chars].rstrip() + "..."


def _render_rule_with_examples(rule: dict, compact: bool = False) -> str:
    """把 review-checklist.yaml 一条规则渲染成 worker prompt 里的 block.

    Args:
        rule: yaml load 后的 rule dict, 至少含 id (或 rule_id) + name + severity + description.
              可选: positive_example / negative_example / fire_when / dont_fire_when.
        compact: 规则数 > 10 时降级模式, 只渲染 description + fire_when, 不展开 examples.

    Returns:
        中文 markdown block 字符串. 向后兼容: 老 schema 无 examples 字段时只渲染老格式
        + 默认 PR-Agent 风格"prefer not reporting"校准提示.

    渲染策略 (新 schema):
        ### {rule_id} {name} [{severity}]
        {description}

        🔥 何时报: {fire_when}
        🚫 何时不报: {dont_fire_when}

        ❌ 正例 (违反此规则的样子):
        > {positive_example.snippet ≤80 字} ...
        > {why_fails}

        ✅ 反例 (满足此规则的样子):
        > {negative_example.snippet ≤80 字} ...
        > {why_passes}

    渲染策略 (老 schema, 兼容):
        ### {rule_id} {name} [{severity}]
        {description}

        🔥 何时报: PRD 显式违反此规则的描述, 且违反点能定位到具体段落/章节
        🚫 何时不报: 找不到具体段落支撑, 或问题靠跨章节模糊推测
    """
    rule_id = (rule.get("id") or rule.get("rule_id") or "?").strip()
    name = (rule.get("name") or "").strip()
    severity = (rule.get("severity") or "should").strip()
    description = (rule.get("description") or name or "").strip()

    # 标题行 + 描述
    lines = [f"### {rule_id} {name} [{severity}]", description]

    # 校准 (fire_when / dont_fire_when) — 老 schema 没有就走默认
    fire_when = (rule.get("fire_when") or "").strip() or _DEFAULT_FIRE_WHEN
    dont_fire_when = (rule.get("dont_fire_when") or "").strip() or _DEFAULT_DONT_FIRE_WHEN
    lines.append("")
    lines.append(f"🔥 何时报: {fire_when}")
    lines.append(f"🚫 何时不报: {dont_fire_when}")

    # compact 模式不展开 examples (token 预算保护)
    if compact:
        return "\n".join(lines)

    # examples 渲染 — 没有就跳过, 不破坏老 schema 兼容
    positive = rule.get("positive_example")
    negative = rule.get("negative_example")

    if isinstance(positive, dict) and positive.get("snippet"):
        snippet = _truncate_snippet(positive.get("snippet", ""))
        why_fails = (positive.get("why_fails") or "").strip()
        lines.append("")
        lines.append("❌ 正例 (违反此规则的样子):")
        lines.append(f"> {snippet}")
        if why_fails:
            lines.append(f"> {why_fails}")

    if isinstance(negative, dict) and negative.get("snippet"):
        snippet = _truncate_snippet(negative.get("snippet", ""))
        why_passes = (negative.get("why_passes") or "").strip()
        lines.append("")
        lines.append("✅ 反例 (满足此规则的样子):")
        lines.append(f"> {snippet}")
        if why_passes:
            lines.append(f"> {why_passes}")

    return "\n".join(lines)


def _load_rules_for_dimension(workspace, dim_key, dimensions=None):
    """从 workspace/review-rules/review-checklist.yaml 拿出该维度的规则 dict list.

    通过 SchemaRegistry 推断每条 rule 的 dimension, 过滤后返回原始 yaml dict
    (保留 examples 等字段, 不丢信息). yaml 缺失/无 examples 字段 → 返回空 list,
    caller 自然走老路径 (dim['rules'] 已是手写 prompt 文本).

    Returns:
        list[dict] — yaml 原始 dict 顺序保持, 每条至少含 id + name + severity + description.
    """
    if not workspace or not os.path.isdir(workspace):
        return []
    # 2026-04-28: 走 SSOT loader, 自动解析 extends 链 + additional_rules.
    # 老 schema (workspace 直接列 rules) 100% 兼容, 不需改动 yaml.
    try:
        from review.rule_loader import load_review_checklist
        raw_rules = load_review_checklist(workspace)
    except Exception as exc:
        log.warning(f"[prompting] SSOT loader 失败 (跳过 examples): {exc}")
        return []
    if not isinstance(raw_rules, list):
        return []

    # 用 SchemaRegistry 推断 dimension; 失败时按 rule_id prefix 回退
    try:
        from review.schema_registry import SchemaRegistry, _infer_dimension_from_prefix
        registry = SchemaRegistry.get(workspace=workspace)
    except Exception:
        registry = None
        from review.schema_registry import _infer_dimension_from_prefix

    dim_rules = []
    for item in raw_rules:
        if not isinstance(item, dict):
            continue
        rid = (item.get("id") or item.get("rule_id") or "").strip()
        if not rid:
            continue
        # 优先从 registry 拿真 dimension; 拿不到走 prefix 推断
        inferred_dim = None
        if registry is not None:
            try:
                inferred_dim = registry.get_rule(rid).dimension
            except KeyError:
                inferred_dim = None
        if inferred_dim is None:
            inferred_dim = _infer_dimension_from_prefix(rid)
        if inferred_dim == dim_key:
            dim_rules.append(item)
    return dim_rules


def _has_any_examples(rules: list) -> bool:
    """判断 rule list 中是否至少有一条带 examples 字段 — 决定是否注入 examples block."""
    for r in rules:
        if not isinstance(r, dict):
            continue
        if r.get("positive_example") or r.get("negative_example"):
            return True
        if r.get("fire_when") or r.get("dont_fire_when"):
            return True
    return False


def _build_examples_block(workspace, dim_key, base_token_estimate: int = 0):
    """渲染当前维度的规则 examples block (新 schema 升级注入点).

    向后兼容: 当前维度规则全部无 examples → 返回空字符串, prompt 不变.

    Token 预算保护:
    - 估算 base_prompt 已占 token + examples block token
    - 总和 > _PROMPT_TOKEN_BUDGET 时:
        * 规则 > 10 条 → 只 must 级展开 examples, should 走 compact
        * 否则全部走 compact (只 description + fire_when)
    - 大致字符 → token: 中文 1 字 ≈ 1 token, ascii 4 字符 ≈ 1 token. 保守估算用 char_count.
    """
    rules = _load_rules_for_dimension(workspace, dim_key)
    if not rules or not _has_any_examples(rules):
        return ""

    # 估算总 token (中文为主, 1 char ≈ 1 token 保守值)
    rule_count = len(rules)
    must_count = sum(1 for r in rules if (r.get("severity") or "").lower() == "must")

    # 第一轮: 全展开估算
    rendered = [_render_rule_with_examples(r, compact=False) for r in rules]
    full_chars = sum(len(s) for s in rendered)
    estimated_tokens = base_token_estimate + full_chars

    if estimated_tokens > _PROMPT_TOKEN_BUDGET:
        # 第二轮: 规则 > 10 条 → must 全展开 + should 走 compact
        if rule_count > 10:
            rendered = [
                _render_rule_with_examples(
                    r,
                    compact=(r.get("severity") or "").lower() != "must",
                )
                for r in rules
            ]
            log.info(
                f"[prompting] dim={dim_key} examples 触发预算降级: must 全展开 + should compact "
                f"(rule_count={rule_count}, must={must_count}, est={estimated_tokens})"
            )
        else:
            # 规则较少但 base_prompt 已经很大 → 全部走 compact
            rendered = [_render_rule_with_examples(r, compact=True) for r in rules]
            log.info(
                f"[prompting] dim={dim_key} examples 触发全 compact 降级 "
                f"(rule_count={rule_count}, est={estimated_tokens})"
            )

    header = (
        f"## 规则 examples 与触发边界 (L3 校准)\n\n"
        f"以下展开是该维度规则的真实 PRD 文本案例. 看 fire_when / dont_fire_when 决定是否报, "
        f"看正例/反例理解规则边界. 不要根据感觉报, 必须找到 PRD 里跟正例同类的具体段落才能报.\n"
    )
    return header + "\n\n".join(rendered) + "\n"


def _build_worker_system(dim_key, rule_perf_history=None, dimensions=None, workspace=None):
    return _build_worker_system_with_metadata(
        dim_key,
        rule_perf_history=rule_perf_history,
        dimensions=dimensions,
        workspace=workspace,
    )["text"]


def _build_worker_system_with_metadata(dim_key, rule_perf_history=None, dimensions=None, workspace=None):
    """为某个评审维度构建 system prompt，并动态注入：
    1. 信鸽反馈的高发问题规则（rule_perf_history）
    2. workspace 中的真实 rule_id / wiki 页面清单（防止 evidence 造假，借鉴百灵 load_real_imports）
    3. L3 升级: review-checklist.yaml 新 schema 的 positive/negative_example + fire_when/dont_fire_when
    """
    dims = dimensions or get_review_dimensions()
    dim = dims[dim_key]

    # 构建 checklist 列表文本，明确告诉模型必须打分哪些规则
    checklist_lines = []
    for rule in dim["checklist"]:
        checklist_lines.append(f"- {rule['rule_id']}（{rule['name']}）")
    checklist_text = "\n".join(checklist_lines)

    prompt_variables = {
        "codename": dim["codename"],
        "dimension_name": dim["name"],
        "dimension_rules": dim["rules"],
        "checklist_list": checklist_text,
        "shared_rules": _WORKER_SHARED_RULES,
        "tone_instructions_block": _build_tone_instructions_block(),
    }
    local_base_prompt = _WORKER_SYSTEM_TEMPLATE.format(
        codename=prompt_variables["codename"],
        dimension_name=prompt_variables["dimension_name"],
        dimension_rules=prompt_variables["dimension_rules"],
        checklist_list=prompt_variables["checklist_list"],
        shared_rules=prompt_variables["shared_rules"],
        tone_instructions_block=prompt_variables["tone_instructions_block"],
    )
    resolved_prompt = resolve_text_prompt(
        worker_prompt_name(dim_key),
        fallback_text=local_base_prompt,
        variables=prompt_variables,
    )
    base_prompt = resolved_prompt.text
    prompt_metadata = dict(resolved_prompt.metadata)

    # --- L3 升级: 注入 examples block (workspace 有 review-checklist.yaml 新 schema 时生效) ---
    # 估算 base_prompt 已用 token, 传给 _build_examples_block 做预算保护
    base_token_estimate = len(base_prompt)
    examples_section = _build_examples_block(workspace, dim_key, base_token_estimate)
    if examples_section:
        base_prompt += "\n" + examples_section

    # --- 优先级注入: v2 PM 显式反馈 → v1 commit 隐式信号 → 真实依据清单 ---
    # 设计决策 (2026-04-29 finalize, 详见 docs/v1_vs_v2_feedback_strategy.md):
    #   - v2 (learnings) 优先级最高: PM 直接反馈, 信号最准, 放在最前面让 worker 先看到
    #   - v1 (commit feedback) 降权为辅助信号: 历史提交反推, 可能滞后/噪声大,
    #     放后面 + 显式注明 "辅助信号"
    #   - 真实依据清单 (refs_section) 穿插中间, 防 evidence 造假
    #
    # 当 v2 与 v1 信号冲突 (e.g. v1 说"近期漏报多", v2 说"PM 反馈这条都是误报"),
    # worker 应优先按 v2 instruction 执行 — prompting 文案里已显式标注优先级.

    # --- 信鸽 v2 (优先): 注入 PM 反馈编译出的 learnings ---
    learnings_section = _build_learnings_section(workspace, dim_key)
    if learnings_section:
        base_prompt += "\n" + learnings_section

    # --- 真实依据清单（防止 evidence 造假，对应路线图 B1 前置） ---
    refs_section = _build_real_refs_section(workspace)
    if refs_section:
        base_prompt += "\n" + refs_section

    # --- 信鸽 v1 (辅助): 代码 commit 隐式信号, 降权为参考 ---
    feedback_section = _build_feedback_section(dim_key, rule_perf_history, dims)
    if feedback_section:
        base_prompt += "\n" + feedback_section

    return {
        "text": base_prompt,
        "metadata": prompt_metadata,
    }


def _build_learnings_section(workspace, dim_key, prd_content=None, max_count=5):
    """信鸽 v2: 注入 PM 反馈编译出的 learnings 到 worker prompt.

    与 _build_feedback_section 区别:
      - _build_feedback_section: 代码 commit 隐式信号 (rejection_rate / missed)
      - _build_learnings_section: PM 显式自然语言反馈编译出的 learning records

    Token 预算:
      - 单条 learning ~ 100-200 token (trigger_pattern + instruction)
      - 每 dim 最多 5 条 → 共 < 1000 token (符合任务 SLA)

    匹配策略 (无 prd_content 时):
      - 取该 dim 相关 (含本 dim 或无显式 dim 标注) 的 learning
      - 按 scope 优先级排序: org_global > team_local > pr_local
      - 取前 max_count 条

    匹配策略 (有 prd_content 时):
      - 调 find_relevant_learnings 做 keyword 启发式匹配
    """
    if not workspace or not os.path.isdir(workspace):
        return ""
    learnings_dir = os.path.join(workspace, "learnings")
    if not os.path.isdir(learnings_dir):
        return ""

    try:
        from review.learnings_store import LearningsStore, find_relevant_learnings
    except ImportError as e:
        log.warning(f"learnings_store import 失败: {e}")
        return ""

    try:
        store = LearningsStore(workspace)
    except (OSError, ValueError) as e:
        log.warning(f"LearningsStore 初始化失败: {e}")
        return ""

    if prd_content:
        learnings = find_relevant_learnings(
            store, prd_content, dim_key, max_count=max_count,
        )
    else:
        # system prompt 阶段没 PRD 内容, 取该 dim 相关的全部 learning, 按 scope 优先 + usage 排序
        all_learnings = store.list_all()
        relevant = [l for l in all_learnings if not l.dim_keys or dim_key in l.dim_keys]
        prio_map = {"org_global": 0, "team_local": 1, "pr_local": 2}
        relevant.sort(key=lambda l: (
            prio_map.get(l.scope, 9),
            -l.usage_count,
            l.created_at,
        ))
        learnings = relevant[:max_count]

    if not learnings:
        return ""

    # 统计当前注入: 异步刷 usage_count (不阻塞 prompt 生成)
    for l in learnings:
        try:
            store.update_usage(l.id)
        except Exception as e:
            log.debug(f"learning {l.id} usage 刷新失败: {e}")

    lines = [
        "## PM 反馈编译记录 (Learnings) — **高优先级 / 信鸽 v2**",
        "以下是 PM 历史反馈编译出的 learning, **是当前最准的信号**. 出现 trigger_pattern 描述的情况时, 严格按 instruction 执行.",
        "**优先级铁律**:",
        "  1. learning 与默认规则冲突 → learning 优先",
        "  2. learning 与下文「近期反馈提示」(信鸽 v1, commit 隐式信号) 冲突 → learning 优先",
        "  3. scope 内部: org_global > team_local > pr_local",
        "",
    ]
    for l in learnings:
        scope_label = {
            "org_global": "[组织]",
            "team_local": "[团队]",
            "pr_local": "[本次]",
        }.get(l.scope, "[本次]")
        lines.append(f"- {scope_label} **当 {l.trigger_pattern}**: {l.instruction}")
        if l.related_rule_ids:
            lines.append(f"  (关联规则: {', '.join(l.related_rule_ids)})")
    lines.append("")
    return "\n".join(lines)


def _build_feedback_section(dim_key, rule_perf_history=None, dimensions=None):
    """从已加载的 history 中筛选当前维度的高发问题规则"""
    if rule_perf_history is None:
        rule_perf_history = try_read_json(_get_rule_perf_history_path(), default=None)
        if rule_perf_history is None:
            return ""

    if not isinstance(rule_perf_history, dict):
        return ""

    # 2. 提取当前维度涉及的规则编号 — 走 SchemaRegistry 单点 SoT (step 3.5)
    # 替代 P0-B 落地的硬编码 `(?:RC|V|EV|FN)-\d+` regex. 加新前缀 (DQ-/BMAD-) 时
    # 只改 yaml, prompting 自动同步, 防漂移.
    dims = dimensions or get_review_dimensions()
    dim_rules_text = dims[dim_key]["rules"]
    dim_rule_ids = set(_extract_rule_ids_via_registry(dim_rules_text))
    if not dim_rule_ids:
        return ""

    # 3. 筛选异常规则：rejection_rate > 0.3 或 missed > 2 或 eval precision/recall 过低
    flagged = []
    for rule_id, stats in rule_perf_history.items():
        if not isinstance(stats, dict):
            continue
        # 规则编号归一化匹配（history 中可能是 "RC-005" 或 "V-07"）
        canonical = rule_id.strip()
        if canonical not in dim_rule_ids:
            continue

        rejection_rate = stats.get("rejection_rate", 0)
        missed = stats.get("stats", {}).get("missed", 0)

        # F2: 同时考虑 eval_metrics 中的 precision/recall
        eval_m = stats.get("eval_metrics") or {}
        eval_precision = eval_m.get("precision", 1.0)
        eval_recall = eval_m.get("recall", 1.0)
        eval_has_data = bool(eval_m)  # 有数据才参与判断

        triggers = (
            rejection_rate > 0.3
            or missed > 2
            or (eval_has_data and eval_precision < 0.6)
            or (eval_has_data and eval_recall < 0.6)
        )

        if triggers:
            flagged.append({
                "rule_id": canonical,
                "rejection_rate": rejection_rate,
                "missed": missed,
                "name": stats.get("name", ""),
                "recent_total": stats.get("stats", {}).get("total", 0),
                "eval_precision": eval_precision if eval_has_data else None,
                "eval_recall": eval_recall if eval_has_data else None,
            })

    # P0.2: 同时收集 impact_score 异常的规则(低效 / 高效)
    low_impact = []   # impact_score < 0.3
    high_impact = []  # impact_score > 0.8
    for rule_id, stats in rule_perf_history.items():
        if not isinstance(stats, dict):
            continue
        canonical = rule_id.strip()
        if canonical not in dim_rule_ids:
            continue
        impact = stats.get("impact_score")
        if impact is not None:
            name = stats.get("name", "")
            if impact < 0.3:
                low_impact.append({"rule_id": canonical, "name": name, "impact_score": impact})
            elif impact > 0.8:
                high_impact.append({"rule_id": canonical, "name": name, "impact_score": impact})

    if not flagged and not low_impact and not high_impact:
        return ""

    lines = []

    # 原有的异常规则反馈
    if flagged:
        # 4. 按 missed + rejection_rate + 1-precision 综合排序，取前 5 条
        def _severity(r):
            p = r["eval_precision"] if r["eval_precision"] is not None else 1.0
            return (r["missed"], r["rejection_rate"], 1.0 - p)
        flagged.sort(key=_severity, reverse=True)
        flagged = flagged[:5]

        lines += [
            "## 近期反馈提示 — **辅助优先级 / 信鸽 v1**",
            "以下来自代码 commit 隐式反推 (rejection_rate / missed / eval P/R), **作为参考信号**.",
            "**与上文「PM 反馈编译记录」(信鸽 v2) 冲突时, 以 v2 为准.**",
            "",
        ]
        for r in flagged:
            parts = []
            if r["name"]:
                label = f"{r['rule_id']}（{r['name']}）"
            else:
                label = r["rule_id"]

            if r["missed"] > 2:
                parts.append(f"漏报率高，近 {r.get('recent_total', '?')} 次评审中 {r['missed']} 次未检出")
            if r["rejection_rate"] > 0.3:
                pct = int(r["rejection_rate"] * 100)
                parts.append(f"驳回率 {pct}%，建议仅在有充分依据时提出")
            if r["eval_precision"] is not None and r["eval_precision"] < 0.6:
                parts.append(f"Eval 精确率 {int(r['eval_precision']*100)}%，降低误报")
            if r["eval_recall"] is not None and r["eval_recall"] < 0.6:
                parts.append(f"Eval 召回率 {int(r['eval_recall']*100)}%，加强检出")

            lines.append(f"- {label}：{'；'.join(parts)}")

    # P0.2: impact_score 权重注入 — Worker 感知规则历史表现
    if low_impact:
        lines.append("")
        lines.append("## 低效规则警示")
        for r in sorted(low_impact, key=lambda x: x["impact_score"]):
            label = f"{r['rule_id']}（{r['name']}）" if r["name"] else r["rule_id"]
            score = r["impact_score"]
            lines.append(
                f"- {label}：⚠ 低效规则(impact={score}),"
                f"历史上被评审人频繁驳回,谨慎报告,确保有充分依据"
            )

    if high_impact:
        lines.append("")
        lines.append("## 高效规则优先")
        for r in sorted(high_impact, key=lambda x: -x["impact_score"]):
            label = f"{r['rule_id']}（{r['name']}）" if r["name"] else r["rule_id"]
            score = r["impact_score"]
            lines.append(
                f"- {label}：✓ 高效规则(impact={score}),"
                f"历史上被评审人高度认可,优先检查"
            )

    return "\n".join(lines) + "\n"


def _build_real_refs_section(workspace):
    """扫 workspace 的真实 rule_id 和 wiki 页面清单注入 Worker prompt。

    借鉴百灵（riskbird_test_agent.load_real_imports）的防 FQN 幻觉策略：
    LLM 倾向于编造不存在的规则号和 wiki 引用，明确给出可用清单后显著降低幻觉率。

    配合 review_fixer.fix_review_items 使用——生成后如果 evidence 仍指向清单外的
    规则或页面，verify_evidence 会标记 verification_status=failed 并降权。
    """
    if not workspace or not os.path.isdir(workspace):
        return ""

    # 1. 扫 review-rules/ 抽所有 rule_id — 走 SchemaRegistry 单点 SoT (step 3.5)
    # 替代 P0-B 落地的硬编码 `(?:RC|V|EV|FN)-\d+` regex. 加新前缀只改 yaml, prompting
    # 自动同步; 老逻辑漏 EV-01/FN-XX 已是漂移先例.
    rule_ids = set()
    rules_dir = os.path.join(workspace, "review-rules")
    if os.path.isdir(rules_dir):
        for root, _, files in os.walk(rules_dir):
            for fn in files:
                if fn.endswith((".md", ".yaml", ".yml", ".txt")):
                    try:
                        fp = os.path.join(root, fn)
                        with open(fp, "r", encoding="utf-8") as f:
                            text = f.read()
                        rule_ids.update(_extract_rule_ids_via_registry(text, workspace=workspace))
                    except (OSError, UnicodeDecodeError):
                        continue

    # 2. 扫 wiki/ 抽所有页面名(去 .md 扩展名,排除隐藏文件)
    # 缺失 ⑤ A 类新鲜度: 同时记录 mtime,按 30/90/180 天分级标注,worker 自然会偏好新页面
    import time as _time
    now_ts = _time.time()
    wiki_pages = []  # [(name, age_days)]
    wiki_dir = os.path.join(workspace, "wiki")
    if os.path.isdir(wiki_dir):
        for fn in sorted(os.listdir(wiki_dir)):
            if fn.endswith(".md") and not fn.startswith("."):
                fp = os.path.join(wiki_dir, fn)
                try:
                    mtime = os.path.getmtime(fp)
                    age_days = int((now_ts - mtime) / 86400)
                except OSError:
                    age_days = 0
                wiki_pages.append((fn[:-3], age_days))

    if not rule_ids and not wiki_pages:
        return ""

    # B 类合法前缀文本 — 走 SchemaRegistry 单点 SoT (step 3.5). yaml 加 DQ-/BMAD-
    # 时这里自动同步, 不需要再手动改"扩 EV-/FN-"这种文案.
    b_class_format_hint = _b_class_format_hint(workspace=workspace)

    lines = [
        "## 真实依据清单（强制复用）",
        "以下清单由 workspace 扫描生成。verify_evidence 会对每条 item 的依据做硬验证：",
        "引用清单外的 rule_id 或 wiki 页面 → 标记 verification_status=failed → confidence_score 降权 50%。",
        "",
        "### 依据格式铁律（违反即 FAIL）",
        "",
        b_class_format_hint,
        "- **A 类**：`evidence_content` 必须包含 `[[页面名]]` 双方括号格式引用，**禁止使用《》书名号、「」、引号或其他符号**。页面名必须与下表精确一致。",
        "- **C 类**：竞品/行业/经验，必须在 `evidence_content` 里明确标注 `⚠️ 待确定` 或 `外部参考`，否则算 C 类违规。",
        "- **如果你想引用的规则/页面不在下表中**：降级为 C 类 + `⚠️ 待确定`，不要强行用 A/B 造假。",
        "",
    ]

    if rule_ids:
        lines.append(f"### 可用规则编号（{len(rule_ids)} 条，仅用于 evidence_type=B）")
        lines.append("")
        # 分行显示更紧凑,每行 5 个
        sorted_rules = sorted(rule_ids)
        for i in range(0, len(sorted_rules), 5):
            lines.append("  " + "  ".join(f"`{r}`" for r in sorted_rules[i:i+5]))
        lines.append("")

    if wiki_pages:
        lines.append(f"### 可用 wiki 页面({len(wiki_pages)} 条,仅用于 evidence_type=A)")
        lines.append("")
        lines.append("**正例**:`**依据**: [A] [[约束-接口命名规范]] 第 3 节约定所有 endpoint 必须 /api/v1 前缀`")
        lines.append("**反例**:`**依据**: [A] 知识库《约束-接口命名规范》...`  <- 书名号会被判 failed")
        lines.append("**反例**:`**依据**: [A] [[不存在的页面]]`  <- 页面不在下表会被判 failed")
        lines.append("")
        lines.append("**新鲜度标注** (缺失 ⑤): `🟢 新鲜` <30天 / `🟡 一般` 30-90天 / `🟠 旧` 90-180天 / `🔴 过期` >180天")
        lines.append("过期的 wiki 页面优先级低,如果新页面也能引用,优先用新的。")
        lines.append("")
        for p, age_days in wiki_pages:
            if age_days < 30:
                badge = "🟢"
            elif age_days < 90:
                badge = "🟡"
            elif age_days < 180:
                badge = "🟠"
            else:
                badge = "🔴"
            lines.append(f"- {badge} `[[{p}]]` ({age_days}d)")
        lines.append("")

    # L4 GraphRAG Phase 3: 注入 wiki KG 工具说明 (workspace/wiki/_kg/ 存在时才加).
    # worker 拿到这段说明后, 在依据写法上可以选择两种格式:
    #   1. 老格式 [[页面名]] — 走 manifest 字符串匹配 (向后兼容)
    #   2. 新格式 [[entity:e_xxx]] — 走 KG entity 验证, 解决"页面名不一致"痛点
    kg_section = _build_kg_tools_hint(workspace)
    if kg_section:
        lines.append(kg_section)

    return "\n".join(lines)


def _build_kg_tools_hint(workspace):
    """L4 GraphRAG Phase 3: 给 worker 介绍 search_entity / expand_neighbors 概念.

    实现注意:
    - **不真改 worker tool list** — 只在 prompt 里告知, 让 worker "声明引用" 而不真 tool call.
      避免改 worker.py 的 tool 调用栈, 风险最小化.
    - 当 workspace/wiki/_kg/entities.json 存在时, 列前 20 个 entity 当样例 (按 type 多样性).
    - worker 引用时写 `[[entity:e_xxx]]`, evidence_verify 会走 entity 验证而非 page name 匹配.
    """
    if not workspace or not os.path.isdir(workspace):
        return ""
    kg_dir = os.path.join(workspace, "wiki", "_kg")
    ents_path = os.path.join(kg_dir, "entities.json")
    if not os.path.isfile(ents_path):
        return ""

    try:
        with open(ents_path, "r", encoding="utf-8") as f:
            entities = json.load(f)
    except (OSError, json.JSONDecodeError):
        return ""

    if not entities:
        return ""

    # 列出前 20 个 entity 当样例, round-robin 拿样本保证 type 覆盖
    sample_n = min(20, len(entities))
    by_type: dict = {}
    for e in entities:
        by_type.setdefault(e.get("type", "?"), []).append(e)
    samples = []
    while len(samples) < sample_n and by_type:
        for t in list(by_type.keys()):
            if by_type[t]:
                samples.append(by_type[t].pop(0))
                if not by_type[t]:
                    del by_type[t]
                if len(samples) >= sample_n:
                    break

    lines = [
        "",
        "## Wiki KG 工具 (L4 GraphRAG Phase 3 — 替代 [[页面名]] 字符串匹配)",
        "",
        f"workspace 已构建 KG ({len(entities)} 个 entity). 你可以引用 entity_id 替代页面名:",
        "- 老格式 `[[页面名]]` → 仍向后兼容, 但 manifest 字符串匹配命中精度 ~60%",
        "- 新格式 `[[entity:e_xxx]]` → 走 KG entity 验证, 修复 alias 不一致 (如 规范-字段映射 ↔ 字段映射规范) 痛点",
        "",
        "**两个工具概念 (你声明引用即可, 无需真 tool call)**:",
        "- `search_entity(query)`: 在 KG 中搜实体, 返回 top-5 匹配 (含 title + aliases + 来源页)",
        "- `expand_neighbors(entity_id, hops=1)`: 拓展 1-hop 邻居, 用于跨 wiki 页推理 (如 \"字段 X 是否在表 Y\")",
        "",
        "**用法**: 先用 search_entity 找到精确实体 ID, 再用 expand_neighbors 做多跳查询.",
        "引用时在 evidence_content 里写 `[[entity:e_xxx]]`, 验证器会查 _kg/entities.json:",
        "  ✅ `**依据**: [A] [[entity:e_a1b2c3d4]] (字段映射规范) 明确要求所有字段标 source_table`",
        "  ✅ `**依据**: [A] [[约束-接口命名规范]]` (老格式仍可用)",
        "  ❌ `**依据**: [A] [[entity:e_99999999]]` (entity_id 不存在 → 标 failed)",
        "",
        f"**KG 实体样例 ({len(samples)} 条, 完整列表见 wiki/_kg/entities.json)**:",
    ]
    for ent in samples[:sample_n]:
        title = ent.get("title", "")
        etype = ent.get("type", "")
        eid = ent.get("id", "")
        aliases = ent.get("aliases", [])
        alias_str = f" (别名: {', '.join(aliases[:3])})" if aliases else ""
        lines.append(f"- `{eid}` [{etype}] {title}{alias_str}")
    lines.append("")
    return "\n".join(lines)


def _maybe_compact_wiki(wiki_pages, budget):
    """二次截断钩子 (CC compact 模式预留接口).

    当 prompt token 估算超过 COMPACT_THRESHOLD 时调用。
    目前按内容顺序做保守字符预算截断,避免 compact warning 只是空响。
    """
    log.info(f"[compact] _maybe_compact_wiki 被调用, pages={len(wiki_pages)}, budget={budget}")
    compacted = {}
    used = 0
    for title, content in wiki_pages.items():
        remaining = budget - used
        if remaining <= 0:
            break
        if len(content) <= remaining:
            compacted[title] = content
            used += len(content)
            continue
        suffix = f"\n\n(... 余 {len(content) - remaining} 字已省略 — compact 预算截断)"
        if len(suffix) < remaining:
            compacted[title] = content[: remaining - len(suffix)].rstrip() + suffix
        else:
            compacted[title] = content[:remaining]
        used += len(compacted[title])
        break
    return compacted


def _workspace_from_wiki_path(wiki_path):
    if not wiki_path:
        return None
    wiki_dir = os.path.abspath(str(wiki_path))
    if os.path.basename(wiki_dir).lower() == "wiki":
        return os.path.dirname(wiki_dir)
    return wiki_dir


def _entity_source_authority(wiki_path, entity):
    """Return authority tier for the first local source page backing an entity."""
    if not wiki_path:
        return ""
    wiki_dir = os.path.abspath(str(wiki_path))
    for raw_page in entity.get("source_pages") or []:
        source_page = str(raw_page or "").strip()
        if not source_page:
            continue
        candidates = [source_page]
        if not os.path.splitext(source_page)[1]:
            candidates.append(f"{source_page}.md")
        for candidate_name in candidates:
            candidate = os.path.abspath(os.path.join(wiki_dir, candidate_name))
            try:
                if os.path.commonpath([wiki_dir, candidate]) != wiki_dir:
                    continue
            except ValueError:
                continue
            if not os.path.isfile(candidate):
                continue
            try:
                from review.evidence_verify import _wiki_authority_tier

                return _wiki_authority_tier(candidate)
            except Exception as exc:  # noqa: BLE001 - authority is prompt metadata.
                log.debug(f"[prompting] KG entity authority lookup skipped: {exc}")
                return ""
    return ""


def _build_prd_entity_anchor_section(prd_content, wiki_path, max_entities=5):
    """Inject compact KG entity anchors matched from PRD text.

    This is a prompt hint only: workers still need to cite exact evidence and
    evidence_verify remains responsible for checking [[entity:e_xxx]] validity.
    """
    workspace = _workspace_from_wiki_path(wiki_path)
    if not workspace:
        return ""
    try:
        from review.wiki_kg_tools import search_entity

        entities = search_entity(
            prd_content or "",
            top_k=max_entities,
            workspace=workspace,
        )
    except Exception as exc:  # noqa: BLE001 - KG anchors must not block review.
        log.debug(f"[prompting] KG entity anchor lookup skipped: {exc}")
        return ""
    if not entities:
        return ""

    lines = [
        "## Wiki entity anchors matched from PRD",
        (
            "These private-domain concepts matched the PRD text. Prefer "
            "`[[entity:e_xxx]]` citations when one of these anchors is the "
            "actual evidence for a finding."
        ),
    ]
    for ent in entities[:max_entities]:
        eid = str(ent.get("id") or "").strip()
        title = str(ent.get("title") or "").strip()
        etype = str(ent.get("type") or "").strip()
        pages = ", ".join(str(p) for p in (ent.get("source_pages") or [])[:3])
        authority = _entity_source_authority(wiki_path, ent)
        score = ent.get("score")
        if not eid or not title:
            continue
        tail = []
        if etype:
            tail.append(f"type={etype}")
        if authority:
            tail.append(f"authority={authority}")
        if pages:
            tail.append(f"sources={pages}")
        if score is not None:
            tail.append(f"score={score}")
        meta = f" ({'; '.join(tail)})" if tail else ""
        lines.append(f"- `[[entity:{eid}]]` {title}{meta}")
    return "\n".join(lines) if len(lines) > 2 else ""


def _build_worker_messages(
    prd_content,
    wiki_pages,
    dim_key=None,
    wiki_path=None,
    wiki_keywords=None,
    diff_context=None,
    on_wiki_selection=None,
    wiki_budget_chars=None,
    recovery_mode=False,
    prd_context_packet=None,
):
    """构建 worker 的 user messages，包含 PRD 和知识库内容"""
    from agent_config import MAX_WIKI_CHARS, COMPACT_THRESHOLD
    from review.scenario_detection import scenario_focus_for_dimension
    from review.wiki_selection import select_wiki_pages

    wk = wiki_keywords or get_wiki_keywords()
    if prd_context_packet:
        parts = [
            (
                "## 待评审 PRD（压缩视图）\n\n"
                f"{prd_context_packet}\n\n"
                "> 完整 PRD 仍是事实源；这里为降低中转站超时，只提供结构索引和本维度相关摘录。\n"
                "> 如果摘录标题里有原文行号，提交改进项时 location / 位置字段优先写成“原文第 X-Y 行 + 章节名”。"
            )
        ]
    else:
        parts = [f"## 待评审 PRD\n\n{prd_content}"]
    if diff_context:
        parts.insert(0, diff_context)  # diff context before PRD content
    scenario_focus = scenario_focus_for_dimension(prd_content, dim_key)
    if scenario_focus:
        parts.append(scenario_focus)
    entity_anchor_section = _build_prd_entity_anchor_section(prd_content, wiki_path)
    if entity_anchor_section:
        parts.append(entity_anchor_section)
    wiki_char_total = 0
    if wiki_pages:
        wiki_budget = wiki_budget_chars or _wiki_budget_for_dim(
            dim_key,
            MAX_WIKI_CHARS,
            prd_content=prd_content,
            wiki_pages=wiki_pages,
            recovery_mode=recovery_mode,
        )
        filtered, selection_telemetry = select_wiki_pages(
            wiki_pages,
            prd_content,
            dim_key=dim_key,
            wiki_keywords=wk,
            max_chars=wiki_budget,
            summary_chars=500,
        )
        selection_telemetry["budget_chars"] = wiki_budget
        selection_telemetry["strategy"] = "adaptive_recovery" if recovery_mode else "adaptive"
        if on_wiki_selection is not None:
            try:
                on_wiki_selection(selection_telemetry)
            except Exception:
                pass
        if selection_telemetry["omitted_count"]:
            log.info(
                f"[{_cn_label(dim_key) if dim_key else 'global'}] wiki_selection "
                f"{selection_telemetry['selected_count']} selected / "
                f"{selection_telemetry['omitted_count']} omitted, "
                f"chars={selection_telemetry['total_chars_after']:,}/"
                f"{selection_telemetry['total_chars_before']:,}"
            )

        parts.append("## 相关知识库页面\n")
        for title, content in filtered.items():
            # 加新鲜度标记（CC memoryAge 模式）
            if wiki_path:
                fpath = os.path.join(wiki_path, f"{title}.md")
                content = _add_freshness_note(fpath, content)
            wiki_char_total += len(content)
            parts.append(f"### {title}\n{content}\n")

        # 1b: rapid_refill_breaker 钩子 — wiki 注入接近预算上限时 warning
        if wiki_char_total > wiki_budget * 0.95:
            log.warning(f"[{_cn_label(dim_key) if dim_key else 'global'}] approaching wiki budget limit: {wiki_char_total:,} / {wiki_budget:,} chars (95%+)")

    parts.append(
        "请评审以上 PRD，逐条对照你的检查清单，然后调用 submit_review_items 工具提交发现的所有改进项。"
        "每条改进项必须标注 rule_id；location / 位置请写成可在 PRD 中搜索到的短句、章节名或原文行号，"
        "避免只写“全文/整体/上述”。"
    )

    messages = [{"role": "user", "content": "\n\n".join(parts)}]

    # 4a: token 估算 (CC tokenEstimation 模式)
    estimated_tokens = len(json.dumps(messages, ensure_ascii=False).encode()) // 4
    log.info(f"[{_cn_label(dim_key) if dim_key else 'global'}] estimated prompt tokens: {estimated_tokens:,}")
    if estimated_tokens > 100_000:
        log.warning(f"[{_cn_label(dim_key) if dim_key else 'global'}] prompt token 估算 > 100K,可能触发 context overflow")

    # 4b: compact 钩子 — wiki 已在 select_wiki_pages 阶段按 MAX_WIKI_CHARS 收敛;
    # 若这里仍超阈值,通常是 PRD 本身过长,只能先告警给上层做 diff/section review。
    if estimated_tokens > COMPACT_THRESHOLD and wiki_pages:
        log.warning(
            f"[{_cn_label(dim_key) if dim_key else 'global'}] prompt 仍超过 compact 阈值: "
            f"{estimated_tokens:,} / {COMPACT_THRESHOLD:,} tokens"
        )

    return messages
