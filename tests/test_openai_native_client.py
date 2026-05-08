from __future__ import annotations

import os
import types
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class _FakeChatCompletions:
    def __init__(self):
        self.last_kwargs = None

    def create(self, **kwargs):
        self.last_kwargs = kwargs
        tool_call = SimpleNamespace(
            id="call_1",
            function=SimpleNamespace(
                name="submit_review_items",
                arguments='{"dimension":"质量鸟","items":[]}',
            ),
        )
        message = SimpleNamespace(content=None, tool_calls=[tool_call])
        usage = SimpleNamespace(
            prompt_tokens=12,
            completion_tokens=5,
            total_tokens=17,
        )
        return SimpleNamespace(
            choices=[SimpleNamespace(message=message, finish_reason="tool_calls")],
            usage=usage,
        )


class _FakeOpenAI:
    def __init__(self):
        self.chat = SimpleNamespace(completions=_FakeChatCompletions())


def test_openai_native_client_maps_function_tool_calls(monkeypatch):
    from clients.openai_native import OpenAINativeClient

    fake_client = _FakeOpenAI()
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_WIRE_API", "chat_completions")
    monkeypatch.delenv("OPENAI_REASONING_EFFORT", raising=False)
    monkeypatch.delenv("OPENAI_DISABLE_RESPONSE_STORAGE", raising=False)
    monkeypatch.setattr(
        OpenAINativeClient,
        "_build_client",
        lambda self, api_key, base_url: fake_client,
    )

    client = OpenAINativeClient()
    resp = client.create(
        model="gpt-5.4",
        max_tokens=256,
        system="system",
        messages=[{"role": "user", "content": "hello"}],
        tools=[
            {
                "name": "submit_review_items",
                "description": "submit",
                "input_schema": {
                    "type": "object",
                    "properties": {"dimension": {"type": "string"}, "items": {"type": "array"}},
                },
            }
        ],
        tool_choice={"type": "any"},
    )

    assert resp.tool_calls[0]["name"] == "submit_review_items"
    assert resp.tool_calls[0]["input"]["dimension"] == "质量鸟"
    assert resp.usage["input_tokens"] == 12
    assert fake_client.chat.completions.last_kwargs["tool_choice"]["type"] == "function"


class _FakeResponses:
    def __init__(self):
        self.last_kwargs = None

    def create(self, **kwargs):
        self.last_kwargs = kwargs
        function_call = SimpleNamespace(
            type="function_call",
            id="fc_1",
            call_id="call_1",
            name="submit_review_items",
            arguments='{"dimension":"质量鸟","items":[]}',
        )
        usage = SimpleNamespace(input_tokens=13, output_tokens=6)
        return SimpleNamespace(
            output=[function_call],
            output_text="",
            usage=usage,
            model=kwargs["model"],
            status="completed",
        )


class _FakeResponsesOpenAI:
    def __init__(self):
        self.responses = _FakeResponses()


def test_openai_native_client_supports_responses_wire(monkeypatch):
    from clients.openai_native import OpenAINativeClient

    fake_client = _FakeResponsesOpenAI()
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_WIRE_API", "responses")
    monkeypatch.setenv("OPENAI_REASONING_EFFORT", "xhigh")
    monkeypatch.setenv("OPENAI_DISABLE_RESPONSE_STORAGE", "true")
    monkeypatch.setattr(
        OpenAINativeClient,
        "_build_client",
        lambda self, api_key, base_url: fake_client,
    )

    client = OpenAINativeClient(base_url="https://pikachu.claudecode.love")
    resp = client.create(
        model="gpt-5.5",
        max_tokens=256,
        system="system",
        messages=[{"role": "user", "content": "hello"}],
        tools=[
            {
                "name": "submit_review_items",
                "description": "submit",
                "input_schema": {
                    "type": "object",
                    "properties": {"dimension": {"type": "string"}, "items": {"type": "array"}},
                },
            }
        ],
        tool_choice={"type": "any"},
    )

    assert resp.tool_calls[0]["name"] == "submit_review_items"
    assert resp.tool_calls[0]["input"]["dimension"] == "质量鸟"
    assert resp.usage["input_tokens"] == 13
    assert isinstance(fake_client.responses.last_kwargs["input"], str)
    assert "hello" in fake_client.responses.last_kwargs["input"]
    assert fake_client.responses.last_kwargs["store"] is False
    assert fake_client.responses.last_kwargs["reasoning"] == {"effort": "xhigh"}
    assert fake_client.responses.last_kwargs["tool_choice"]["type"] == "function"


def test_openai_native_client_requires_api_key(monkeypatch):
    from clients.openai_native import OpenAINativeClient

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("API_KEY", raising=False)

    try:
        OpenAINativeClient()
    except RuntimeError as exc:
        assert "OPENAI_API_KEY/API_KEY" in str(exc)
    else:
        raise AssertionError("expected missing OPENAI_API_KEY to fail")


def test_openai_native_client_accepts_legacy_api_key_alias(monkeypatch):
    from clients.openai_native import OpenAINativeClient

    fake_client = _FakeOpenAI()
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("API_KEY", "test-key")
    monkeypatch.setattr(
        OpenAINativeClient,
        "_build_client",
        lambda self, api_key, base_url: fake_client,
    )

    client = OpenAINativeClient()

    assert client.client is fake_client


def test_openai_native_client_sets_request_timeout_and_uses_own_retries(monkeypatch):
    from clients.openai_native import OpenAINativeClient

    captured = {}

    class FakeOpenAI:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setitem(sys.modules, "openai", types.SimpleNamespace(OpenAI=FakeOpenAI))
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_REQUEST_TIMEOUT", "45")

    OpenAINativeClient(base_url="https://pikachu.claudecode.love")

    assert captured["api_key"] == "test-key"
    assert captured["base_url"] == "https://pikachu.claudecode.love"
    assert captured["timeout"] == 45.0
    assert captured["max_retries"] == 0


def test_openai_native_client_default_timeout_covers_deep_review_workers(monkeypatch):
    from clients.openai_native import OpenAINativeClient

    captured = {}

    class FakeOpenAI:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setitem(sys.modules, "openai", types.SimpleNamespace(OpenAI=FakeOpenAI))
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.delenv("OPENAI_REQUEST_TIMEOUT", raising=False)

    OpenAINativeClient()

    assert captured["timeout"] >= 360.0
    assert captured["max_retries"] == 0


def test_openai_native_client_can_override_worker_retry_count(monkeypatch):
    from clients.openai_native import OpenAINativeClient

    class FailingResponses:
        def __init__(self):
            self.calls = 0

        def create(self, **_kwargs):
            self.calls += 1
            raise TimeoutError("gateway timed out")

    fake_responses = FailingResponses()
    fake_client = types.SimpleNamespace(responses=fake_responses)

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_WIRE_API", "responses")
    monkeypatch.setenv("OPENAI_WORKER_MAX_RETRIES", "0")
    monkeypatch.delenv("OPENAI_REASONING_EFFORT", raising=False)
    monkeypatch.setattr(
        OpenAINativeClient,
        "_build_client",
        lambda self, api_key, base_url: fake_client,
    )

    client = OpenAINativeClient()
    try:
        client.create(
            model="gpt-5.5",
            max_tokens=8,
            system="system",
            messages=[{"role": "user", "content": "hello"}],
            retry_policy="worker",
        )
    except TimeoutError:
        pass
    else:
        raise AssertionError("expected request to fail")

    assert fake_responses.calls == 1
