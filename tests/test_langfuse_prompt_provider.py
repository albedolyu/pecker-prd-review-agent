from __future__ import annotations

import types


class FakeTextPrompt:
    def __init__(self, template: str, *, version: int = 7, is_fallback: bool = False):
        self.template = template
        self.version = version
        self.is_fallback = is_fallback

    def compile(self, **variables):
        text = self.template
        for key, value in variables.items():
            text = text.replace("{{" + key + "}}", str(value))
        return text


def test_resolve_text_prompt_fetches_langfuse_prompt(monkeypatch):
    from review.langfuse_prompt_provider import resolve_text_prompt

    calls: list[dict] = []

    class FakeLangfuse:
        def get_prompt(self, name, **kwargs):
            calls.append({"name": name, "kwargs": kwargs})
            return FakeTextPrompt("Remote {{dimension_name}} prompt.")

    monkeypatch.setenv("PECKER_LANGFUSE_PROMPTS_ENABLED", "1")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test-secret")
    monkeypatch.setenv("PECKER_LANGFUSE_PROMPT_LABEL", "canary")

    resolved = resolve_text_prompt(
        "pecker.worker.structure.system",
        fallback_text="Local prompt",
        variables={"dimension_name": "Structure"},
        client_factory=lambda: FakeLangfuse(),
    )

    assert resolved.text == "Remote Structure prompt."
    assert calls[0]["name"] == "pecker.worker.structure.system"
    assert calls[0]["kwargs"]["label"] == "canary"
    assert calls[0]["kwargs"]["fallback"] == "Local prompt"
    assert resolved.metadata["source"] == "langfuse"
    assert resolved.metadata["status"] == "ready"
    assert resolved.metadata["version"] == 7
    assert "sk-test-secret" not in repr(resolved.metadata)


def test_resolve_text_prompt_falls_back_without_leaking_secret(monkeypatch):
    from review.langfuse_prompt_provider import resolve_text_prompt

    monkeypatch.setenv("PECKER_LANGFUSE_PROMPTS_ENABLED", "1")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test-secret")

    resolved = resolve_text_prompt(
        "pecker.worker.structure.system",
        fallback_text="Local prompt",
        variables={"dimension_name": "Structure"},
        client_factory=lambda: (_ for _ in ()).throw(RuntimeError("boom sk-test-secret")),
    )

    assert resolved.text == "Local prompt"
    assert resolved.metadata["source"] == "local_fallback"
    assert resolved.metadata["status"] == "error"
    assert "sk-test-secret" not in resolved.metadata["error"]


def test_worker_core_attaches_langfuse_prompt_metadata(monkeypatch):
    from review import langfuse_prompt_provider as provider
    from review.worker import _worker_core

    class FakeLangfuse:
        def get_prompt(self, *_args, **_kwargs):
            return FakeTextPrompt("Remote worker {{codename}} / {{dimension_name}}.")

    class FakeClient:
        def create(self, **_kwargs):
            return types.SimpleNamespace(
                content=[
                    types.SimpleNamespace(
                        type="tool_use",
                        name="submit_review_items",
                        input={
                            "dimension": "业务完整性",
                            "items": [],
                            "null_finding_reason": "已核查 V-02、V-03、V-04，均未发现 fail。",
                        },
                    )
                ],
                usage={
                    "input_tokens": 10,
                    "output_tokens": 5,
                    "cache_read_input_tokens": 0,
                    "cache_creation_input_tokens": 0,
                },
            )

    monkeypatch.setenv("PECKER_LANGFUSE_PROMPTS_ENABLED", "1")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test-secret")
    monkeypatch.setattr(provider, "_default_langfuse_client_factory", lambda: FakeLangfuse())

    result = _worker_core(
        FakeClient(),
        "structure",
        "# PRD\ncontent",
        {},
        {"sonnet": "test-sonnet"},
    )

    assert result["telemetry"]["prompt"]["name"] == "pecker.worker.structure.system"
    assert result["telemetry"]["prompt"]["source"] == "langfuse"
    assert result["telemetry"]["prompt"]["status"] == "ready"
    assert result["telemetry"]["prompt"]["version"] == 7
    assert "sk-test-secret" not in repr(result["telemetry"]["prompt"])
