from pathlib import Path

from pecker.channel_eval import evaluate_channels, load_channel_config, rank_channels
from pecker.graph import run_review
from pecker.models import ReviewRequest
from pecker.redaction import redact_text
from pecker.tool_registry import ToolAccessError, default_registry


def test_review_returns_findings_with_how_to_fix():
    content = Path("examples/sample_prd.md").read_text(encoding="utf-8")
    result = run_review(ReviewRequest(title="sample", content=content))
    assert result.status == "ok"
    assert result.trace == ["prepare_context", "run_workers", "merge_findings", "finalize_report"]
    assert result.findings
    assert all(finding.how_to_fix for finding in result.findings)


def test_redaction_masks_secrets_and_private_urls():
    api_key = "sk-" + "1234567890abcdef1234567890"
    private_ip = "10." + "1.2.3"
    secret_value = "secret-" + "value"
    text = f"token={secret_value} {api_key} https://{private_ip}/api"
    redacted = redact_text(text)
    assert secret_value not in redacted
    assert "sk-123" not in redacted
    assert private_ip not in redacted


def test_tool_registry_enforces_callers():
    registry = default_registry()
    try:
        registry.execute("prd.extract_sections", {"content": "# A"}, caller="worker.quality")
    except ToolAccessError:
        pass
    else:
        raise AssertionError("unexpected tool access")


def test_channel_eval_dry_run_ranks_candidates():
    candidates = load_channel_config("config/model_channels.example.yaml")
    rankings = rank_channels(evaluate_channels(candidates, dry_run=True))
    assert rankings[0]["name"] == "openai-default"
    assert rankings[0]["passed_gate"] is True
