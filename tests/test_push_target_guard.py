from __future__ import annotations


def test_company_gitlab_allows_sensitive_paths():
    from scripts.check_push_target import evaluate_push

    result = evaluate_push(
        remote_url="http://git.xinshucredit.com/riskbirdm/prd-review-agent.git",
        changed_files=["workspace-alpha/prd/demo.md", ".pecker_drafts/a.json"],
    )

    assert result.allowed is True
    assert result.blocked_files == []


def test_github_blocks_sensitive_paths():
    from scripts.check_push_target import evaluate_push

    result = evaluate_push(
        remote_url="https://github.com/riskbird/prd-review-agent.git",
        changed_files=[
            "workspace-alpha/prd/demo.md",
            "eval_reports/demo_pm_revision.md",
            "review/finding_outcomes.db",
            ".env.local",
            "shared-wiki/company.md",
            "api/routes/review.py",
        ],
    )

    assert result.allowed is False
    assert result.blocked_files == [
        "workspace-alpha/prd/demo.md",
        "eval_reports/demo_pm_revision.md",
        "review/finding_outcomes.db",
        ".env.local",
        "shared-wiki/company.md",
    ]


def test_github_blocks_private_workspace_trees_but_allows_sample_workspace():
    from scripts.check_push_target import evaluate_push

    result = evaluate_push(
        remote_url="https://github.com/riskbird/prd-review-agent.git",
        changed_files=[
            "workspace/prd/internal.md",
            "workspace-alpha/wiki/index.md",
            "workspace-alpha/review-rules/review-checklist.yaml",
            "workspace-alpha/.pecker_acl.json",
            "workspace-alpha/knowledge/export.json",
            "workspace-sample/prd/sample-1-favorites.md",
            "workspace-sample/wiki/index.md",
        ],
    )

    assert result.allowed is False
    assert result.blocked_files == [
        "workspace/prd/internal.md",
        "workspace-alpha/wiki/index.md",
        "workspace-alpha/review-rules/review-checklist.yaml",
        "workspace-alpha/.pecker_acl.json",
        "workspace-alpha/knowledge/export.json",
    ]


def test_github_allows_non_sensitive_paths():
    from scripts.check_push_target import evaluate_push

    result = evaluate_push(
        remote_url="git@github.com:riskbird/prd-review-agent.git",
        changed_files=["api/routes/review.py", "tests/test_review.py", ".env.example"],
    )

    assert result.allowed is True


def test_push_guard_env_bypass_allows_public_sensitive_paths(monkeypatch):
    from scripts.check_push_target import evaluate_push

    monkeypatch.setenv("PECKER_PUSH_GUARD", "0")

    result = evaluate_push(
        remote_url="https://github.com/riskbird/prd-review-agent.git",
        changed_files=["workspace-alpha/raw/source.md"],
    )

    assert result.allowed is True
    assert result.reason == "disabled"
