"""
啄木鸟飞书 Bot -- 接收 PRD 文件，执行评审，发送交互式结果卡片
FastAPI 服务，POST /feishu/event 接收消息，POST /feishu/action 处理按钮点击
"""

import asyncio
import hashlib
import json
import os
import sys
import tempfile
from datetime import datetime

from logger import get_logger

log = get_logger("bot")

# 延迟导入 FastAPI（只在 bot 启动时需要）
try:
    from fastapi import FastAPI, Request
    from fastapi.responses import JSONResponse
except ImportError:
    FastAPI = None
    log.warning("FastAPI 未安装，飞书 Bot 不可用。pip install fastapi uvicorn")

# 已处理的 event_id 去重（飞书会重发消息）
_processed_events = set()
MAX_PROCESSED_CACHE = 1000


def create_app():
    """创建 FastAPI 应用"""
    if FastAPI is None:
        raise RuntimeError("FastAPI 未安装")

    app = FastAPI(title="啄木鸟飞书 Bot", version="1.0.0")

    @app.get("/health")
    async def health():
        return {"status": "ok", "service": "pecker-feishu-bot"}

    @app.post("/feishu/event")
    async def feishu_event(request: Request):
        """飞书事件回调入口"""
        body = await request.json()

        # URL 验证（飞书首次配置时发送的 challenge）
        if "challenge" in body:
            return {"challenge": body["challenge"]}

        # 事件去重
        header = body.get("header", {})
        event_id = header.get("event_id", "")
        if event_id in _processed_events:
            return {"code": 0, "msg": "duplicate"}
        _processed_events.add(event_id)
        if len(_processed_events) > MAX_PROCESSED_CACHE:
            _processed_events.clear()

        # 消息事件
        event_type = header.get("event_type", "")
        if event_type == "im.message.receive_v1":
            event = body.get("event", {})
            asyncio.create_task(_handle_message_safe(event))

        return {"code": 0}

    @app.post("/feishu/action")
    async def feishu_action(request: Request):
        """飞书卡片按钮回调"""
        body = await request.json()
        action = body.get("action", {})
        value = action.get("value", {})

        item_id = value.get("item_id", "")
        decision = value.get("decision", "")
        prd_name = value.get("prd", "")
        workspace = value.get("workspace", "")

        if item_id and decision:
            _save_decision(workspace, prd_name, item_id, decision)
            log.info(f"[action] {item_id} -> {decision}")

        return {"code": 0}

    return app


async def _handle_message_safe(event):
    """消息处理入口（带异常保护）"""
    try:
        await _handle_message(event)
    except Exception as e:
        log.error(f"消息处理失败: {str(e)[:100]}")


async def _handle_message(event):
    """处理收到的飞书消息"""
    from feishu_client import FeishuClient

    message = event.get("message", {})
    chat_id = message.get("chat_id", "")
    message_id = message.get("message_id", "")
    msg_type = message.get("message_type", "")
    content_str = message.get("content", "{}")

    content = json.loads(content_str)
    text = content.get("text", "")

    # 检测是否是评审请求
    if "评审" not in text:
        return

    client = FeishuClient()

    # 下载附件
    prd_content = None
    prd_name = "未命名PRD"

    if msg_type == "file" or "file_key" in content_str:
        # 消息本身是文件
        file_key = content.get("file_key", "")
        file_name = content.get("file_name", "document.md")
        if file_key:
            file_bytes = client.download_file(message_id, file_key)
            prd_content = file_bytes.decode("utf-8", errors="replace")
            prd_name = os.path.splitext(file_name)[0]

    if not prd_content:
        # 尝试从消息文本中提取 PRD 内容（PM 可能直接粘贴）
        if len(text) > 200:
            prd_content = text
            # 从首行提取名称
            first_line = text.split("\n")[0].strip().lstrip("# ")
            if first_line:
                prd_name = first_line[:30]
        else:
            client.reply_text(message_id, "请附带 PRD 文件（.md 格式）或直接粘贴 PRD 全文。")
            return

    # 发送"评审中"卡片
    progress_card = _build_progress_card(prd_name)
    progress_msg_id = client.send_card(chat_id, progress_card)

    # 创建临时 workspace 并执行评审
    sender = event.get("sender", {}).get("sender_id", {}).get("union_id", "feishu_user")

    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(None, lambda: _run_review(prd_content, prd_name, sender))

    # 发送结果卡片
    if result:
        result_card = _build_result_card(result["items"], prd_name, result.get("peck_score"), result.get("workspace", ""))
        if progress_msg_id:
            client.update_card(progress_msg_id, result_card)
        else:
            client.send_card(chat_id, result_card)
    else:
        client.reply_text(message_id, "评审失败，请检查 PRD 格式或联系管理员。")


def _run_review(prd_content, prd_name, reviewer):
    """在临时 workspace 中执行评审（同步，跑在线程池中）"""
    # 创建临时 workspace
    workspace = tempfile.mkdtemp(prefix=f"pecker_{prd_name[:10]}_")
    prd_dir = os.path.join(workspace, "prd")
    output_dir = os.path.join(workspace, "output")
    os.makedirs(prd_dir, exist_ok=True)
    os.makedirs(output_dir, exist_ok=True)

    # 写入 PRD
    prd_path = os.path.join(prd_dir, f"{prd_name}.md")
    with open(prd_path, "w", encoding="utf-8") as f:
        f.write(prd_content)

    try:
        from api_adapter import create_client
        from agent_config import MODEL_TIERS
        from parallel_review import parallel_review_sync, verify_evidence
        from easter_eggs import calculate_peck_score

        client = create_client()
        result = parallel_review_sync(client, prd_content, {}, MODEL_TIERS)
        items = verify_evidence(result["merged_items"], workspace)
        valid_items = [i for i in items if i.get("status") != "RETRACTED"]
        peck = calculate_peck_score(valid_items)

        return {
            "items": valid_items,
            "peck_score": peck,
            "workspace": workspace,
            "usage": result.get("total_usage", {}),
        }
    except Exception as e:
        log.error(f"评审执行失败: {str(e)[:100]}")
        return None


def _build_progress_card(prd_name):
    """构建"评审中"进度卡片"""
    return {
        "header": {
            "title": {"tag": "plain_text", "content": f"啄木鸟评审: {prd_name}"},
            "template": "blue",
        },
        "elements": [
            {"tag": "markdown", "content": "评审进行中... 织布鸟、猫头鹰、渡鸦、鸬鹚正在并行评审 PRD"},
            {"tag": "note", "elements": [{"tag": "plain_text", "content": "预计 1-2 分钟完成"}]},
        ],
    }


def _build_result_card(items, prd_name, peck_score, workspace=""):
    """构建评审结果交互式卡片"""
    must_items = [i for i in items if i.get("severity") == "must"]
    should_items = [i for i in items if i.get("severity") == "should"]

    elements = [
        {"tag": "markdown", "content": (
            f"**啄伤度**: {peck_score.get('score', 0) if isinstance(peck_score, dict) else peck_score}/100\n"
            f"**改进项**: {len(items)} 条 (must: {len(must_items)}, should: {len(should_items)})"
        )},
        {"tag": "hr"},
    ]

    # 展示 must 项（带按钮）
    for item in must_items[:10]:
        item_id = item.get("id", "?")
        issue = item.get("issue", "")[:80]
        location = item.get("location", "")

        elements.append({
            "tag": "markdown",
            "content": f"**{item_id}** [必须] {location}\n{issue}",
        })
        elements.append({
            "tag": "action",
            "actions": [
                {
                    "tag": "button",
                    "text": {"tag": "plain_text", "content": "确认"},
                    "type": "primary",
                    "value": {"item_id": item_id, "decision": "confirm", "prd": prd_name, "workspace": workspace},
                },
                {
                    "tag": "button",
                    "text": {"tag": "plain_text", "content": "驳回"},
                    "type": "danger",
                    "value": {"item_id": item_id, "decision": "reject", "prd": prd_name, "workspace": workspace},
                },
            ],
        })

    # should 项折叠显示
    if should_items:
        should_text = "\n".join(
            f"- **{i.get('id', '?')}** {i.get('location', '')}: {i.get('issue', '')[:60]}"
            for i in should_items[:10]
        )
        elements.append({"tag": "markdown", "content": f"**建议项 ({len(should_items)} 条)**\n{should_text}"})

    return {
        "header": {
            "title": {"tag": "plain_text", "content": f"啄木鸟评审完成: {prd_name}"},
            "template": "green" if len(must_items) == 0 else "orange" if len(must_items) < 5 else "red",
        },
        "elements": elements,
    }


def _save_decision(workspace, prd_name, item_id, decision):
    """保存飞书卡片的决策"""
    if not workspace:
        return
    decisions_dir = os.path.join(workspace, "output", ".feishu_decisions")
    os.makedirs(decisions_dir, exist_ok=True)
    fpath = os.path.join(decisions_dir, f"{prd_name}.json")

    existing = {}
    if os.path.exists(fpath):
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                existing = json.load(f)
        except (json.JSONDecodeError, OSError):
            pass

    existing[item_id] = {
        "decision": decision,
        "timestamp": datetime.now().isoformat(),
    }

    with open(fpath, "w", encoding="utf-8") as f:
        json.dump(existing, f, ensure_ascii=False, indent=2)


# FastAPI 应用实例（uvicorn 直接引用）
app = create_app() if FastAPI else None