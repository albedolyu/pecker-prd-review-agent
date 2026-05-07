from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_startup_accepts_openai_native_routes_with_openai_key(monkeypatch):
    import api.main as main

    monkeypatch.delenv("USE_CLAUDE_CODE", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    errors, warnings, auth = main._validate_llm_runtime()

    assert errors == []
    assert auth["status"] == "ok"
    assert "openai:native" in auth["active_routes"]


def test_startup_accepts_legacy_api_key_alias_for_team_openai(monkeypatch):
    import api.main as main

    monkeypatch.delenv("USE_CLAUDE_CODE", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("API_KEY", "test-key")

    errors, warnings, auth = main._validate_llm_runtime()

    assert errors == []
    assert auth["status"] == "ok"
    assert "openai:native" in auth["active_routes"]
