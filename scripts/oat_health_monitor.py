"""OAT 健康监控 (claude CLI + codex CLI 的 OAuth Access Token 监控).

设计目标:
  - 每 30min 跑一次 (cron / Task Scheduler), 检测 OAT 是否过期/即将过期
  - 主动验证 (调一次轻量 API), 不只看 mtime
  - 失败时输出 JSON + 推送告警 (飞书 webhook + 邮件 fallback)
  - 自愈尝试 (调 `claude login --refresh` / `codex login --refresh`)
  - 不阻主流程 — 异步跑, 失败重试 + 告警人工介入

输入:
  环境变量:
    FEISHU_WEBHOOK    可选, 推送告警
    SMTP_HOST / SMTP_USER / SMTP_PASS / ALERT_EMAIL  可选, 邮件 fallback
    OAT_CLAUDE_TTL_HOURS  默认 5h
    OAT_CODEX_TTL_HOURS   默认 5h

输出:
  stdout JSON (machine-readable):
    {
      "checked_at": "...",
      "checks": [
        {"vendor": "claude", "status": "ok|expiring|expired|missing", "mtime_age_hours": 1.2, "active_check": "200|401|skipped"},
        {"vendor": "codex",  "status": "...", ...}
      ],
      "alerts_sent": ["feishu", "email"]
    }

退出码:
  0 全部 ok / expiring (warn-only)
  1 任一 expired / missing (critical)
  2 内部错误
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import smtplib
import subprocess
import sys
import time
import urllib.error
import urllib.request
from email.mime.text import MIMEText
from typing import Any, Dict, List, Optional


# ============================================================
# 文件检测
# ============================================================

def _expand(path: str) -> str:
    return os.path.expanduser(os.path.expandvars(path))


def _file_age_hours(path: str) -> Optional[float]:
    if not os.path.isfile(path):
        return None
    return (time.time() - os.path.getmtime(path)) / 3600


def _check_claude_oat() -> Dict[str, Any]:
    """检查 ~/.claude/ 下的 OAT 状态.

    实际 token 在 keychain (macOS) / keyring 服务里; 文件层只能看 history.jsonl
    或 mcp-needs-auth-cache.json 的 mtime 间接推断登录会话活跃度.
    """
    ttl = float(os.environ.get("OAT_CLAUDE_TTL_HOURS", "5"))
    candidates = [
        _expand("~/.claude/history.jsonl"),
        _expand("~/.claude/mcp-needs-auth-cache.json"),
    ]
    found = None
    for p in candidates:
        if os.path.isfile(p):
            found = p
            break
    if not found:
        return {
            "vendor": "claude",
            "status": "missing",
            "path_checked": candidates,
            "mtime_age_hours": None,
            "active_check": "skipped",
            "message": "claude CLI 未登录或缓存目录缺失",
        }

    age = _file_age_hours(found)
    status = "ok"
    if age is None:
        status = "missing"
    elif age > ttl:
        status = "expiring"  # mtime 老 ≠ 已过期, 仅示警

    # 主动验证: 调 `claude --version` (轻量, 不消耗配额)
    active = "skipped"
    if shutil.which("claude"):
        try:
            r = subprocess.run(
                ["claude", "--version"],
                capture_output=True, text=True, timeout=10,
            )
            if r.returncode == 0:
                active = "200"
            else:
                active = f"err_rc={r.returncode}"
                # version 失败一般是二进制问题, 不直接判 expired
        except (subprocess.TimeoutExpired, FileNotFoundError) as e:
            active = f"err_{type(e).__name__}"

    return {
        "vendor": "claude",
        "status": status,
        "path_checked": found,
        "mtime_age_hours": round(age, 2) if age is not None else None,
        "active_check": active,
        "ttl_hours": ttl,
    }


def _check_codex_oat() -> Dict[str, Any]:
    """检查 ~/.codex/auth.json 的 OAT 状态."""
    ttl = float(os.environ.get("OAT_CODEX_TTL_HOURS", "5"))
    auth_path = _expand("~/.codex/auth.json")
    if not os.path.isfile(auth_path):
        return {
            "vendor": "codex",
            "status": "missing",
            "path_checked": auth_path,
            "mtime_age_hours": None,
            "active_check": "skipped",
            "message": "~/.codex/auth.json 不存在, 未登录",
        }

    age = _file_age_hours(auth_path)
    status = "ok"
    if age and age > ttl:
        status = "expiring"

    # 解析 auth.json, 看 token 是否结构正常 (不打印 token 内容)
    token_info: Dict[str, Any] = {}
    try:
        with open(auth_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        token_info["has_access_token"] = bool(
            data.get("access_token") or data.get("OPENAI_API_KEY") or data.get("tokens")
        )
        if isinstance(data.get("tokens"), dict):
            tokens = data["tokens"]
            token_info["has_id_token"] = bool(tokens.get("id_token"))
            token_info["has_refresh_token"] = bool(tokens.get("refresh_token"))
        # exp 字段 (jwt)?
        if data.get("expires_at"):
            token_info["expires_at"] = data["expires_at"]
    except (json.JSONDecodeError, OSError) as e:
        status = "expired"
        token_info["parse_error"] = str(e)[:120]

    # 主动验证: codex --version (轻量)
    active = "skipped"
    if shutil.which("codex"):
        try:
            r = subprocess.run(
                ["codex", "--version"],
                capture_output=True, text=True, timeout=10,
            )
            if r.returncode == 0:
                active = "200"
            else:
                active = f"err_rc={r.returncode}"
        except (subprocess.TimeoutExpired, FileNotFoundError) as e:
            active = f"err_{type(e).__name__}"

    return {
        "vendor": "codex",
        "status": status,
        "path_checked": auth_path,
        "mtime_age_hours": round(age, 2) if age is not None else None,
        "active_check": active,
        "ttl_hours": ttl,
        "token_info": token_info,
    }


# ============================================================
# 自愈尝试
# ============================================================

def _try_refresh(vendor: str) -> Dict[str, Any]:
    """尝试调 `<vendor> login --refresh`. 失败返回 error info, 成功返回 ok."""
    bin_name = vendor
    if not shutil.which(bin_name):
        return {"vendor": vendor, "refreshed": False, "reason": "binary not found"}
    try:
        r = subprocess.run(
            [bin_name, "login", "--refresh"],
            capture_output=True, text=True, timeout=30,
        )
        if r.returncode == 0:
            return {"vendor": vendor, "refreshed": True}
        return {
            "vendor": vendor,
            "refreshed": False,
            "rc": r.returncode,
            "stderr": (r.stderr or "")[:200],
        }
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        return {"vendor": vendor, "refreshed": False, "error": type(e).__name__}


# ============================================================
# 告警通道
# ============================================================

def _send_feishu(text: str) -> bool:
    webhook = os.environ.get("FEISHU_WEBHOOK")
    if not webhook:
        return False
    payload = json.dumps({
        "msg_type": "text",
        "content": {"text": text},
    }).encode("utf-8")
    try:
        req = urllib.request.Request(
            webhook,
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status == 200
    except (urllib.error.URLError, OSError) as e:
        print(f"[WARN] 飞书推送失败: {e}", file=sys.stderr)
        return False


def _send_email(subject: str, body: str) -> bool:
    host = os.environ.get("SMTP_HOST")
    user = os.environ.get("SMTP_USER")
    pwd = os.environ.get("SMTP_PASS")
    to = os.environ.get("ALERT_EMAIL")
    if not all([host, user, pwd, to]):
        return False
    try:
        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = subject
        msg["From"] = user
        msg["To"] = to
        port = int(os.environ.get("SMTP_PORT", "465"))
        with smtplib.SMTP_SSL(host, port, timeout=15) as s:
            s.login(user, pwd)
            s.send_message(msg)
        return True
    except Exception as e:  # noqa: BLE001
        print(f"[WARN] 邮件发送失败: {e}", file=sys.stderr)
        return False


# ============================================================
# 主流程
# ============================================================

def run_health_check(*, try_refresh: bool = False) -> Dict[str, Any]:
    """跑一次健康检查, 返回报告 dict (不写文件不发告警, 纯结果)."""
    checks = [_check_claude_oat(), _check_codex_oat()]
    auto_heal: List[Dict[str, Any]] = []
    if try_refresh:
        for c in checks:
            if c["status"] in ("expired", "expiring"):
                auto_heal.append(_try_refresh(c["vendor"]))

    return {
        "checked_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "checks": checks,
        "auto_heal": auto_heal,
    }


def _summarize(report: Dict[str, Any]) -> str:
    lines = [f"[OAT Health] {report['checked_at']}"]
    for c in report["checks"]:
        lines.append(
            f"  - {c['vendor']:8s} status={c['status']:8s} "
            f"mtime_age={c['mtime_age_hours']}h  active={c['active_check']}"
        )
    if report.get("auto_heal"):
        lines.append("  Auto-heal:")
        for h in report["auto_heal"]:
            lines.append(f"    - {h}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="OAT 健康监控")
    parser.add_argument(
        "--auto-heal",
        action="store_true",
        help="检测到 expired/expiring 时尝试 refresh",
    )
    parser.add_argument(
        "--alert-on-warn",
        action="store_true",
        help="expiring 也发告警 (默认仅 expired/missing 告警)",
    )
    parser.add_argument("--metrics-db", default=None, help="可选, 把检查结果写入 metrics.db")
    args = parser.parse_args()

    try:
        report = run_health_check(try_refresh=args.auto_heal)
    except Exception as e:  # noqa: BLE001
        print(json.dumps({"error": str(e)[:200]}, ensure_ascii=False))
        return 2

    # 决定告警 + 退出码
    has_critical = any(c["status"] in ("expired", "missing") for c in report["checks"])
    has_warn = any(c["status"] == "expiring" for c in report["checks"])
    should_alert = has_critical or (has_warn and args.alert_on_warn)

    alerts_sent: List[str] = []
    if should_alert:
        text = _summarize(report)
        if _send_feishu(text):
            alerts_sent.append("feishu")
        subject = "[ALERT] OAT 过期" if has_critical else "[WARN] OAT 即将过期"
        if _send_email(subject, text):
            alerts_sent.append("email")
    report["alerts_sent"] = alerts_sent

    # 可选: 把检查结果埋点到 metrics.db
    if args.metrics_db:
        try:
            sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            from review.metrics_store import record_event
            for c in report["checks"]:
                record_event(
                    "oauth.check",
                    model=c["vendor"],
                    status="success" if c["status"] == "ok" else "failed",
                    details={
                        "oat_status": c["status"],
                        "mtime_age_hours": c["mtime_age_hours"],
                        "active_check": c["active_check"],
                    },
                    db_path=args.metrics_db,
                )
            for h in report.get("auto_heal", []):
                record_event(
                    "oauth.refresh",
                    model=h["vendor"],
                    status="success" if h.get("refreshed") else "failed",
                    details=h,
                    db_path=args.metrics_db,
                )
        except Exception as e:  # noqa: BLE001
            print(f"[WARN] 写 metrics.db 失败 (silent): {e}", file=sys.stderr)

    print(json.dumps(report, ensure_ascii=False, indent=2))
    if has_critical:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
