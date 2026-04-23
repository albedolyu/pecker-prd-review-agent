"""预算卡 — 按天累计评审成本,超 PECKER_DAILY_BUDGET_USD 拒绝新评审。

设计:
- 文件 `logs/daily_cost_YYYY-MM-DD.jsonl`: 每行 {"ts": <unix>, "cost_usd": <float>, "reviewer": <str>}
- append-only,无需锁,扫描当天文件求和即可
- 评审前 check_budget(estimated=DEFAULT_ESTIMATED_USD),超 budget 直接 429
- 评审后 record_review_cost() append 实际成本
- 0=off(默认),> 0 启用预算卡

并发竞态: 单实例 + 评审时长 90-150s, 并发撞预算的概率低, MVP 不加锁;
真需要严格限额时改成 redis INCR 或 fcntl.lockf,留 TODO。
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, Tuple

from fastapi import HTTPException, status


DEFAULT_ESTIMATED_USD = 2.5  # 单次评审平均成本,用于预扣判定
DEFAULT_WARN_PCT = 0.8


def _budget_limit() -> float:
    try:
        return float(os.environ.get("PECKER_DAILY_BUDGET_USD", "0") or 0)
    except ValueError:
        return 0.0


def _warn_pct() -> float:
    try:
        return float(os.environ.get("PECKER_BUDGET_WARN_PCT", str(DEFAULT_WARN_PCT)) or DEFAULT_WARN_PCT)
    except ValueError:
        return DEFAULT_WARN_PCT


def _cost_log_path(project_root: Path, date_str: str) -> Path:
    """logs/daily_cost_YYYY-MM-DD.jsonl"""
    return project_root / "logs" / f"daily_cost_{date_str}.jsonl"


def _today_str() -> str:
    # 用本地时区,按自然日切分
    return datetime.now().strftime("%Y-%m-%d")


def compute_today_spend(project_root: Path) -> Tuple[float, int]:
    """扫当天 jsonl 求和。返回 (total_usd, review_count)。"""
    path = _cost_log_path(project_root, _today_str())
    if not path.is_file():
        return 0.0, 0
    total = 0.0
    count = 0
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                    total += float(row.get("cost_usd", 0) or 0)
                    count += 1
                except (json.JSONDecodeError, ValueError, TypeError):
                    continue
    except OSError:
        return 0.0, 0
    return total, count


def check_budget(project_root: Path, estimated_usd: float = DEFAULT_ESTIMATED_USD) -> Dict[str, float]:
    """评审前调用。超 budget 抛 429; 否则返回进度信息(可附带到响应/SSE)。

    返回: {limit, spent, estimated_next, remaining, warn: bool}
    当 limit=0 (未启用) 时仍返回 dict,limit/remaining 为 0 标识 off。
    """
    limit = _budget_limit()
    spent, count = compute_today_spend(project_root)

    if limit <= 0:
        return {
            "limit": 0.0,
            "spent": round(spent, 6),
            "estimated_next": round(estimated_usd, 6),
            "remaining": 0.0,
            "warn": False,
            "enabled": False,
            "today_count": count,
        }

    projected = spent + estimated_usd
    if projected > limit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                f"今日预算已用尽:已消耗 ${spent:.2f} USD / 限额 ${limit:.2f} USD,"
                f"预估新评审还需 ${estimated_usd:.2f}。请明日再试或联系管理员调高 PECKER_DAILY_BUDGET_USD。"
            ),
        )

    remaining = limit - spent
    warn = spent >= limit * _warn_pct()
    return {
        "limit": round(limit, 6),
        "spent": round(spent, 6),
        "estimated_next": round(estimated_usd, 6),
        "remaining": round(remaining, 6),
        "warn": warn,
        "enabled": True,
        "today_count": count,
    }


def budget_status_snapshot(project_root: Path) -> Dict[str, float]:
    """纯查询当前预算状态,不抛异常。用于响应/SSE event 带出,给前端/运维显示。"""
    limit = _budget_limit()
    spent, count = compute_today_spend(project_root)
    enabled = limit > 0
    remaining = max(0.0, limit - spent) if enabled else 0.0
    warn = enabled and spent >= limit * _warn_pct()
    return {
        "enabled": enabled,
        "limit": round(limit, 6),
        "spent": round(spent, 6),
        "remaining": round(remaining, 6),
        "warn": warn,
        "today_count": count,
    }


def record_review_cost(project_root: Path, cost_usd: float, reviewer: str = "") -> None:
    """评审完成后 append 实际成本。失败不阻塞(log warn 即可)。"""
    path = _cost_log_path(project_root, _today_str())
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "ts": int(time.time()),
        "cost_usd": round(float(cost_usd or 0), 6),
        "reviewer": (reviewer or "")[:40],
    }
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    except OSError:
        pass  # 日志失败不阻塞主流程
