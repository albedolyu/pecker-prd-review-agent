from __future__ import annotations

import hashlib
import json


def test_langfuse_smoke_check_validates_auth_prompts_and_score_api_without_writing(monkeypatch):
    from scripts.langfuse_smoke_check import run_langfuse_smoke_check

    calls: list[dict] = []

    class FakePrompt:
        version = 8
        is_fallback = False
        prompt = "managed prompt"

        def compile(self, **_kwargs):
            return "managed prompt"

    class FakeLangfuse:
        def auth_check(self):
            calls.append({"auth_check": True})
            return True

        def get_prompt(self, name, **kwargs):
            calls.append({"get_prompt": name, "kwargs": kwargs})
            return FakePrompt()

        def create_score(self, **kwargs):
            calls.append({"create_score": kwargs})

    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test-secret")
    monkeypatch.setenv("PECKER_LANGFUSE_ENABLED", "1")
    monkeypatch.setenv("PECKER_LANGFUSE_PROMPTS_ENABLED", "1")
    monkeypatch.setenv("PECKER_LANGFUSE_PROMPT_LABEL", "production")

    result = run_langfuse_smoke_check(
        dim_keys=["structure"],
        client_factory=lambda: FakeLangfuse(),
        sdk_available=True,
    )

    assert result["ok"] is True
    assert result["configured"] is True
    assert result["auth"]["status"] == "ready"
    assert result["prompts"]["status"] == "ready"
    assert result["prompts"]["checked"] == [{
        "name": "pecker.worker.structure.system",
        "status": "ready",
        "label": "production",
        "version": 8,
        "hash": hashlib.sha256("managed prompt".encode()).hexdigest()[:12],
        "source": "langfuse",
    }]
    assert result["score_api"]["status"] == "ready"
    assert not any("create_score" in call for call in calls)
    assert "sk-test-secret" not in json.dumps(result, ensure_ascii=False)


def test_langfuse_smoke_check_reports_missing_credentials_without_client_call(monkeypatch):
    from scripts.langfuse_smoke_check import run_langfuse_smoke_check

    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    monkeypatch.setenv("PECKER_LANGFUSE_ENABLED", "1")

    result = run_langfuse_smoke_check(
        dim_keys=["structure"],
        client_factory=lambda: (_ for _ in ()).throw(AssertionError("must not call client")),
        sdk_available=True,
    )

    assert result["ok"] is False
    assert result["configured"] is False
    assert result["auth"]["status"] == "missing_credentials"
    assert result["prompts"]["status"] == "skipped"
    assert result["score_api"]["status"] == "skipped"


def test_langfuse_smoke_check_can_write_explicit_smoke_score(monkeypatch):
    from scripts.langfuse_smoke_check import run_langfuse_smoke_check

    calls: list[dict] = []

    class FakePrompt:
        version = 9
        prompt = "managed prompt"

    class FakeLangfuse:
        def auth_check(self):
            return True

        def create_trace_id(self, *, seed=None):
            calls.append({"create_trace_id": seed})
            return "abc123abc123abc123abc123abc123ab"

        def get_trace_url(self, *, trace_id=None):
            calls.append({"get_trace_url": trace_id})
            return f"https://langfuse.example/project/proj/traces/{trace_id}"

        def get_prompt(self, *_args, **_kwargs):
            return FakePrompt()

        def create_score(self, **kwargs):
            calls.append(kwargs)

        def flush(self):
            calls.append({"flush": True})

    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test-secret")
    monkeypatch.setenv("PECKER_LANGFUSE_ENABLED", "1")
    monkeypatch.setenv("PECKER_LANGFUSE_PROMPTS_ENABLED", "1")

    result = run_langfuse_smoke_check(
        dim_keys=["structure"],
        client_factory=lambda: FakeLangfuse(),
        sdk_available=True,
        write_score=True,
    )

    assert result["ok"] is True
    assert result["score_api"]["status"] == "written"
    assert result["score_api"]["trace_id"] == "abc123abc123abc123abc123abc123ab"
    assert result["score_api"]["trace_linked"] is True
    assert result["score_api"]["trace_url"].endswith("/abc123abc123abc123abc123abc123ab")
    score_call = next(call for call in calls if call.get("name") == "pecker.smoke.score_api")
    assert {"create_trace_id": "pecker-langfuse-smoke"} in calls
    assert {"get_trace_url": "abc123abc123abc123abc123abc123ab"} in calls
    assert "session_id" not in score_call
    assert score_call["trace_id"] == "abc123abc123abc123abc123abc123ab"
    assert calls[-1] == {"flush": True}
