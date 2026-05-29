from __future__ import annotations


def test_goshawk_user_message_keeps_full_wiki_by_default(monkeypatch):
    from goshawk_advisor import _build_advisor_user_message

    monkeypatch.delenv("PECKER_GOSHAWK_COMPACT_WIKI", raising=False)
    wiki_pages = {
        "api/field-contract": "field mapping DDL source_table " + ("A" * 120),
        "marketing/campaign": "campaign calendar coupon banner " + ("B" * 120),
    }

    message = _build_advisor_user_message(
        "PRD mentions field mapping and DDL.",
        [],
        wiki_pages,
    )

    assert "### api/field-contract" in message
    assert "### marketing/campaign" in message


def test_goshawk_user_message_compacts_wiki_when_flag_enabled(monkeypatch):
    from goshawk_advisor import _build_advisor_user_message

    monkeypatch.setenv("PECKER_GOSHAWK_COMPACT_WIKI", "1")
    monkeypatch.setenv("PECKER_GOSHAWK_WIKI_CHARS", "180")
    wiki_pages = {
        "api/field-contract": "field mapping DDL source_table source_column " + ("A" * 120),
        "modules/company-search": "company logo upload pic entid unique_id " + ("B" * 80),
        "marketing/campaign": "campaign calendar coupon banner " + ("C" * 180),
    }
    worker_results = [
        {
            "id": "R-001",
            "rule_id": "RC-009",
            "dimension": "data_quality",
            "location": "storage DDL",
            "issue": "pic field mapping is missing",
            "suggestion": "add source_table and source_column mapping",
            "severity": "must",
            "evidence_content": "RC-009 requires field mapping and DDL clarity.",
        }
    ]

    message = _build_advisor_user_message(
        "PRD describes company logo upload with DDL, pic, entid and field mapping.",
        worker_results,
        wiki_pages,
    )

    assert "### api/field-contract" in message
    assert "### marketing/campaign" not in message


def test_env_example_documents_default_off_goshawk_compact_flag():
    from pathlib import Path

    env = Path(".env.example").read_text(encoding="utf-8")

    assert "PECKER_GOSHAWK_COMPACT_WIKI=0" in env
    assert "PECKER_GOSHAWK_WIKI_CHARS=25000" in env


def test_goshawk_prompt_guards_compact_wiki_output_stability():
    from goshawk_advisor import GOSHAWK_SYSTEM_PROMPT

    assert "不得把 compact wiki 的信息缺口当作漏报" in GOSHAWK_SYSTEM_PROMPT
    assert "不得因为压缩摘要缺少细节就误合并" in GOSHAWK_SYSTEM_PROMPT
    assert "输出稳定性优先于节省 token" in GOSHAWK_SYSTEM_PROMPT
    assert "误报标记默认不超过总数 30%" in GOSHAWK_SYSTEM_PROMPT
    assert "只挑证据最明确的少数项" in GOSHAWK_SYSTEM_PROMPT
