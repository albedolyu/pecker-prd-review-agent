"""Budget gate for review cost control.

Costs are stored in append-only daily JSONL files under ``logs/``.  The gate is
called before a review starts, so it must fail clearly and cheaply before any
LLM call burns money.
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Tuple

from fastapi import HTTPException, status


DEFAULT_ESTIMATED_USD = 2.5
DEFAULT_WARN_PCT = 0.8


def _env_float(name: str, default: float = 0.0) -> float:
    try:
        return float(os.environ.get(name, str(default)) or default)
    except ValueError:
        return default


def _budget_limit() -> float:
    return _env_float("PECKER_DAILY_BUDGET_USD")


def _review_hard_cap() -> float:
    return _env_float("PECKER_REVIEW_HARD_CAP_USD")


def _reviewer_daily_limit() -> float:
    return _env_float("PECKER_REVIEWER_DAILY_BUDGET_USD")


def _monthly_budget_limit() -> float:
    return _env_float("PECKER_MONTHLY_BUDGET_USD")


def _warn_pct() -> float:
    return _env_float("PECKER_BUDGET_WARN_PCT", DEFAULT_WARN_PCT)


def _cost_log_path(project_root: Path, date_str: str) -> Path:
    return project_root / "logs" / f"daily_cost_{date_str}.jsonl"


def _today_str() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _month_prefix() -> str:
    return datetime.now().strftime("%Y-%m")


def _sum_cost_file(path: Path, reviewer: str = "") -> Tuple[float, int]:
    if not path.is_file():
        return 0.0, 0

    reviewer = (reviewer or "").strip()
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
                    row_reviewer = str(row.get("reviewer", "") or "").strip()
                    if reviewer and row_reviewer != reviewer:
                        continue
                    total += float(row.get("cost_usd", 0) or 0)
                    count += 1
                except (json.JSONDecodeError, ValueError, TypeError):
                    continue
    except OSError:
        return 0.0, 0
    return total, count


def compute_today_spend(project_root: Path, reviewer: str = "") -> Tuple[float, int]:
    """Return ``(total_usd, review_count)`` for today."""
    return _sum_cost_file(_cost_log_path(project_root, _today_str()), reviewer=reviewer)


def compute_month_spend(project_root: Path, reviewer: str = "") -> Tuple[float, int]:
    """Return ``(total_usd, review_count)`` for the current month."""
    logs_dir = project_root / "logs"
    if not logs_dir.is_dir():
        return 0.0, 0

    total = 0.0
    count = 0
    for path in logs_dir.glob(f"daily_cost_{_month_prefix()}-*.jsonl"):
        subtotal, subcount = _sum_cost_file(path, reviewer=reviewer)
        total += subtotal
        count += subcount
    return total, count


def _raise_429(detail: str) -> None:
    raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=detail)


def check_budget(
    project_root: Path,
    estimated_usd: float = DEFAULT_ESTIMATED_USD,
    reviewer: str = "",
) -> Dict[str, object]:
    """Check per-review, per-reviewer/day, project/day, and project/month caps."""
    limit = _budget_limit()
    hard_cap = _review_hard_cap()
    reviewer_limit = _reviewer_daily_limit()
    monthly_limit = _monthly_budget_limit()

    spent, count = compute_today_spend(project_root)
    reviewer_spent, reviewer_count = compute_today_spend(project_root, reviewer=reviewer)
    month_spent, month_count = compute_month_spend(project_root)

    if hard_cap > 0 and estimated_usd > hard_cap:
        _raise_429(
            f"单次评审额度不足: 本次预估 ${estimated_usd:.2f} USD, "
            f"单次上限 ${hard_cap:.2f} USD。请拆小 PRD 或联系管理员调整额度。"
        )

    if reviewer and reviewer_limit > 0 and reviewer_spent + estimated_usd > reviewer_limit:
        _raise_429(
            f"个人今日额度已用完: 已消耗 ${reviewer_spent:.2f} USD / "
            f"个人日限额 ${reviewer_limit:.2f} USD。请明日再试或联系管理员。"
        )

    if monthly_limit > 0 and month_spent + estimated_usd > monthly_limit:
        _raise_429(
            f"项目月度额度已用完: 本月已消耗 ${month_spent:.2f} USD / "
            f"月度限额 ${monthly_limit:.2f} USD。请联系管理员。"
        )

    if limit > 0 and spent + estimated_usd > limit:
        _raise_429(
            f"今日预算已用完: 已消耗 ${spent:.2f} USD / 限额 ${limit:.2f} USD, "
            f"预估新评审还需 ${estimated_usd:.2f} USD。请明日再试或联系管理员。"
        )

    enabled = limit > 0
    remaining = max(0.0, limit - spent) if enabled else 0.0
    warn = enabled and spent >= limit * _warn_pct()
    return {
        "limit": round(limit, 6),
        "spent": round(spent, 6),
        "estimated_next": round(estimated_usd, 6),
        "remaining": round(remaining, 6),
        "warn": warn,
        "enabled": enabled,
        "today_count": count,
        "reviewer_daily": {
            "enabled": reviewer_limit > 0,
            "limit": round(reviewer_limit, 6),
            "spent": round(reviewer_spent, 6),
            "today_count": reviewer_count,
        },
        "monthly": {
            "enabled": monthly_limit > 0,
            "limit": round(monthly_limit, 6),
            "spent": round(month_spent, 6),
            "month_count": month_count,
        },
    }


def budget_status_snapshot(project_root: Path) -> Dict[str, object]:
    """Read-only budget snapshot for SSE and operations UI."""
    limit = _budget_limit()
    reviewer_limit = _reviewer_daily_limit()
    monthly_limit = _monthly_budget_limit()
    spent, count = compute_today_spend(project_root)
    month_spent, month_count = compute_month_spend(project_root)
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
        "reviewer_daily": {
            "enabled": reviewer_limit > 0,
            "limit": round(reviewer_limit, 6),
        },
        "monthly": {
            "enabled": monthly_limit > 0,
            "limit": round(monthly_limit, 6),
            "spent": round(month_spent, 6),
            "month_count": month_count,
        },
    }


def record_review_cost(project_root: Path, cost_usd: float, reviewer: str = "") -> None:
    """Append actual review cost. Logging failure must not block the main flow."""
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
        pass
