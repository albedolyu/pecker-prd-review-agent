from __future__ import annotations

from pathlib import Path
from statistics import quantiles
from typing import Any

import yaml

from pecker.models import ChannelCandidate, ChannelScore


def load_channel_config(path: str | Path) -> list[ChannelCandidate]:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    return [ChannelCandidate(**item) for item in raw.get("channels", [])]


def evaluate_channels(
    candidates: list[ChannelCandidate],
    *,
    dry_run: bool = True,
) -> list[ChannelScore]:
    scores: list[ChannelScore] = []
    for index, candidate in enumerate(candidates):
        if dry_run:
            success_rate = 1.0
            latencies = [600 + index * 30, 680 + index * 30, 720 + index * 30]
            cost = 0.001 + index * 0.0002
        else:
            success_rate = 0.0
            latencies = [0.0]
            cost = 0.0
        p95 = _p95(latencies)
        scores.append(
            ChannelScore(
                name=candidate.name,
                provider=candidate.provider,
                model=candidate.model,
                base_url=candidate.base_url,
                success_rate=success_rate,
                p95_latency_ms=p95,
                cost_per_run_usd=cost,
                passed_gate=success_rate >= 0.95 and p95 <= 1500,
            )
        )
    return scores


def rank_channels(scores: list[ChannelScore]) -> list[dict[str, Any]]:
    rows = [score.model_dump() for score in scores]
    return sorted(rows, key=lambda row: (-row["success_rate"], row["p95_latency_ms"], row["cost_per_run_usd"]))


def _p95(values: list[float]) -> float:
    if len(values) < 2:
        return float(values[0] if values else 0.0)
    return float(quantiles(values, n=20, method="inclusive")[18])
