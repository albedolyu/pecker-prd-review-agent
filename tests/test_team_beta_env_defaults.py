from __future__ import annotations

from pathlib import Path


def _env_example() -> str:
    return Path(".env.example").read_text(encoding="utf-8")


def test_team_beta_defaults_use_full_worker_parallelism():
    env = _env_example()

    assert "PECKER_WORKER_BATCH_SIZE=4" in env
    assert "PECKER_WORKER_BATCH_SIZE=2" not in env
    assert "2+2" in env


def test_team_beta_defaults_keep_prd_context_packet_enabled():
    env = _env_example()

    assert "PECKER_PRD_CONTEXT_MODE=auto" in env
    assert "PECKER_PRD_CONTEXT_AUTO_CHARS=12000" in env


def test_team_beta_openai_timeout_covers_deep_review_workers():
    env = _env_example()
    values = {
        line.split("=", 1)[0]: line.split("=", 1)[1]
        for line in env.splitlines()
        if "=" in line and not line.lstrip().startswith("#")
    }

    assert float(values["OPENAI_REQUEST_TIMEOUT"]) >= 360


def test_team_beta_model_call_queue_timeout_covers_request_timeout():
    env = _env_example()
    values = {
        line.split("=", 1)[0]: line.split("=", 1)[1]
        for line in env.splitlines()
        if "=" in line and not line.lstrip().startswith("#")
    }

    assert float(values["PECKER_MODEL_CALL_QUEUE_TIMEOUT"]) >= float(
        values["OPENAI_REQUEST_TIMEOUT"]
    )


def test_team_beta_env_copy_does_not_recommend_legacy_claude_override():
    env = _env_example()
    override_block = "\n".join(
        line for line in env.splitlines() if "PECKER_MODEL_OVERRIDE" in line or "--model" in line
    )

    assert "opus" not in override_block
    assert "sonnet" not in override_block
    assert "haiku" not in override_block
    assert "gpt55/gpt54/gpt54mini" in override_block


def test_team_beta_budget_copy_uses_generic_model_call_wording():
    env = _env_example()

    assert "每次 Claude 调用前检查" not in env
    assert "每次模型调用前检查" in env


def test_default_route_comments_do_not_describe_old_opus_router():
    routes = Path("model_routes.yaml").read_text(encoding="utf-8")

    assert "主啄木鸟默认 --model opus" not in routes
    assert "不需要再过 Haiku 分类层" not in routes
    assert "默认由 GPT 路由表控制" in routes


def test_model_router_comments_do_not_recommend_legacy_override_tiers():
    source = Path("model_router.py").read_text(encoding="utf-8")

    assert "PECKER_MODEL_OVERRIDE=opus|sonnet|haiku|auto" not in source
    assert "auto|gpt55|gpt54|gpt54mini" in source
