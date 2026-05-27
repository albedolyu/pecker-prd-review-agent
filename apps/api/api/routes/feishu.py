"""飞书路由: /api/feishu/send (推送报告) + /api/feishu/event (PM 反馈回调).

设计:
  - /send: 主动推送评审报告卡片到群 (require_writer)
  - /event: 被动接收飞书事件回调 (challenge URL 验证 + im.message.receive_v1
    PM @机器人反馈), 复用 feishu_bot._handle_message + _try_parse_feedback,
    最终落库到 review/learnings_store.db (信鸽 v2)

事件路径:
  飞书开放平台 → POST /api/feishu/event → 异步交给 feishu_bot._handle_message_safe
  → 若是反馈则 _try_parse_feedback 抽 finding_id + outcome → record_outcome 写
  finding_outcomes_store + 累计达到 reject 阈值时反哺 learning_store.

部署见 docs/feishu_integration.md.
"""
from __future__ import annotations

import asyncio
import os

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from api.deps import require_writer
from logger import get_logger

log = get_logger("api.feishu")

router = APIRouter(tags=["feishu"])

# 事件去重 cache (飞书会重发); _processed_events 由 feishu_bot 模块共享
_event_seen: set[str] = set()
_MAX_SEEN = 1000


class FeishuSendRequest(BaseModel):
    prd_name: str
    report_markdown: str = Field(..., max_length=100_000)
    chat_id: str = ""  # 空时从 env 读 FEISHU_REPORT_CHAT_ID


@router.post("/feishu/send")
async def send_to_feishu(req: FeishuSendRequest, user: dict = Depends(require_writer)):
    """把评审报告推送到飞书群。只读用户 403。

    需要 env var: FEISHU_APP_ID / FEISHU_APP_SECRET / FEISHU_REPORT_CHAT_ID
    """
    app_id = os.environ.get("FEISHU_APP_ID", "")
    app_secret = os.environ.get("FEISHU_APP_SECRET", "")
    chat_id = req.chat_id or os.environ.get("FEISHU_REPORT_CHAT_ID", "")

    if not (app_id and app_secret and chat_id):
        raise HTTPException(
            status_code=503,
            detail="飞书未配置 (FEISHU_APP_ID / FEISHU_APP_SECRET / FEISHU_REPORT_CHAT_ID)",
        )

    try:
        from feishu_client import FeishuClient
        client = FeishuClient(app_id=app_id, app_secret=app_secret)

        snippet = req.report_markdown[:3500]
        if len(req.report_markdown) > 3500:
            snippet += "\n\n...(报告已截断)"

        card = {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": f"🪶 PRD 评审报告 - {req.prd_name}"},
                "template": "blue",
            },
            "elements": [
                {"tag": "div", "text": {"tag": "lark_md", "content": f"**评审人**: {user['reviewer']}"}},
                {"tag": "hr"},
                {"tag": "div", "text": {"tag": "lark_md", "content": snippet}},
            ],
        }
        msg_id = client.send_card(chat_id, card)
        if not msg_id:
            raise HTTPException(status_code=500, detail="飞书 send_card 返回空")
        return {"status": "ok", "msg_id": msg_id}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"推送失败: {str(e)[:200]}")


# ============================================================
# /feishu/event — 飞书事件回调 (PM @机器人 反馈入口)
# ============================================================


@router.post("/feishu/event")
async def feishu_event(request: Request):
    """飞书事件回调.

    支持事件类型:
      1. URL 验证 (challenge): 飞书后台首次配置 URL 时发的 challenge ping
      2. im.message.receive_v1: PM 在群里 @机器人 发消息 (反馈或评审)

    无鉴权 (飞书没有标准 PR 流程, 用 verify_token + 频次限速兜底; 本 endpoint
    应该走 cloudflare tunnel 或反代加防护). 本路由刻意不依赖 require_writer,
    因为飞书后台不会带 cookie.

    部署: 在飞书开发者后台填回调 URL = https://<your-host>/api/feishu/event
    """
    try:
        body = await request.json()
    except Exception as e:
        log.warning(f"解析 body 失败: {e}")
        raise HTTPException(status_code=400, detail="invalid json")

    # 1. URL 验证 (challenge)
    if isinstance(body, dict) and "challenge" in body:
        log.info(f"飞书 URL 验证 challenge={body.get('challenge', '')[:8]}...")
        return {"challenge": body["challenge"]}

    # 2. verify_token 校验 (可选 — 设了 FEISHU_VERIFY_TOKEN 才校验)
    expected_token = os.environ.get("FEISHU_VERIFY_TOKEN", "")
    if expected_token:
        got_token = body.get("token") or body.get("header", {}).get("token", "")
        if got_token != expected_token:
            log.warning(f"verify_token 不匹配, 拒绝事件")
            raise HTTPException(status_code=401, detail="verify_token mismatch")

    # 3. 事件去重
    header = body.get("header", {}) if isinstance(body, dict) else {}
    event_id = header.get("event_id", "")
    if event_id and event_id in _event_seen:
        return {"code": 0, "msg": "duplicate"}
    if event_id:
        _event_seen.add(event_id)
        if len(_event_seen) > _MAX_SEEN:
            _event_seen.clear()

    # 4. 分发
    event_type = header.get("event_type", "")
    if event_type == "im.message.receive_v1":
        event = body.get("event", {})
        # 复用 feishu_bot 的 _handle_message_safe 异步处理
        try:
            from feishu_bot import _handle_message_safe
            asyncio.create_task(_handle_message_safe(event))
        except Exception as e:
            log.error(f"消息处理 dispatch 失败: {str(e)[:120]}")
            # 仍返回 0 给飞书, 避免它重发把 _event_seen 清掉后再炸一次
    else:
        log.debug(f"忽略事件类型: {event_type}")

    return {"code": 0}
