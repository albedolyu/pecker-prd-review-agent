"""
飞书 API 客户端 -- token 获取、文件下载、卡片发送/更新
用 httpx（anthropic SDK 已带，无需新增依赖）
"""

import os
import time
import httpx

from logger import get_logger

log = get_logger("feishu")

FEISHU_API_BASE = "https://open.feishu.cn/open-apis"


class FeishuClient:
    """飞书 Open Platform API 封装"""

    def __init__(self, app_id=None, app_secret=None):
        self.app_id = app_id or os.environ.get("FEISHU_APP_ID", "")
        self.app_secret = app_secret or os.environ.get("FEISHU_APP_SECRET", "")
        self._token = ""
        self._token_expires = 0
        self.http = httpx.Client(timeout=30)

    def _get_token(self):
        """获取 tenant_access_token（2 小时有效，自动续期）"""
        if self._token and time.time() < self._token_expires - 60:
            return self._token

        resp = self.http.post(
            f"{FEISHU_API_BASE}/auth/v3/tenant_access_token/internal",
            json={"app_id": self.app_id, "app_secret": self.app_secret},
        )
        data = resp.json()
        if data.get("code") != 0:
            raise RuntimeError(f"飞书认证失败: {data.get('msg', 'unknown')}")

        self._token = data["tenant_access_token"]
        self._token_expires = time.time() + data.get("expire", 7200)
        return self._token

    def _headers(self):
        return {"Authorization": f"Bearer {self._get_token()}"}

    def download_file(self, message_id, file_key):
        """下载消息中的文件附件"""
        resp = self.http.get(
            f"{FEISHU_API_BASE}/im/v1/messages/{message_id}/resources/{file_key}",
            headers=self._headers(),
            params={"type": "file"},
        )
        if resp.status_code != 200:
            raise RuntimeError(f"文件下载失败: {resp.status_code}")
        return resp.content

    def send_card(self, chat_id, card_json):
        """发送交互式卡片消息，返回 message_id"""
        resp = self.http.post(
            f"{FEISHU_API_BASE}/im/v1/messages",
            headers=self._headers(),
            params={"receive_id_type": "chat_id"},
            json={
                "receive_id": chat_id,
                "msg_type": "interactive",
                "content": card_json if isinstance(card_json, str) else __import__("json").dumps(card_json, ensure_ascii=False),
            },
        )
        data = resp.json()
        if data.get("code") != 0:
            log.warning(f"发送卡片失败: {data.get('msg', '')}")
            return None
        return data.get("data", {}).get("message_id")

    def update_card(self, message_id, card_json):
        """更新已发送的卡片"""
        resp = self.http.patch(
            f"{FEISHU_API_BASE}/im/v1/messages/{message_id}",
            headers=self._headers(),
            json={
                "msg_type": "interactive",
                "content": card_json if isinstance(card_json, str) else __import__("json").dumps(card_json, ensure_ascii=False),
            },
        )
        return resp.json().get("code") == 0

    def reply_text(self, message_id, text):
        """回复文本消息"""
        import json
        resp = self.http.post(
            f"{FEISHU_API_BASE}/im/v1/messages/{message_id}/reply",
            headers=self._headers(),
            json={
                "msg_type": "text",
                "content": json.dumps({"text": text}, ensure_ascii=False),
            },
        )
        return resp.json().get("code") == 0

    def get_message_file_list(self, message_id):
        """获取消息中的文件列表"""
        resp = self.http.get(
            f"{FEISHU_API_BASE}/im/v1/messages/{message_id}",
            headers=self._headers(),
        )
        data = resp.json()
        if data.get("code") != 0:
            return []
        items = data.get("data", {}).get("items", [])
        if not items:
            return []
        msg_body = items[0].get("body", {})
        import json
        content = json.loads(msg_body.get("content", "{}"))
        # 提取文件 key
        files = []
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("tag") == "file":
                    files.append({"file_key": block.get("file_key", ""), "file_name": block.get("file_name", "")})
        return files
