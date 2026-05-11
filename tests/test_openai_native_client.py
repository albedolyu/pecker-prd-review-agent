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
    monkeypatch.setenv("PECKER_OPENAI_STRICT_STRUCTURED_OUTPUT", "0")
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


def test_openai_native_client_uses_strict_chat_json_schema_for_structured_tool(monkeypatch):
    from clients.openai_native import OpenAINativeClient

    fake_client = _FakeOpenAI()
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_WIRE_API", "chat_completions")
    monkeypatch.delenv("OPENAI_REASONING_EFFORT", raising=False)
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
                    "properties": {
                        "dimension": {"type": "string"},
                        "items": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "rule_id": {"type": "string"},
                                    "issue": {"type": "string"},
                                },
                            },
                        },
                    },
                },
            }
        ],
        tool_choice={"type": "any"},
    )

    kwargs = fake_client.chat.completions.last_kwargs
    assert resp.usage["strict_structured_output"] is True
    assert "tools" not in kwargs
    assert "tool_choice" not in kwargs
    schema_format = kwargs["response_format"]["json_schema"]
    assert schema_format["name"] == "submit_review_items"
    assert schema_format["strict"] is True
    assert schema_format["schema"]["additionalProperties"] is False
    assert set(schema_format["schema"]["required"]) == {"dimension", "items"}
    item_schema = schema_format["schema"]["properties"]["items"]["items"]
    assert item_schema["additionalProperties"] is False
    assert set(item_schema["required"]) == {"rule_id", "issue"}


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


class _SuccessfulResponses:
    def __init__(self, api_key: str, calls: list[str]):
        self.api_key = api_key
        self.calls = calls

    def create(self, **kwargs):
        self.calls.append(self.api_key)
        usage = SimpleNamespace(input_tokens=1, output_tokens=1)
        return SimpleNamespace(
            output=[],
            output_text="ok",
            usage=usage,
            model=kwargs["model"],
            status="completed",
        )


def test_openai_native_client_spreads_calls_across_key_pool(monkeypatch):
    from clients.openai_native import OpenAINativeClient

    calls: list[str] = []

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("API_KEY", raising=False)
    monkeypatch.delenv("PECKER_OPENAI_API_KEYS", raising=False)
    monkeypatch.setenv("OPENAI_API_KEYS", "key-a,key-b")
    monkeypatch.setenv("OPENAI_WIRE_API", "responses")
    monkeypatch.delenv("OPENAI_REASONING_EFFORT", raising=False)
    monkeypatch.setattr(
        OpenAINativeClient,
        "_build_client",
        lambda self, api_key, base_url: types.SimpleNamespace(
            responses=_SuccessfulResponses(api_key, calls)
        ),
    )

    client = OpenAINativeClient()
    for _ in range(2):
        client.create(
            model="gpt-5.5",
            max_tokens=8,
            system="system",
            messages=[{"role": "user", "content": "hello"}],
            retry_policy="router",
        )

    assert calls == ["key-a", "key-b"]


class _Gateway524Error(Exception):
    status_code = 524


class _GatewayFlakyResponses:
    def __init__(self, api_key: str, calls: list[str]):
        self.api_key = api_key
        self.calls = calls

    def create(self, **kwargs):
        self.calls.append(self.api_key)
        if self.api_key == "key-a":
            raise _Gateway524Error("Error code: 524")
        usage = SimpleNamespace(input_tokens=1, output_tokens=1)
        return SimpleNamespace(
            output=[],
            output_text="ok",
            usage=usage,
            model=kwargs["model"],
            status="completed",
        )


def test_openai_native_client_retries_transient_524_on_next_key(monkeypatch):
    from clients.openai_native import OpenAINativeClient

    calls: list[str] = []

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("API_KEY", raising=False)
    monkeypatch.delenv("PECKER_OPENAI_API_KEYS", raising=False)
    monkeypatch.setenv("OPENAI_API_KEYS", "key-a,key-b")
    monkeypatch.setenv("OPENAI_WIRE_API", "responses")
    monkeypatch.setenv("OPENAI_WORKER_MAX_RETRIES", "1")
    monkeypatch.delenv("OPENAI_REASONING_EFFORT", raising=False)
    monkeypatch.setattr("clients.openai_native.time.sleep", lambda _seconds: None)
    monkeypatch.setattr(
        OpenAINativeClient,
        "_build_client",
        lambda self, api_key, base_url: types.SimpleNamespace(
            responses=_GatewayFlakyResponses(api_key, calls)
        ),
    )

    client = OpenAINativeClient()
    resp = client.create(
        model="gpt-5.5",
        max_tokens=8,
        system="system",
        messages=[{"role": "user", "content": "hello"}],
        retry_policy="worker",
    )

    assert resp.content[0].text == "ok"
    assert resp.usage["key_pool_size"] == 2
    assert resp.usage["key_id"] == "key_2"
    assert resp.usage["attempts"] == 2
    assert calls == ["key-a", "key-b"]


def test_openai_native_client_treats_cloudflare_521_and_523_as_transient():
    from clients.openai_native import OpenAINativeClient

    for status_code in (521, 523):
        exc = types.SimpleNamespace(status_code=status_code)

        assert OpenAINativeClient._is_transient_error(exc) is True


class _IntermittentAuth401Error(Exception):
    status_code = 401


class _IntermittentAuthResponses:
    def __init__(self):
        self.calls = 0

    def create(self, **kwargs):
        self.calls += 1
        if self.calls == 1:
            raise _IntermittentAuth401Error("Error code: 401 - {'code': 'INVALID_API_KEY'}")
        usage = SimpleNamespace(input_tokens=1, output_tokens=1)
        return SimpleNamespace(
            output=[],
            output_text="ok",
            usage=usage,
            model=kwargs["model"],
            status="completed",
        )


def test_openai_native_client_can_retry_gateway_intermittent_401(monkeypatch):
    from clients.openai_native import OpenAINativeClient

    fake_responses = _IntermittentAuthResponses()
    fake_client = types.SimpleNamespace(responses=fake_responses)

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_WIRE_API", "responses")
    monkeypatch.setenv("OPENAI_WORKER_MAX_RETRIES", "1")
    monkeypatch.setenv("PECKER_RETRY_INTERMITTENT_AUTH_401", "1")
    monkeypatch.delenv("OPENAI_REASONING_EFFORT", raising=False)
    monkeypatch.setattr("clients.openai_native.time.sleep", lambda _seconds: None)
    monkeypatch.setattr(
        OpenAINativeClient,
        "_build_client",
        lambda self, api_key, base_url: fake_client,
    )

    client = OpenAINativeClient()
    resp = client.create(
        model="gpt-5.4",
        max_tokens=8,
        system="system",
        messages=[{"role": "user", "content": "hello"}],
        retry_policy="worker",
    )

    assert resp.content[0].text == "ok"
    assert resp.usage["attempts"] == 2
    assert fake_responses.calls == 2


def test_openai_native_client_accepts_chinese_colon_key_labels(monkeypatch):
    from clients.openai_native import OpenAINativeClient

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEYS", "key1：sk-a,key2：sk-b")

    assert OpenAINativeClient._load_api_keys(None) == [("key1", "sk-a"), ("key2", "sk-b")]


def test_openai_native_client_supports_responses_wire(monkeypatch):
    from clients.openai_native import OpenAINativeClient

    fake_client = _FakeResponsesOpenAI()
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_WIRE_API", "responses")
    monkeypatch.setenv("PECKER_OPENAI_STRICT_STRUCTURED_OUTPUT", "0")
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


def test_openai_native_client_uses_strict_responses_json_schema_for_structured_tool(monkeypatch):
    from clients.openai_native import OpenAINativeClient

    fake_client = _FakeResponsesOpenAI()
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_WIRE_API", "responses")
    monkeypatch.delenv("OPENAI_REASONING_EFFORT", raising=False)
    monkeypatch.setattr(
        OpenAINativeClient,
        "_build_client",
        lambda self, api_key, base_url: fake_client,
    )

    client = OpenAINativeClient()
    resp = client.create(
        model="gpt-5.5",
        max_tokens=256,
        system="system",
        messages=[{"role": "user", "content": "hello"}],
        tools=[
            {
                "name": "submit_advisor_review",
                "description": "submit",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "confidence": {"type": "number"},
                        "additional_findings": {"type": "array"},
                    },
                },
            }
        ],
        tool_choice={"type": "any"},
    )

    kwargs = fake_client.responses.last_kwargs
    assert resp.usage["strict_structured_output"] is True
    assert "tools" not in kwargs
    assert "tool_choice" not in kwargs
    schema_format = kwargs["text"]["format"]
    assert schema_format["type"] == "json_schema"
    assert schema_format["name"] == "submit_advisor_review"
    assert schema_format["strict"] is True
    assert schema_format["schema"]["additionalProperties"] is False
    assert set(schema_format["schema"]["required"]) == {"confidence", "additional_findings"}


def test_openai_native_client_allows_policy_reasoning_effort_override(monkeypatch):
    from clients.openai_native import OpenAINativeClient

    fake_client = _FakeResponsesOpenAI()
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_WIRE_API", "responses")
    monkeypatch.setenv("OPENAI_REASONING_EFFORT", "xhigh")
    monkeypatch.setenv("OPENAI_WORKER_REASONING_EFFORT", "high")
    monkeypatch.setattr(
        OpenAINativeClient,
        "_build_client",
        lambda self, api_key, base_url: fake_client,
    )

    client = OpenAINativeClient(base_url="https://pikachu.claudecode.love")
    client.create(
        model="gpt-5.4",
        max_tokens=256,
        system="system",
        messages=[{"role": "user", "content": "hello"}],
        retry_policy="worker",
    )

    assert fake_client.responses.last_kwargs["reasoning"] == {"effort": "high"}


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
