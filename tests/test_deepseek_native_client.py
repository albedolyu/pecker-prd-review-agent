from __future__ import annotations

from types import SimpleNamespace


class _FakeCompletions:
    def __init__(self):
        self.kwargs = None

    def create(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(
            model=kwargs["model"],
            choices=[
                SimpleNamespace(
                    finish_reason="tool_calls",
                    message=SimpleNamespace(content=None, tool_calls=[]),
                )
            ],
            usage=SimpleNamespace(
                prompt_tokens=10,
                completion_tokens=5,
                prompt_cache_hit_tokens=0,
            ),
        )


class _FakeOpenAI:
    def __init__(self):
        self.completions = _FakeCompletions()
        self.chat = SimpleNamespace(completions=self.completions)


def _client_with_fake_backend():
    from clients.deepseek_native import DeepSeekNativeClient
    from clients.token_tracker import TokenTracker

    backend = _FakeOpenAI()
    client = DeepSeekNativeClient.__new__(DeepSeekNativeClient)
    client.client = backend
    client.tracker = TokenTracker()
    return client, backend


def test_v4_pro_tool_calls_disable_thinking_by_default(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_THINKING_MODE", raising=False)
    client, backend = _client_with_fake_backend()

    client.create(
        model="deepseek-v4-pro",
        max_tokens=256,
        system="submit via tool",
        messages=[{"role": "user", "content": "PRD"}],
        tools=[
            {
                "name": "submit_review_items",
                "description": "Submit items",
                "input_schema": {
                    "type": "object",
                    "properties": {"items": {"type": "array"}},
                    "required": ["items"],
                },
            }
        ],
        tool_choice={"type": "any"},
        retry_policy="worker",
    )

    assert backend.completions.kwargs["extra_body"] == {
        "thinking": {"type": "disabled"}
    }


def test_v4_pro_without_tools_keeps_default_thinking_mode(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_THINKING_MODE", raising=False)
    client, backend = _client_with_fake_backend()

    client.create(
        model="deepseek-v4-pro",
        max_tokens=64,
        system="plain chat",
        messages=[{"role": "user", "content": "hello"}],
        retry_policy="router",
    )

    assert "extra_body" not in backend.completions.kwargs
