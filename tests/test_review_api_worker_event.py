"""API review worker_done event payload tests."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_build_worker_done_event_payload_includes_wiki_selection_summary():
    from api.routes.review import _build_worker_done_event_payload

    payload = _build_worker_done_event_payload(
        "data_quality",
        {
            "items": [{"id": "R-001"}],
            "telemetry": {
                "duration_ms": 1234,
                "input_tokens": 100,
                "output_tokens": 50,
                "wiki_selection": {
                    "selected_count": 3,
                    "omitted_count": 7,
                    "total_chars_before": 12000,
                    "total_chars_after": 2800,
                    "pages": [{"title": "字段映射规范", "mode": "full"}],
                },
            },
        },
    )

    assert payload["dim"] == "data_quality"
    assert payload["items_count"] == 1
    assert payload["wiki_selection"] == {
        "selected_count": 3,
        "omitted_count": 7,
        "total_chars_before": 12000,
        "total_chars_after": 2800,
    }
