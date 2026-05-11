from __future__ import annotations

import json

import pytest


def _prd_fixture() -> str:
    anchors = [f"PRD-LEAK-ANCHOR-{idx:02d}" for idx in range(10)]
    paragraphs = [
        f"第 {idx} 段业务规则包含 {anchors[idx % len(anchors)]}，用于验证正文泄漏契约。"
        + "字段口径、验收流程、异常处理、数据范围、导出策略需要保持一致。"
        for idx in range(80)
    ]
    text = "\n".join(paragraphs)
    assert len(text) >= 4000
    return text


def _assert_no_prd_leak(payload: object, prd_text: str) -> None:
    serialized = json.dumps(payload, ensure_ascii=False)
    assert prd_text not in serialized
    for anchor in [f"PRD-LEAK-ANCHOR-{idx:02d}" for idx in range(10)]:
        assert anchor not in serialized
    prefix = prd_text[:2000]
    for start in range(0, len(prefix) - 200 + 1, 37):
        assert prefix[start : start + 200] not in serialized


def test_redact_prd_content_recursively_removes_body_slices_and_anchors():
    from api.sanitize import redact_prd_content

    prd_text = _prd_fixture()
    payload = {
        "prd_content": prd_text,
        "metadata": {
            "preview": prd_text[180:520],
            "events": [{"message": f"模型失败上下文: {prd_text[700:980]}"}],
        },
        "safe": "workspace-alpha",
    }

    redacted = redact_prd_content(payload, prd_text)

    _assert_no_prd_leak(redacted, prd_text)
    serialized = json.dumps(redacted, ensure_ascii=False)
    assert "<prd-redacted len=" in serialized
    assert redacted["safe"] == "workspace-alpha"


def test_event_store_redacts_prd_body_contract_before_jsonl_write(tmp_path):
    from event_store import EventStore

    prd_text = _prd_fixture()
    store = EventStore(workspace=str(tmp_path), review_id="rev_contract")

    store.append(
        "review_started",
        {
            "prd_content": prd_text,
            "worker_debug": {
                "prompt_excerpt": prd_text[240:620],
                "status": "failed",
            },
        },
    )

    rows = [
        json.loads(line)
        for line in store.path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert rows
    _assert_no_prd_leak(rows[0], prd_text)


def test_sse_emitter_redacts_prd_body_contract_before_queue_write():
    from api.stream import ReviewProgressEmitter

    prd_text = _prd_fixture()
    emitter = ReviewProgressEmitter()

    emitter.emit(
        "workers_started",
        data={
            "mode": "standard",
            "prd_content": prd_text,
            "debug": {"prompt_excerpt": prd_text[300:760]},
        },
    )

    payload = emitter.queue.get_nowait()
    _assert_no_prd_leak(payload, prd_text)


def test_finding_outcomes_truncates_and_redacts_evidence_content(tmp_path):
    import sqlite3

    from review.finding_outcomes_store import init_store, record_outcome

    prd_text = _prd_fixture()
    db_path = str(tmp_path / "finding_outcomes.db")
    init_store(db_path)

    record_outcome(
        finding_id="R-001",
        outcome="reject",
        rule_id="V-06",
        evidence_content=prd_text[120:900],
        prd_body=prd_text,
        db_path=db_path,
    )

    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT evidence_content FROM finding_outcomes ORDER BY id DESC LIMIT 1"
        ).fetchone()

    assert row is not None
    assert len(row[0]) <= 500
    _assert_no_prd_leak({"evidence_content": row[0]}, prd_text)


@pytest.mark.asyncio
async def test_drafts_get_for_non_admin_hides_raw_prd_sidecar_fields(tmp_path):
    from api.routes.drafts import get_draft

    prd_text = _prd_fixture()
    draft_dir = tmp_path / ".pecker_drafts"
    draft_dir.mkdir(parents=True)
    (draft_dir / "contract-pm_draft.json").write_text(
        json.dumps(
            {
                "ts": "2026-05-11T10:00:00",
                "reviewer": "contract-pm",
                "phase": 3,
                "prd_name": "demo.md",
                "supplemental_materials_raw": prd_text,
                "prd_body": prd_text,
                "review_result": {"items": []},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    draft = await get_draft(
        "contract-pm",
        project_root=tmp_path,
        user={"reviewer": "contract-pm", "role": "reviewer"},
    )

    assert "supplemental_materials_raw" not in draft
    assert "prd_body" not in draft
    _assert_no_prd_leak(draft, prd_text)


def test_usage_summary_keeps_prd_name_but_shortens_preview(tmp_path):
    from datetime import datetime

    from api.usage_summary import build_usage_summary

    prd_text = _prd_fixture()
    session_dir = tmp_path / "workspace-alpha" / "output" / "sessions"
    session_dir.mkdir(parents=True)
    (session_dir / "run-001.jsonl").write_text(
        "\n".join(
            json.dumps(row, ensure_ascii=False)
            for row in [
                {
                    "type": "review_started",
                    "ts": "2026-05-11T09:00:00",
                    "reviewer": "pm-a",
                    "mode": "standard",
                    "prd_name": "真实 PRD.md",
                    "prd_preview": prd_text[:300],
                    "prd_content": prd_text,
                },
                {
                    "type": "review_completed",
                    "ts": "2026-05-11T09:10:00",
                    "items_count": 3,
                    "duration_ms": 600000,
                },
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    summary = build_usage_summary(
        tmp_path,
        days=7,
        now=datetime(2026, 5, 11, 12, 0, 0),
    )

    recent = summary["recent_runs"][0]
    assert recent["prd_name"] == "真实 PRD.md"
    assert recent["prd_preview"].endswith("...")
    assert len(recent["prd_preview"]) <= 80
    _assert_no_prd_leak(summary, prd_text)


@pytest.mark.asyncio
async def test_review_job_get_non_owner_returns_404():
    from fastapi import HTTPException

    from api.review_jobs import ReviewJobStore

    store = ReviewJobStore()

    async def runner(_job):
        return {"review_id": "rev_1", "items": []}

    job = store.create_job(
        owner="pm-a",
        workspace="workspace-alpha",
        prd_name="demo.md",
        mode="standard",
        runner=runner,
    )
    await job.wait()

    with pytest.raises(HTTPException) as exc:
        store.get_job(job.job_id, owner="pm-b", admin=False)

    assert exc.value.status_code == 404


def test_eval_report_prd_source_must_be_path_reference(tmp_path):
    from scripts.check_redaction_contract import find_inline_prd_sources

    prd_text = _prd_fixture()
    report_dir = tmp_path / "eval_reports"
    report_dir.mkdir()
    (report_dir / "bad.json").write_text(
        json.dumps({"prd_source": prd_text}, ensure_ascii=False),
        encoding="utf-8",
    )
    (report_dir / "ok.json").write_text(
        json.dumps({"prd_source": "workspace-alpha/prd/demo.md"}, ensure_ascii=False),
        encoding="utf-8",
    )

    leaks = find_inline_prd_sources(tmp_path)

    assert leaks == [str(report_dir / "bad.json")]


def test_redaction_contract_checker_warns_on_new_public_exit_without_contract(tmp_path):
    from scripts.check_redaction_contract import find_unreviewed_public_exit_calls

    source = tmp_path / "feature.py"
    source.write_text(
        "\n".join(
            [
                "def unsafe(emitter, payload):",
                "    emitter.emit('result', data=payload)",
                "",
                "def safe(emitter, payload):",
                "    # contract: NoPRDBody",
                "    emitter.emit('result', data=payload)",
            ]
        ),
        encoding="utf-8",
    )

    warnings = find_unreviewed_public_exit_calls([source])

    assert warnings == [f"{source}:2: emitter.emit('result', data=payload)"]


@pytest.mark.asyncio
async def test_review_job_response_redacts_nested_prd_body_for_owner():
    from api.review_jobs import ReviewJobStore

    prd_text = _prd_fixture()
    store = ReviewJobStore()

    async def runner(job):
        job.emit(
            "worker_done",
            {
                "prd_body": prd_text,
                "debug": {"prompt_excerpt": prd_text[400:820]},
            },
        )
        return {
            "review_id": "rev_1",
            "prd_content": prd_text,
            "items": [{"problem": prd_text[900:1260]}],
        }

    job = store.create_job(
        owner="pm-a",
        workspace="workspace-alpha",
        prd_name="demo.md",
        mode="standard",
        runner=runner,
    )
    await job.wait()

    snapshot = store.get_job(job.job_id, owner="pm-a", admin=False)

    _assert_no_prd_leak(snapshot, prd_text)


def test_feedback_summary_redacts_prd_fragments_from_draft_items(tmp_path):
    from datetime import datetime

    from api.feedback_summary import build_feedback_summary

    prd_text = _prd_fixture()
    draft_dir = tmp_path / ".pecker_drafts"
    draft_dir.mkdir(parents=True)
    (draft_dir / "pm-a_draft.json").write_text(
        json.dumps(
            {
                "ts": "2026-05-11T10:00:00",
                "reviewer": "pm-a",
                "workspace": "workspace-alpha",
                "prd_name": "demo.md",
                "prd_content": prd_text,
                "review_result": {
                    "items": [
                        {
                            "id": "R-001",
                            "rule_id": "V-06",
                            "problem": prd_text[1000:1360],
                            "suggestion": prd_text[1400:1760],
                        }
                    ]
                },
                "item_decisions": {"R-001": {"action": "reject"}},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    summary = build_feedback_summary(
        tmp_path,
        days=7,
        now=datetime(2026, 5, 11, 12, 0, 0),
    )

    _assert_no_prd_leak(summary, prd_text)
