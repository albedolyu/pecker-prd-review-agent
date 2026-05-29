from __future__ import annotations

import re


def test_langfuse_worker_prompt_template_keeps_runtime_placeholders():
    from scripts.langfuse_seed_worker_prompts import langfuse_worker_prompt_template

    template = langfuse_worker_prompt_template()

    assert "{{codename}}" in template
    assert "{{dimension_name}}" in template
    assert "{{dimension_rules}}" in template
    assert "{{checklist_list}}" in template
    assert "{{tone_instructions_block}}" in template
    assert re.search(r"(?<!\{)\{codename\}(?!\})", template) is None


def test_seed_worker_prompts_dry_run_does_not_call_langfuse():
    from scripts.langfuse_seed_worker_prompts import seed_worker_prompts

    result = seed_worker_prompts(
        dim_keys=["structure", "quality"],
        label="canary",
        dry_run=True,
        client_factory=lambda: (_ for _ in ()).throw(AssertionError("must not call client")),
    )

    assert result["ok"] is True
    assert result["created_count"] == 0
    assert [prompt["name"] for prompt in result["prompts"]] == [
        "pecker.worker.structure.system",
        "pecker.worker.quality.system",
    ]
    assert all(prompt["dry_run"] for prompt in result["prompts"])


def test_seed_worker_prompts_creates_langfuse_text_prompts(monkeypatch):
    from scripts.langfuse_seed_worker_prompts import seed_worker_prompts

    calls: list[dict] = []

    class FakeLangfuse:
        def create_prompt(self, **kwargs):
            calls.append(kwargs)

    monkeypatch.setenv("PECKER_LANGFUSE_PROMPT_PREFIX", "pecker")

    result = seed_worker_prompts(
        dim_keys=["structure"],
        label="canary",
        dry_run=False,
        client_factory=lambda: FakeLangfuse(),
    )

    assert result["ok"] is True
    assert result["created_count"] == 1
    assert calls[0]["name"] == "pecker.worker.structure.system"
    assert calls[0]["labels"] == ["canary"]
    assert calls[0]["type"] == "text"
    assert "worker_system_base" in calls[0]["tags"]
    assert calls[0]["config"]["managed_by"] == "pecker"
    assert calls[0]["config"]["dim_key"] == "structure"
    assert "{{dimension_name}}" in calls[0]["prompt"]
