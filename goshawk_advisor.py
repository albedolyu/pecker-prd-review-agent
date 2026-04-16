"""
苍鹰（Goshawk）Advisor Agent -- 交叉校验模块
功能：
  1. 用更强模型审核 4 个 worker 的评审结论
  2. 误报检测 / 漏报补充 / 冲突调解
  3. 结果合并回主评审列表
  4. 可独立 CLI 运行
"""

import argparse
import json
import random
import os
import copy
import time as _time

from dotenv import load_dotenv
from agent_config import MODEL_TIERS
from logger import get_logger

log = get_logger("goshawk")

# ============================================================
# 苍鹰 ASCII Art
# ============================================================

GOSHAWK_ART = r"""
      _____
     /     \
    | () () |    苍鹰俯瞰全局...
    |   >   |    "我不重新评审，我审核评审。"
     \_____/
      |   |
     /|   |\
    / |   | \
"""

# ============================================================
# System Prompt
# ============================================================

GOSHAWK_SYSTEM_PROMPT = """你是「苍鹰」，啄木鸟评审团的高级顾问。

你的职责不是重新评审 PRD，而是审核其他评审员（织布鸟、猫头鹰、渡鸦、鸬鹚）的评审结论。

你要做三件事：
1. 误报检测：哪些改进项是过度解读？PRD 在其他地方可能已有解释。
2. 漏报补充（最多 2 条）：仅限以下规则列表中有明确编号的规则被全部 Worker 遗漏的情况。每条必须引用具体规则编号（如 RC-005 或 V-07）和 PRD 中的具体位置。不得补充规则列表之外的问题。
   可引用的规则：V-02~V-12, RC-004~RC-015
3. 冲突调解：不同评审员对同一处的判断矛盾时，给出你的裁决，必须引用冲突双方的 item_id。

原则：
- 你的审核权重高于单个 worker，但不能推翻有充分依据的结论
- 只在有明确理由时才标记误报
- 补充的漏报必须有规则编号依据，不能编造规则列表之外的问题
- 冲突调解必须说明裁决理由，并引用相关 item_id
"""

# ============================================================
# Tool Schema -- 让苍鹰结构化输出
# ============================================================

SUBMIT_ADVISOR_REVIEW_TOOL = {
    "name": "submit_advisor_review",
    "description": "提交苍鹰的交叉校验结果，包含误报检测、漏报补充、冲突调解。",
    "input_schema": {
        "type": "object",
        "properties": {
            "flagged_as_false_positive": {
                "type": "array",
                "description": "被标记为误报（过度解读）的改进项",
                "items": {
                    "type": "object",
                    "properties": {
                        "item_id": {"type": "string", "description": "改进项编号，如 R-003"},
                        "reason": {"type": "string", "description": "判断为误报的理由"},
                        "recommendation": {
                            "type": "string",
                            "description": "建议处理方式：降级为 should / 移除",
                        },
                    },
                    "required": ["item_id", "reason", "recommendation"],
                },
            },
            "additional_findings": {
                "type": "array",
                "description": "被所有 Worker 遗漏但有明确规则依据的问题，最多 2 条(硬约束)",
                "maxItems": 2,
                "items": {
                    "type": "object",
                    "properties": {
                        "rule_id": {"type": "string", "description": "规则编号，如 RC-005 或 V-07"},
                        "location": {"type": "string", "description": "PRD 中的位置"},
                        "issue": {"type": "string", "description": "具体问题"},
                        "suggestion": {"type": "string", "description": "改进建议"},
                        "severity": {
                            "type": "string",
                            "enum": ["must", "should"],
                        },
                        "evidence_type": {"type": "string", "description": "依据类型：A/B/C"},
                        "evidence_content": {"type": "string", "description": "依据内容"},
                    },
                    "required": ["rule_id", "location", "issue", "suggestion", "severity", "evidence_type", "evidence_content"],
                },
            },
            "conflict_resolutions": {
                "type": "array",
                "description": "冲突调解结果",
                "items": {
                    "type": "object",
                    "properties": {
                        "items": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "冲突的改进项编号列表",
                        },
                        "resolution": {"type": "string", "description": "裁决结论"},
                        "reason": {"type": "string", "description": "裁决理由"},
                    },
                    "required": ["items", "resolution", "reason"],
                },
            },
            "confidence": {
                "type": "number",
                "description": "苍鹰对自己判断的信心，0-1",
            },
        },
        "required": [
            "flagged_as_false_positive",
            "additional_findings",
            "conflict_resolutions",
            "confidence",
        ],
    },
}

# ============================================================
# 默认模型（从 agent_config 统一获取）
# ============================================================

# Opus→Sonnet: Opus CLI 2/3 轮 timeout,Sonnet 稳定 30-60s。质量略降但每次跑完。
DEFAULT_MODEL = MODEL_TIERS["sonnet"]


# ============================================================
# 构建 Anthropic Client
# ============================================================

def _make_client():
    """从 .env 创建 API client（复用 api_adapter，确保 token 统计一致）"""
    from api_adapter import create_client
    return create_client()


# ============================================================
# 核心：Advisor 调用
# ============================================================

def _build_advisor_user_message(prd_content, worker_results, wiki_pages=None):
    """构建给苍鹰的 user message"""
    parts = []

    # PRD 原文
    parts.append(f"## 待审核的 PRD 原文\n\n{prd_content}")

    # 知识库（可选）
    if wiki_pages:
        parts.append("## 相关知识库页面\n")
        for title, content in wiki_pages.items():
            parts.append(f"### {title}\n{content}\n")

    # Worker 评审结果
    parts.append("## 各 Worker 的评审结果\n")
    parts.append("以下是 4 个评审员提交的所有改进项，请逐条审核：\n")

    for item in worker_results:
        item_id = item.get("id", "?")
        dim = item.get("dimension", "未知")
        loc = item.get("location", "")
        issue = item.get("issue", "")
        suggestion = item.get("suggestion", "")
        severity = item.get("severity", "")
        evidence = item.get("evidence_content", "")
        rule_id = item.get("rule_id", "")

        rule_line = f"- 规则编号：{rule_id}\n" if rule_id else ""
        parts.append(
            f"### {item_id}（{dim} | {severity}）\n"
            f"{rule_line}"
            f"- 位置：{loc}\n"
            f"- 问题：{issue}\n"
            f"- 建议：{suggestion}\n"
            f"- 依据：{evidence}\n"
        )

    parts.append(
        "请仔细审核以上所有改进项，完成后使用 submit_advisor_review 工具提交你的审核结果。\n"
        "注意：漏报补充最多 2 条，每条必须引用具体规则编号（V-02~V-12, RC-004~RC-015），不得补充规则列表之外的问题。\n\n"
        "**输出格式硬约束**：你必须且只能输出一个 JSON 对象,严格遵循 submit_advisor_review 的 schema。"
        "不要在 JSON 前后写任何解释文字、markdown code fence 或注释。"
        "确保所有 string 字段使用双引号,数组用 [],对象用 {},不要有 trailing comma。"
    )

    return "\n\n".join(parts)


def advisor_review(client, prd_content, worker_results, wiki_pages=None, model=DEFAULT_MODEL):
    """
    苍鹰交叉校验主函数
    含指数退避重试 + tool_use 检测 + 催促重试 + 文本兜底
    """
    if client is None:
        client = _make_client()

    print(GOSHAWK_ART)

    user_msg = _build_advisor_user_message(prd_content, worker_results, wiki_pages)
    messages = [{"role": "user", "content": user_msg}]

    import time

    def _call(msgs):
        return client.create(
            model=model,
            max_tokens=4096,
            system=GOSHAWK_SYSTEM_PROMPT,
            messages=msgs,
            tools=[SUBMIT_ADVISOR_REVIEW_TOOL],
            tool_choice={"type": "any"},
        )

    # 指数退避重试
    max_retries = 2
    response = None
    for attempt in range(max_retries + 1):
        try:
            response = _call(messages)
            break
        except Exception as e:
            if attempt == max_retries:
                raise
            delay = 2 ** (attempt + 1) + random.uniform(0, 1)
            print(f"  终审 API 异常 (第{attempt + 1}次)，{delay:.1f}s 后重试: {str(e)[:60]}")
            time.sleep(delay)

    # Tool 调用检测：没有 tool_use 时催促重试
    result = _extract_advisor_result(response)
    has_tool = any(block.type == "tool_use" for block in response.content)

    if not has_tool:
        print("  终审未调用 tool，催促重试...")
        text_parts = "\n".join(block.text for block in response.content if block.type == "text")
        followup_msgs = messages + [
            {"role": "assistant", "content": text_parts},
            {"role": "user", "content": "请使用 submit_advisor_review 工具提交你的审核结果。"},
        ]
        time.sleep(2 + random.uniform(0, 0.5))
        try:
            response2 = _call(followup_msgs)
            result2 = _extract_advisor_result(response2)
            has_tool2 = any(block.type == "tool_use" for block in response2.content)
            if has_tool2:
                result = result2
                response = response2
        except Exception:
            pass

    result["verdict"] = "REVIEWED"
    result["model_used"] = model
    # 保存 usage 供成本归因 (CC cost-tracker querySource 模式)
    result["usage"] = {
        "input_tokens": response.usage.get("input_tokens", 0) if hasattr(response.usage, 'get') else getattr(response.usage, 'input_tokens', 0),
        "output_tokens": response.usage.get("output_tokens", 0) if hasattr(response.usage, 'get') else getattr(response.usage, 'output_tokens', 0),
    }

    return result


async def advisor_review_async(client, prd_content, worker_results, wiki_pages=None, model=DEFAULT_MODEL):
    """苍鹰交叉校验异步版本（在线程池中执行同步逻辑）

    Phase G #9: 加 GOSHAWK_TIMEOUT 保护。Opus via Claude CLI 可能跑 10+ 分钟,
    超时后跳过交叉校验,直接返回一个"苍鹰超时"的空 advisor result,让 pipeline
    继续推进到 Phase 3。用户能看到 Phase 4 报告但没有苍鹰加持(降级)。
    """
    import asyncio
    from agent_config import GOSHAWK_TIMEOUT
    loop = asyncio.get_running_loop()
    try:
        return await asyncio.wait_for(
            loop.run_in_executor(
                None, lambda: advisor_review(client, prd_content, worker_results, wiki_pages, model)
            ),
            timeout=GOSHAWK_TIMEOUT,
        )
    except asyncio.TimeoutError:
        log.warning(f"苍鹰交叉校验超时({GOSHAWK_TIMEOUT}s),跳过终审,直接用 worker 合并结果")
        return {
            "flagged_as_false_positive": [],
            "additional_findings": [],
            "conflict_resolutions": [],
            "confidence": 0.0,
            "verdict": "TIMEOUT",
            "model_used": model,
        }


#: 漏报补充硬上限(schema + parser 双保险,防止模型绕过 schema)
MAX_ADDITIONAL_FINDINGS = 2

#: Side Query escalation 单条 item 最大验证次数 (L3 约束)
MAX_ESCALATIONS = 3


def _extract_advisor_result(response):
    """从 Messages API 响应中提取苍鹰的结构化输出"""
    for block in response.content:
        if block.type == "tool_use" and block.name == "submit_advisor_review":
            data = block.input
            additional = data.get("additional_findings", []) or []
            # 兜底截断:即使模型不遵守 schema maxItems,parser 层强制执行硬上限
            if len(additional) > MAX_ADDITIONAL_FINDINGS:
                log.warning(
                    f"苍鹰返回 {len(additional)} 条漏报补充,超出硬上限 {MAX_ADDITIONAL_FINDINGS},截断"
                )
                additional = additional[:MAX_ADDITIONAL_FINDINGS]
            return {
                "flagged_as_false_positive": data.get("flagged_as_false_positive", []),
                "additional_findings": additional,
                "conflict_resolutions": data.get("conflict_resolutions", []),
                "confidence": data.get("confidence", 0.0),
            }

    # 如果没有 tool_use，返回空结果
    return {
        "flagged_as_false_positive": [],
        "additional_findings": [],
        "conflict_resolutions": [],
        "confidence": 0.0,
    }


# ============================================================
# 结果合并
# ============================================================

def _verify_wiki_evidence(item, wiki_pages):
    """Side Query L1: 校验 A 类 evidence 引用的 wiki 页面标题是否真实存在。

    3 层升级链 (CC escalation 模式):
      L1: wiki 自动验证 — 检查 [[页面名]] 是否在 wiki_pages 中
      L2: 规则兜底 — evidence_type=A 且 wiki 验证失败 → 降级为 C + advisor_note
      L3: MAX_ESCALATIONS=3,单条 item 最多验证 3 次

    Returns: (passed: bool, note: str)
    """
    import re as _re
    ev_type = item.get("evidence_type", "")
    ev_content = item.get("evidence_content", "")

    if ev_type != "A" or not ev_content:
        return True, ""

    # L1: 提取 [[页面名]] 引用
    refs = _re.findall(r"\[\[(.+?)\]\]", ev_content)
    if not refs:
        return True, ""  # 没有标准引用格式,跳过

    wiki_titles = set(wiki_pages.keys()) if wiki_pages else set()
    escalation_count = 0

    for ref in refs:
        if escalation_count >= MAX_ESCALATIONS:
            break
        escalation_count += 1

        # 精确匹配 or 模糊匹配(页面名可能是 "约束-接口命名规范" 而引用写 "接口命名规范")
        found = any(ref == title or ref in title or title in ref for title in wiki_titles)
        if not found:
            # L2: 降级为 C 类 + advisor_note
            item["evidence_type"] = "C"
            note = f"L2 降级: [[{ref}]] 不在 wiki 中,A→C + ⚠️ 待确定"
            if "⚠️ 待确定" not in ev_content:
                item["evidence_content"] = ev_content + " (⚠️ 待确定,wiki 页面不存在)"
            return False, note

    return True, ""


def _build_gate_log(item, advisor_result, fp_map, conflict_map):
    """为单条 item 构建 gate 决策链 (CC decisionReason 模式)

    gates 列表记录每个检查点的 pass/fail + 原因,供前端 Phase 3 悬浮显示。
    """
    gates = []
    item_id = item.get("id", "")

    # Gate 1: schema 校验 — 必须字段是否齐全
    required = ("rule_id", "location", "issue", "suggestion", "severity", "evidence_type")
    missing = [f for f in required if not item.get(f)]
    gates.append({
        "type": "schema",
        "pass": len(missing) == 0,
        "detail": f"缺少字段: {missing}" if missing else None,
    })

    # Gate 2: confidence 校验
    conf = item.get("confidence_score", 1.0)
    gates.append({
        "type": "confidence",
        "pass": conf >= 0.3,
        "score": conf,
    })

    # Gate 3: evidence 校验 — verification_status 如果存在
    v_status = item.get("verification_status", "")
    if v_status:
        gates.append({
            "type": "evidence",
            "pass": v_status != "retracted",
            "reason": item.get("verification_reason", ""),
        })

    # Gate 4: advisor 误报标记
    if item_id in fp_map:
        fp = fp_map[item_id]
        gates.append({
            "type": "advisor_false_positive",
            "pass": False,
            "reason": fp.get("reason", ""),
            "recommendation": fp.get("recommendation", ""),
        })
    else:
        gates.append({
            "type": "advisor_false_positive",
            "pass": True,
        })

    # Gate 5: advisor 冲突
    if item_id in conflict_map:
        res = conflict_map[item_id]
        gates.append({
            "type": "advisor_conflict",
            "pass": True,
            "resolution": res.get("resolution", ""),
        })

    return {"gates": gates}


def _sanity_check_false_positives(fps, items_by_id, client):
    """用 Haiku 做苍鹰误报标记的 sanity check

    对每个被标为误报的 item,问 Haiku:
    "以下评审条目被终审标记为误报,理由是 {reason}。
     原始条目:{item summary}
     你同意这是误报吗?回答 agree 或 disagree + 一句话理由"

    如果 Haiku disagree,恢复 item 的 status(不标为 REMOVED),
    加 advisor_note "苍鹰标误报但 Haiku 不同意,保留待人工确认"

    Returns:
        dict: {"sanity_check_count": int, "sanity_check_disagreed": int}
    """
    if not fps or client is None:
        return {"sanity_check_count": 0, "sanity_check_disagreed": 0}

    haiku_model = MODEL_TIERS.get("haiku", "claude-haiku-4-5")
    check_count = 0
    disagreed_count = 0

    for fp in fps:
        item_id = fp.get("item_id", "")
        reason = fp.get("reason", "")
        item = items_by_id.get(item_id)
        if not item:
            continue

        # 跳过 pinned items(已在 apply_advisor_result 中处理)
        if item.get("pinned"):
            continue

        item_summary = (
            f"[{item.get('rule_id', '')}] {item.get('location', '')} "
            f"| {item.get('severity', '')} | {item.get('issue', '')[:200]}"
        )

        prompt = (
            f"以下评审条目被终审标记为误报,理由是: {reason}\n\n"
            f"原始条目: {item_summary}\n\n"
            f"你同意这是误报吗?回答 agree 或 disagree + 一句话理由。"
        )

        try:
            resp = client.create(
                model=haiku_model,
                max_tokens=256,
                messages=[{"role": "user", "content": prompt}],
                timeout=10,
            )
            text = ""
            for block in resp.content:
                if block.type == "text":
                    text += block.text.lower()
            check_count += 1

            if "disagree" in text:
                disagreed_count += 1
                # 恢复 item: 不标为 REMOVED,加备注
                if item.get("status") == "REMOVED_BY_ADVISOR":
                    item["status"] = "RESTORED_BY_SANITY_CHECK"
                item.setdefault("advisor_note", "")
                sanity_note = "苍鹰标误报但 Haiku 不同意,保留待人工确认"
                if item["advisor_note"]:
                    item["advisor_note"] += "; " + sanity_note
                else:
                    item["advisor_note"] = sanity_note
                log.info(f"[sanity_check] {item_id}: Haiku disagree — {text[:100]}")

        except Exception as e:
            # timeout 或其他异常,跳过不阻塞
            log.warning(f"[sanity_check] {item_id}: 跳过 ({str(e)[:60]})")
            continue

    telemetry = {
        "sanity_check_count": check_count,
        "sanity_check_disagreed": disagreed_count,
    }
    if check_count > 0:
        log.info(
            f"[sanity_check] 完成: {check_count} 条检查, "
            f"{disagreed_count} 条 Haiku 不同意"
        )
    return telemetry


def apply_advisor_result(review_items, advisor_result, wiki_pages=None, client=None):
    """
    将苍鹰的审核结果合并回改进项列表
    - 误报：降级 severity 或移除，加 advisor_note + gate_log
    - 漏报：追加到列表末尾，标记 source="苍鹰补充"
    - 冲突：合并冲突项，保留裁决
    - wiki 验证: A 类 evidence 的 wiki 引用存在性检查 (L1-L3)
    返回: 合并后的新列表 (每条 item 含 gate_log 字段)
    """
    items = copy.deepcopy(review_items)
    items_by_id = {item["id"]: item for item in items}

    # 预建 fp / conflict 索引,供 gate_log 查询
    fp_map = {}
    for fp in advisor_result.get("flagged_as_false_positive", []):
        fp_map[fp.get("item_id", "")] = fp
    conflict_map = {}
    for res in advisor_result.get("conflict_resolutions", []):
        for cid in res.get("items", []):
            conflict_map[cid] = res

    # 1. 处理误报
    for fp in advisor_result.get("flagged_as_false_positive", []):
        item_id = fp["item_id"]
        if item_id not in items_by_id:
            continue

        target = items_by_id[item_id]

        # Pattern 23: Pinned Edit State — 用户 pin 的 item 不被苍鹰修改
        if target.get("pinned"):
            target.setdefault("gate_log", [])
            target["gate_log"].append(f"pinned: 跳过苍鹰误报标记 ({fp.get('reason', '')[:60]})")
            continue

        rec = fp.get("recommendation", "")

        if "移除" in rec:
            # 标记为移除（不物理删除，留审计痕迹）
            target["status"] = "REMOVED_BY_ADVISOR"
            target["advisor_note"] = f"终审认为过度解读了。{fp['reason']}"
            print(f'  终审：{item_id} 这条改进项...终审认为过度解读了。')
        else:
            # 降级为 should
            target["severity"] = "should"
            target["advisor_note"] = f"终审建议降级。{fp['reason']}"
            print(f'  终审：{item_id} 降级为 should -- {fp["reason"]}')

    # 2. 处理漏报补充
    # 计算新编号起点
    max_num = 0
    for item in items:
        item_id = item.get("id", "")
        if item_id.startswith("R-"):
            try:
                num = int(item_id.split("-")[1])
                max_num = max(max_num, num)
            except (ValueError, IndexError):
                pass

    # B4: 苍鹰补充项的 confidence 需要衰减(is_supplement=True)
    from cuckoo_parser import compute_confidence
    for i, finding in enumerate(advisor_result.get("additional_findings", [])[:MAX_ADDITIONAL_FINDINGS], start=1):
        new_id = f"R-{max_num + i:03d}"
        evi_type = finding.get("evidence_type", "A")
        meta_confidence = compute_confidence(evi_type, is_supplement=True)  # B4
        new_item = {
            "id": new_id,
            "rule_id": finding.get("rule_id", ""),
            "location": finding.get("location", ""),
            "issue": finding.get("issue", ""),
            "suggestion": finding.get("suggestion", ""),
            "severity": finding.get("severity", "should"),
            "evidence_type": evi_type,
            "evidence_content": finding.get("evidence_content", finding.get("evidence", "")),
            "confidence_score": meta_confidence,  # B4(已有,后端用)
            # ============ Phase G #3: provenance 字段 ============
            # 标记这条是苍鹰补遗,前端 Phase 3 会显示"苍鹰补遗 · 红章"
            "provenance": "meta_added",
            "confidence": meta_confidence,             # 前端用的标准化字段(0..1)
            "cited_by_workers": ["final-reviewer"],     # 只有苍鹰一个人指证
            "dimension": "苍鹰补充",
            "source": "苍鹰补充",
        }
        items.append(new_item)
        print(f'  终审：所有编辑都没看到这个?补充 {new_id} (confidence={meta_confidence}).')

    # 3. 处理冲突调解
    for resolution in advisor_result.get("conflict_resolutions", []):
        conflict_ids = resolution.get("items", [])
        if len(conflict_ids) < 2:
            continue

        # 保留第一个，合并其余到第一个
        primary_id = conflict_ids[0]
        if primary_id not in items_by_id:
            continue

        primary = items_by_id[primary_id]
        primary["advisor_note"] = (
            f"冲突调解：{resolution['resolution']}（理由：{resolution['reason']}）"
        )

        # 将其余冲突项标记为合并
        for cid in conflict_ids[1:]:
            if cid in items_by_id:
                items_by_id[cid]["status"] = "MERGED_BY_ADVISOR"
                items_by_id[cid]["advisor_note"] = f"已合并至 {primary_id}"

    # Side Query L1-L3: wiki 标题验证 (仅在有 wiki_pages 时执行)
    if wiki_pages:
        for item in items:
            passed, note = _verify_wiki_evidence(item, wiki_pages)
            if not passed:
                log.info(f"[goshawk] {item.get('id', '?')} wiki 验证: {note}")
                item.setdefault("advisor_note", "")
                if item["advisor_note"]:
                    item["advisor_note"] += "; " + note
                else:
                    item["advisor_note"] = note

    # Haiku sanity check: 对被标为误报的 item 做二次校验
    # 只在有 false_positive 且 client 可用时触发(大部分评审 0 条 fp,零开销)
    sanity_telemetry = {"sanity_check_count": 0, "sanity_check_disagreed": 0}
    fps_list = advisor_result.get("flagged_as_false_positive", [])
    if fps_list and client is not None:
        sanity_telemetry = _sanity_check_false_positives(fps_list, items_by_id, client)

    # 为每条 item 生成 gate_log (CC decisionReason 模式)
    for item in items:
        item["gate_log"] = _build_gate_log(item, advisor_result, fp_map, conflict_map)

    # 过滤掉被移除和被合并的（但保留在返回结构中做审计）
    # 注意: RESTORED_BY_SANITY_CHECK 的 item 不会被过滤
    active_items = [
        item
        for item in items
        if item.get("status") not in ("REMOVED_BY_ADVISOR", "MERGED_BY_ADVISOR")
    ]

    # 附加 sanity check telemetry 到第一个 active item(供上层消费)
    if active_items and sanity_telemetry["sanity_check_count"] > 0:
        active_items[0].setdefault("_sanity_telemetry", sanity_telemetry)

    return active_items


# ============================================================
# 报告生成
# ============================================================

def format_advisor_report(advisor_result):
    """格式化苍鹰的审核报告（Markdown），附在评审报告末尾"""
    lines = [
        "",
        "---",
        "",
        "## 苍鹰交叉校验报告",
        "",
        f"模型：{advisor_result.get('model_used', 'unknown')}",
        f"判定：{advisor_result.get('verdict', 'REVIEWED')}",
        f"信心度：{advisor_result.get('confidence', 0):.0%}",
        "",
    ]

    # 误报检测
    fps = advisor_result.get("flagged_as_false_positive", [])
    lines.append(f"### 误报检测（{len(fps)} 条）")
    lines.append("")
    if fps:
        for fp in fps:
            lines.append(f"- **{fp['item_id']}**：{fp['reason']}")
            lines.append(f"  - 建议：{fp['recommendation']}")
    else:
        lines.append("无误报。鸟群判断一致。")
    lines.append("")

    # 漏报补充
    findings = advisor_result.get("additional_findings", [])
    lines.append(f"### 漏报补充（{len(findings)} 条）")
    lines.append("")
    if findings:
        for f in findings:
            rule_tag = f"[{f.get('rule_id')}] " if f.get('rule_id') else ""
            lines.append(f"- {rule_tag}**{f.get('location', '')}**（{f.get('severity', 'should')}）：{f.get('issue', '')}")
            lines.append(f"  - 依据：{f.get('evidence_content', f.get('evidence', ''))}")
    else:
        lines.append("无补充。鸟群覆盖全面。")
    lines.append("")

    # 冲突调解
    conflicts = advisor_result.get("conflict_resolutions", [])
    lines.append(f"### 冲突调解（{len(conflicts)} 条）")
    lines.append("")
    if conflicts:
        for c in conflicts:
            ids = ", ".join(c.get("items", []))
            lines.append(f"- **{ids}**：{c['resolution']}")
            lines.append(f"  - 理由：{c['reason']}")
    else:
        lines.append("无冲突。各维度评审员意见统一。")
    lines.append("")

    return "\n".join(lines)


# ============================================================
# CLI 入口
# ============================================================

def _parse_review_items_from_report(report_path):
    """
    从评审报告 Markdown 中解析出改进项列表
    简易解析：找 R-NNN 格式的条目
    """
    import re

    with open(report_path, "r", encoding="utf-8") as f:
        content = f.read()

    items = []
    # 匹配 ### R-001 或 **R-001** 等格式
    pattern = re.compile(
        r"(?:###?\s*)?(?:\*\*)?(?P<id>R-\d{3})(?:\*\*)?"
        r".*?位置[：:]\s*(?P<location>.+?)$"
        r".*?问题[：:]\s*(?P<issue>.+?)$"
        r".*?建议[：:]\s*(?P<suggestion>.+?)$"
        r".*?严重度[：:]\s*(?P<severity>must|should)",
        re.MULTILINE | re.DOTALL,
    )

    for m in pattern.finditer(content):
        items.append({
            "id": m.group("id"),
            "location": m.group("location").strip(),
            "issue": m.group("issue").strip(),
            "suggestion": m.group("suggestion").strip(),
            "severity": m.group("severity").strip(),
            "dimension": "",
            "evidence_type": "",
            "evidence_content": "",
        })

    # 兜底：如果正则没匹配到，用简易方式提取
    if not items:
        for line in content.split("\n"):
            m = re.match(r".*?(R-\d{3}).*", line)
            if m:
                items.append({
                    "id": m.group(1),
                    "location": "",
                    "issue": line.strip(),
                    "suggestion": "",
                    "severity": "should",
                    "dimension": "",
                    "evidence_type": "",
                    "evidence_content": "",
                })

    return items, content


def _resolve_model(model_arg):
    """将 CLI 参数转为完整模型名，统一从 agent_config 取"""
    return MODEL_TIERS.get(model_arg, model_arg)


def main():
    load_dotenv()

    parser = argparse.ArgumentParser(
        description="苍鹰 Advisor -- 啄木鸟评审团的高级顾问，交叉校验 worker 评审结果"
    )
    parser.add_argument("--prd", required=True, help="PRD 文件路径")
    parser.add_argument("--report", required=True, help="评审报告文件路径（含改进项）")
    parser.add_argument(
        "--model",
        default="opus",
        help="模型档位：opus / sonnet / haiku，或完整模型名（默认 opus）",
    )
    parser.add_argument("--wiki", default=None, help="wiki 知识库目录路径（可选）")
    parser.add_argument("--output", default=None, help="输出文件路径（默认打印到终端）")

    args = parser.parse_args()

    # 读 PRD
    with open(args.prd, "r", encoding="utf-8") as f:
        prd_content = f.read()

    # 从报告中解析改进项
    review_items, report_content = _parse_review_items_from_report(args.report)

    if not review_items:
        print("终审：报告中没有找到改进项（R-NNN），无需审核。")
        return

    print(f"终审：发现 {len(review_items)} 条改进项，开始交叉校验...\n")

    # 读知识库（可选）
    wiki_pages = {}
    if args.wiki and os.path.isdir(args.wiki):
        import glob as g

        for wiki_file in g.glob(os.path.join(args.wiki, "*.md")):
            title = os.path.splitext(os.path.basename(wiki_file))[0]
            with open(wiki_file, "r", encoding="utf-8", errors="replace") as f:
                wiki_pages[title] = f.read()

    # 调用苍鹰
    model = _resolve_model(args.model)
    from api_adapter import create_client
    client = create_client()
    result = advisor_review(client, prd_content, review_items, wiki_pages, model)

    # 合并结果(CLI 模式也传 client,启用 sanity check)
    updated_items = apply_advisor_result(review_items, result, client=client)

    # 生成报告
    report = format_advisor_report(result)

    # 输出
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(report_content)
            f.write(report)
        print(f"\n终审：审核报告已写入 {args.output}")
    else:
        print(report)

    # 打印摘要
    fp_count = len(result.get("flagged_as_false_positive", []))
    add_count = len(result.get("additional_findings", []))
    conf_count = len(result.get("conflict_resolutions", []))
    print(
        f"\n终审完毕：误报 {fp_count} 条，补充 {add_count} 条，"
        f"调解 {conf_count} 处冲突，信心度 {result.get('confidence', 0):.0%}"
    )


if __name__ == "__main__":
    main()
