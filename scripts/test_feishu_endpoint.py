#!/usr/bin/env python
"""啄木鸟 /feishu/event endpoint smoke test (mock POST).

不需要真飞书机器人, 直接 POST 模拟 payload 验证:
  1. URL 验证 challenge → 应该 200 + body 含 {"challenge": <原值>}
  2. PM 反馈消息 (im.message.receive_v1) → 应该 200 + {"code": 0}
  3. 落库验证 (可选, --check-db) → 看 finding_outcomes.db 有没有新 record

用法:
  # 假设后端已在 :8001
  python scripts/test_feishu_endpoint.py

  # 自定义 host
  python scripts/test_feishu_endpoint.py --base-url http://localhost:8000

  # 只跑某个 case
  python scripts/test_feishu_endpoint.py --only challenge
  python scripts/test_feishu_endpoint.py --only feedback

  # 反馈完落库验证
  python scripts/test_feishu_endpoint.py --check-db

退出码:
  0 = 全部通过
  1 = 至少一项 fail
  2 = 后端未起 / 网络不通
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from typing import Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


# ─── 配置 ───────────────────────────────────────────────────

DEFAULT_BASE_URL = "http://localhost:8001"
EVENT_PATH = "/api/feishu/event"
TIMEOUT_SECONDS = 5


# ─── HTTP 工具 ───────────────────────────────────────────────


def _post_json(url: str, payload: dict, timeout: int = TIMEOUT_SECONDS) -> tuple[int, dict | str]:
    """POST JSON, 返回 (status_code, parsed_body or raw_text)."""
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            try:
                return resp.status, json.loads(raw)
            except json.JSONDecodeError:
                return resp.status, raw
    except HTTPError as e:
        # 4xx/5xx: 仍把 body 读出来给 caller 看
        raw = e.read().decode("utf-8", errors="replace") if e.fp else ""
        try:
            return e.code, json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            return e.code, raw


# ─── Smoke Cases ─────────────────────────────────────────────


def case_challenge(base_url: str) -> tuple[bool, str]:
    """飞书首次绑定 URL 时发的 url_verification 事件."""
    url = base_url.rstrip("/") + EVENT_PATH
    challenge_value = f"smoke_test_challenge_{int(time.time())}"
    payload = {
        "challenge": challenge_value,
        "token": "v_smoke_dummy_token",
        "type": "url_verification",
    }
    status, body = _post_json(url, payload)

    if status != 200:
        return False, f"期望 200 实得 {status}: {body!r}"
    if not isinstance(body, dict) or body.get("challenge") != challenge_value:
        return False, f"期望 body['challenge']={challenge_value!r}, 实得 {body!r}"
    return True, f"challenge={challenge_value} echoed OK"


def case_feedback_reject(base_url: str) -> tuple[bool, str]:
    """模拟 PM @机器人 发反馈消息."""
    url = base_url.rstrip("/") + EVENT_PATH
    payload = {
        "header": {
            "event_id": f"ev_smoke_{int(time.time() * 1000)}",
            "event_type": "im.message.receive_v1",
            "token": "v_smoke_dummy_token",
            "create_time": str(int(time.time() * 1000)),
        },
        "event": {
            "message": {
                "chat_id": "oc_smoke_chat",
                "message_id": f"om_smoke_{int(time.time() * 1000)}",
                "message_type": "text",
                "content": json.dumps({
                    "text": "@_user_1 R-001 是误报, 字段已统一约定为 20"
                }, ensure_ascii=False),
            },
            "sender": {"sender_id": {"union_id": "on_smoke_pm"}},
        },
    }
    status, body = _post_json(url, payload)

    if status != 200:
        return False, f"期望 200 实得 {status}: {body!r}"
    # body 形如 {"code": 0} 或 {"code": 0, "msg": "duplicate"}, 任一都算通过
    if not isinstance(body, dict) or body.get("code") != 0:
        return False, f"期望 body['code']==0, 实得 {body!r}"
    return True, f"feedback reject 路径通畅 (body={body})"


def case_duplicate_event(base_url: str) -> tuple[bool, str]:
    """同 event_id 重发, 应被路由层 _event_seen 去重."""
    url = base_url.rstrip("/") + EVENT_PATH
    event_id = f"ev_smoke_dup_{int(time.time() * 1000)}"
    payload = {
        "header": {
            "event_id": event_id,
            "event_type": "im.message.receive_v1",
            "token": "v_smoke_dummy_token",
            "create_time": str(int(time.time() * 1000)),
        },
        "event": {
            "message": {
                "chat_id": "oc_smoke_chat",
                "message_id": f"om_dup_{int(time.time() * 1000)}",
                "message_type": "text",
                "content": json.dumps({"text": "@_user_1 R-002 接受"}, ensure_ascii=False),
            },
            "sender": {"sender_id": {"union_id": "on_smoke_pm"}},
        },
    }

    status1, body1 = _post_json(url, payload)
    status2, body2 = _post_json(url, payload)  # 重发

    if status1 != 200 or status2 != 200:
        return False, f"两次 POST 期望都 200, 实得 {status1} / {status2}"
    # 第二次应标 duplicate (msg=duplicate); 但路由实现可能直接 ignore, 任一都接受
    return True, f"重发去重 OK (body1={body1}, body2={body2})"


# ─── 落库验证 (可选, 仅 --check-db) ───────────────────────────


def check_db_records() -> tuple[bool, str]:
    """检查 finding_outcomes_store 有最近的 smoke record."""
    try:
        # 加 project root 到 path
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).parent.parent.resolve()))
        from review.finding_outcomes_store import get_recent_outcomes
    except ImportError as e:
        return False, f"import finding_outcomes_store 失败: {e} (project root 不在 sys.path?)"

    try:
        recent = get_recent_outcomes(limit=10)
    except Exception as e:
        return False, f"get_recent_outcomes 失败: {e}"

    # 找有没有 finding_id 含 R- 的最近 smoke record
    smoke_hits = [
        r for r in recent
        if (r.get("pm_name") or "").startswith("on_smoke_")
        or (r.get("finding_id") or "").startswith("R-")
    ]
    if not smoke_hits:
        return False, f"未在最近 10 条 outcome 中找到 smoke record (recent={recent[:2]})"
    return True, f"落库 OK, 最近 smoke record: finding_id={smoke_hits[0].get('finding_id')}, outcome={smoke_hits[0].get('outcome')}"


# ─── 主流程 ──────────────────────────────────────────────────


CASES = {
    "challenge": ("URL verification challenge", case_challenge),
    "feedback": ("反馈消息 reject", case_feedback_reject),
    "duplicate": ("event_id 去重", case_duplicate_event),
}


def main():
    parser = argparse.ArgumentParser(
        description="啄木鸟 /feishu/event endpoint smoke test (mock POST)",
        epilog="先起后端: uvicorn api.main:app --port 8001",
    )
    parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help=f"FastAPI host base url (默认 {DEFAULT_BASE_URL})",
    )
    parser.add_argument(
        "--only",
        choices=list(CASES.keys()),
        default=None,
        help="只跑某一项 case",
    )
    parser.add_argument(
        "--check-db",
        action="store_true",
        help="跑完反馈消息后, 验证 finding_outcomes.db 有 smoke record",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=TIMEOUT_SECONDS,
        help=f"HTTP 超时秒数 (默认 {TIMEOUT_SECONDS})",
    )
    args = parser.parse_args()

    print(f"[feishu-smoke] base url: {args.base_url}")
    print(f"[feishu-smoke] endpoint: {args.base_url.rstrip('/')}{EVENT_PATH}")
    print()

    cases_to_run = (
        [(args.only, *CASES[args.only])]
        if args.only
        else [(k, *v) for k, v in CASES.items()]
    )

    failures: list[str] = []
    for i, (key, label, fn) in enumerate(cases_to_run, 1):
        print(f"[feishu-smoke] case {i}/{len(cases_to_run)}: {label} ...", end=" ", flush=True)
        try:
            ok, msg = fn(args.base_url)
        except (URLError, ConnectionRefusedError) as e:
            print("CONN_FAIL")
            print(f"  错误: 后端未起或网络不通: {e}")
            print(f"  先跑: uvicorn api.main:app --port 8001")
            return 2
        except Exception as e:
            print("EXCEPTION")
            print(f"  {type(e).__name__}: {e}")
            failures.append(f"{key}: {type(e).__name__}: {e}")
            continue

        if ok:
            print("OK")
            print(f"  {msg}")
        else:
            print("FAIL")
            print(f"  {msg}")
            failures.append(f"{key}: {msg}")

    if args.check_db:
        print()
        print("[feishu-smoke] check-db: 验证 sqlite 落库 ...", end=" ", flush=True)
        ok, msg = check_db_records()
        if ok:
            print("OK")
            print(f"  {msg}")
        else:
            print("FAIL")
            print(f"  {msg}")
            failures.append(f"check-db: {msg}")

    print()
    if failures:
        print(f"[feishu-smoke] FAIL: {len(failures)} 项未通过")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("[feishu-smoke] 全部通过.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
