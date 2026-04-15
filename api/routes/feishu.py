"""POST /api/feishu/send — 推送评审报告到飞书群,复用 feishu_client.FeishuClient"""
from __future__ import annotations

import os

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.deps import require_writer

router = APIRouter(tags=["feishu"])


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
