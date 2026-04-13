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
import os
import copy

from dotenv import load_dotenv

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
2. 漏报补充：所有评审员都遗漏但你认为重要的问题（最多补充 3 条，不要发散）。
3. 冲突调解：不同评审员对同一处的判断矛盾时，给出你的裁决。

原则：
- 你的审核权重高于单个 worker，但不能推翻有充分依据的结论
- 只在有明确理由时才标记误报
- 补充的漏报必须有依据，不能编造
- 冲突调解必须说明裁决理由
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
                "description": "苍鹰补充的漏报（最多 3 条）",
                "items": {
                    "type": "object",
                    "properties": {
                        "location": {"type": "string", "description": "PRD 中的位置"},
                        "issue": {"type": "string", "description": "具体问题"},
                        "severity": {
                            "type": "string",
                            "enum": ["must", "should"],
                        },
                        "evidence": {"type": "string", "description": "依据"},
                    },
                    "required": ["location", "issue", "severity", "evidence"],
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
# 默认模型
# ============================================================

DEFAULT_MODEL = "claude-opus-4-6"


# ============================================================
# 构建 Anthropic Client
# ============================================================

def _make_client():
    """从 .env 创建 anthropic client"""
    import anthropic

    # 清掉 Claude Code 注入的旧 auth token
    os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)

    api_key = os.getenv("ANTHROPIC_API_KEY")
    base_url = os.getenv("ANTHROPIC_BASE_URL")
    kwargs = {}
    if api_key:
        kwargs["api_key"] = api_key
    if base_url:
        kwargs["base_url"] = base_url
    return anthropic.Anthropic(**kwargs)


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

        parts.append(
            f"### {item_id}（{dim} | {severity}）\n"
            f"- 位置：{loc}\n"
            f"- 问题：{issue}\n"
            f"- 建议：{suggestion}\n"
            f"- 依据：{evidence}\n"
        )

    parts.append(
        "请仔细审核以上所有改进项，完成后使用 submit_advisor_review 工具提交你的审核结果。\n"
        "注意：漏报补充最多 3 条，不要发散。"
    )

    return "\n\n".join(parts)


def advisor_review(client, prd_content, worker_results, wiki_pages=None, model=DEFAULT_MODEL):
    """
    苍鹰交叉校验主函数
    - client: anthropic.Anthropic 实例（可传入或 None 自动创建）
    - prd_content: PRD 全文
    - worker_results: 合并后的改进项列表（含 id/dimension/location/issue 等）
    - wiki_pages: dict {页面标题: 页面内容}，可选
    - model: 使用的模型，默认 claude-opus-4-6
    返回: AdvisorResult dict
    """
    if client is None:
        client = _make_client()

    print(GOSHAWK_ART)

    user_msg = _build_advisor_user_message(prd_content, worker_results, wiki_pages)

    response = client.messages.create(
        model=model,
        max_tokens=4096,
        system=GOSHAWK_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_msg}],
        tools=[SUBMIT_ADVISOR_REVIEW_TOOL],
        tool_choice={"type": "any"},  # 强制使用工具输出
    )

    # 从 response 中提取 tool_use 结果
    result = _extract_advisor_result(response)
    result["verdict"] = "REVIEWED"
    result["model_used"] = model

    return result


def _extract_advisor_result(response):
    """从 Messages API 响应中提取苍鹰的结构化输出"""
    for block in response.content:
        if block.type == "tool_use" and block.name == "submit_advisor_review":
            data = block.input
            return {
                "flagged_as_false_positive": data.get("flagged_as_false_positive", []),
                "additional_findings": data.get("additional_findings", []),
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

def apply_advisor_result(review_items, advisor_result):
    """
    将苍鹰的审核结果合并回改进项列表
    - 误报：降级 severity 或移除，加 advisor_note
    - 漏报：追加到列表末尾，标记 source="苍鹰补充"
    - 冲突：合并冲突项，保留裁决
    返回: 合并后的新列表
    """
    items = copy.deepcopy(review_items)
    items_by_id = {item["id"]: item for item in items}

    # 1. 处理误报
    for fp in advisor_result.get("flagged_as_false_positive", []):
        item_id = fp["item_id"]
        if item_id not in items_by_id:
            continue

        target = items_by_id[item_id]
        rec = fp.get("recommendation", "")

        if "移除" in rec:
            # 标记为移除（不物理删除，留审计痕迹）
            target["status"] = "REMOVED_BY_ADVISOR"
            target["advisor_note"] = f"苍鹰认为过度解读了。{fp['reason']}"
            print(f'  苍鹰：{item_id} 这条改进项...苍鹰认为过度解读了。')
        else:
            # 降级为 should
            target["severity"] = "should"
            target["advisor_note"] = f"苍鹰建议降级。{fp['reason']}"
            print(f'  苍鹰：{item_id} 降级为 should -- {fp["reason"]}')

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

    for i, finding in enumerate(advisor_result.get("additional_findings", [])[:3], start=1):
        new_id = f"R-{max_num + i:03d}"
        new_item = {
            "id": new_id,
            "location": finding.get("location", ""),
            "issue": finding.get("issue", ""),
            "suggestion": "",  # 苍鹰只指出问题，不给具体建议
            "severity": finding.get("severity", "should"),
            "evidence_type": "A",
            "evidence_content": finding.get("evidence", ""),
            "dimension": "苍鹰补充",
            "source": "苍鹰补充",
        }
        items.append(new_item)
        print(f'  苍鹰：所有鸟都没看到这个？苍鹰补充 {new_id}。')

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

    # 过滤掉被移除和被合并的（但保留在返回结构中做审计）
    active_items = [
        item
        for item in items
        if item.get("status") not in ("REMOVED_BY_ADVISOR", "MERGED_BY_ADVISOR")
    ]

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
            lines.append(f"- **{f.get('location', '')}**（{f.get('severity', 'should')}）：{f.get('issue', '')}")
            lines.append(f"  - 依据：{f.get('evidence', '')}")
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
    """将 CLI 参数转为完整模型名"""
    mapping = {
        "opus": "claude-opus-4-6",
        "sonnet": "claude-sonnet-4-6",
        "haiku": "claude-haiku-4-5",
    }
    return mapping.get(model_arg, model_arg)


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
        print("苍鹰：报告中没有找到改进项（R-NNN），无需审核。")
        return

    print(f"苍鹰：发现 {len(review_items)} 条改进项，开始交叉校验...\n")

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
    client = _make_client()
    result = advisor_review(client, prd_content, review_items, wiki_pages, model)

    # 合并结果
    updated_items = apply_advisor_result(review_items, result)

    # 生成报告
    report = format_advisor_report(result)

    # 输出
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(report_content)
            f.write(report)
        print(f"\n苍鹰：审核报告已写入 {args.output}")
    else:
        print(report)

    # 打印摘要
    fp_count = len(result.get("flagged_as_false_positive", []))
    add_count = len(result.get("additional_findings", []))
    conf_count = len(result.get("conflict_resolutions", []))
    print(
        f"\n苍鹰审核完毕：误报 {fp_count} 条，补充 {add_count} 条，"
        f"调解 {conf_count} 处冲突，信心度 {result.get('confidence', 0):.0%}"
    )


if __name__ == "__main__":
    main()
