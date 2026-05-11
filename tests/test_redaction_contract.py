from __future__ import annotations

import json


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
