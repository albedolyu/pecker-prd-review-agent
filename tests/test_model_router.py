"""model_router + clients/factory 单元测试。

覆盖:
- RouteConfig 加载 / 校验失败 (vendor 缺失 / tier 错配 / transport 非法)
- resolve route_id → vendor + transport + model 实名 + retry_policy
- model_override (tier 别名) 覆盖默认 model, 非法 override 回退 + warn
- worker.* fallback 到 worker.default
- enabled: false 抛 RouteDisabledError
- PECKER_MODEL_OVERRIDE env 仅作用于 worker.*
- route_call 端到端 (用 fake client 模拟 anthropic + openai 两 vendor)
- route_call_with_shadow 主成功 + shadow 失败时不阻断主路径
- factory 单例语义
"""
from __future__ import annotations

import os
import sys
import tempfile
import textwrap

import pytest

# tests/ 不在 sys.path 默认时, 通过 tests.fake_clients 模块路径 import
TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
if TESTS_DIR not in sys.path:
    sys.path.insert(0, TESTS_DIR)
sys.modules["tests.test_model_router"] = sys.modules[__name__]


# ============================================================
# Fake clients (放在测试模块级, 避免真的去 import claude_cli/anthropic_native)
# ============================================================

class _FakeUnifiedResponse:
    def __init__(self, model: str, text: str = "ok"):
        self.model = model
        self.text_blocks = [{"type": "text", "text": text}]
        self.tool_calls = []
        self.stop_reason = "end_turn"
        self.usage = {"input_tokens": 1, "output_tokens": 1}
        self.truncated = False


class FakeAnthropicCLI:
    """模拟 ClaudeCodeCLIClient, 记录最后一次 create() 调用的 kwargs。"""
    last_call: dict = {}

    def create(self, model, max_tokens, system, messages, tools=None, tool_choice=None,
               temperature=0.2, retry_policy="foreground"):
        FakeAnthropicCLI.last_call = {
            "model": model, "max_tokens": max_tokens, "system": system,
            "messages": messages, "tools": tools, "tool_choice": tool_choice,
            "temperature": temperature, "retry_policy": retry_policy,
        }
        return _FakeUnifiedResponse(model, text=f"anthropic-cli:{model}")


class FakeAnthropicNative:
    last_call: dict = {}

    def create(self, model, max_tokens, system, messages, tools=None, tool_choice=None,
               temperature=0.2, retry_policy="foreground"):
        FakeAnthropicNative.last_call = {
            "model": model, "retry_policy": retry_policy,
        }
        return _FakeUnifiedResponse(model, text=f"anthropic-native:{model}")


class FakeCodexCLI:
    last_call: dict = {}

    def create(self, model, max_tokens, system, messages, tools=None, tool_choice=None,
               temperature=0.2, retry_policy="foreground"):
        FakeCodexCLI.last_call = {
            "model": model, "retry_policy": retry_policy,
        }
        return _FakeUnifiedResponse(model, text=f"codex-cli:{model}")


class FakeFailingClient:
    def create(self, *a, **kw):
        raise RuntimeError("simulated client failure")


class FakeTransientFailingClient:
    def create(self, *a, **kw):
        raise TimeoutError("Request timed out.")


class FakeGateway524FailingClient:
    def create(self, *a, **kw):
        raise RuntimeError("HTTP 524")


class FakeDeepSeekNative:
    last_call: dict = {}

    def create(self, model, max_tokens, system, messages, tools=None, tool_choice=None,
               temperature=0.2, retry_policy="foreground"):
        FakeDeepSeekNative.last_call = {
            "model": model, "retry_policy": retry_policy,
        }
        return _FakeUnifiedResponse(model, text=f"deepseek-native:{model}")


# ============================================================
# Fixtures
# ============================================================

_BASE_YAML = """
vendors:
  anthropic:
    cli_client: tests.test_model_router.FakeAnthropicCLI
    native_client: tests.test_model_router.FakeAnthropicNative
    model_tiers:
      opus:   claude-opus-x
      sonnet: claude-sonnet-x
      haiku:  claude-haiku-x
    fallback_chain: [opus, sonnet, haiku]
  openai:
    cli_client: tests.test_model_router.FakeCodexCLI
    model_tiers:
      pro: gpt-pro
      mid: gpt-mid
    fallback_chain: [pro, mid]

routes:
  worker.default:    {vendor: anthropic, transport: cli, model: sonnet, retry_policy: worker}
  worker.compliance: {vendor: anthropic, transport: cli, model: sonnet, retry_policy: worker}
  worker.quality:    {vendor: anthropic, transport: cli, model: opus,   retry_policy: worker}
  advisor.goshawk:   {vendor: anthropic, transport: cli, model: sonnet, retry_policy: advisor}
  advisor.goshawk.shadow: {vendor: openai, transport: cli, model: pro, retry_policy: advisor, enabled: false}
  advisor.goshawk.shadow_on: {vendor: openai, transport: cli, model: pro, retry_policy: advisor}
  verify.nli:        {vendor: anthropic, transport: cli, model: haiku, retry_policy: router}
  router.intent:     {vendor: anthropic, transport: native, model: haiku, retry_policy: router}
"""


@pytest.fixture
def routes_file(tmp_path, monkeypatch):
    """临时 routes.yaml + 重置 model_router/factory 单例缓存。"""
    path = tmp_path / "routes.yaml"
    path.write_text(_BASE_YAML, encoding="utf-8")
    monkeypatch.setenv("PECKER_ROUTES_FILE", str(path))
    monkeypatch.delenv("PECKER_MODEL_OVERRIDE", raising=False)

    import model_router
    from clients import factory
    model_router.reset_config_cache()
    factory.reset_clients()
    FakeAnthropicCLI.last_call = {}
    FakeAnthropicNative.last_call = {}
    FakeCodexCLI.last_call = {}
    yield path
    model_router.reset_config_cache()
    factory.reset_clients()


# ============================================================
# 1. RouteConfig 加载与校验
# ============================================================

def test_load_routes_succeeds(routes_file):
    from model_router import get_route_config
    cfg = get_route_config()
    assert "anthropic" in cfg.vendors
    assert "openai" in cfg.vendors
    assert "worker.compliance" in cfg.routes
    assert "advisor.goshawk.shadow" in cfg.routes


def test_route_config_rejects_unknown_vendor(tmp_path, monkeypatch):
    yml = textwrap.dedent("""
    vendors:
      anthropic:
        cli_client: tests.test_model_router.FakeAnthropicCLI
        model_tiers: {sonnet: claude-sonnet-x}
        fallback_chain: [sonnet]
    routes:
      worker.compliance: {vendor: bogus, transport: cli, model: sonnet, retry_policy: worker}
    """)
    p = tmp_path / "bad.yaml"
    p.write_text(yml, encoding="utf-8")
    monkeypatch.setenv("PECKER_ROUTES_FILE", str(p))
    import model_router
    model_router.reset_config_cache()
    with pytest.raises(model_router.RouteConfigError, match="vendor 'bogus' 未定义"):
        model_router.get_route_config()


def test_route_config_rejects_unknown_tier(tmp_path, monkeypatch):
    yml = textwrap.dedent("""
    vendors:
      anthropic:
        cli_client: tests.test_model_router.FakeAnthropicCLI
        model_tiers: {sonnet: claude-sonnet-x}
        fallback_chain: [sonnet]
    routes:
      worker.compliance: {vendor: anthropic, transport: cli, model: opus, retry_policy: worker}
    """)
    p = tmp_path / "bad.yaml"
    p.write_text(yml, encoding="utf-8")
    monkeypatch.setenv("PECKER_ROUTES_FILE", str(p))
    import model_router
    model_router.reset_config_cache()
    with pytest.raises(model_router.RouteConfigError, match="model tier 'opus' 不在"):
        model_router.get_route_config()


def test_route_config_rejects_bad_transport(tmp_path, monkeypatch):
    yml = textwrap.dedent("""
    vendors:
      anthropic:
        cli_client: tests.test_model_router.FakeAnthropicCLI
        model_tiers: {sonnet: x}
        fallback_chain: [sonnet]
    routes:
      worker.compliance: {vendor: anthropic, transport: subprocess, model: sonnet, retry_policy: worker}
    """)
    p = tmp_path / "bad.yaml"
    p.write_text(yml, encoding="utf-8")
    monkeypatch.setenv("PECKER_ROUTES_FILE", str(p))
    import model_router
    model_router.reset_config_cache()
    with pytest.raises(model_router.RouteConfigError, match="transport 必须是 cli 或 native"):
        model_router.get_route_config()


# ============================================================
# 2. resolve() — route_id 到 model 实名解析
# ============================================================

def test_resolve_basic_route(routes_file):
    from model_router import get_route_config
    cfg = get_route_config()
    r = cfg.resolve("advisor.goshawk")
    assert r["vendor"] == "anthropic"
    assert r["transport"] == "cli"
    assert r["tier"] == "sonnet"
    assert r["model"] == "claude-sonnet-x"
    assert r["retry_policy"] == "advisor"
    assert r["enabled"] is True


def test_resolve_with_model_override(routes_file):
    from model_router import get_route_config
    cfg = get_route_config()
    r = cfg.resolve("worker.compliance", model_override="opus")
    assert r["tier"] == "opus"
    assert r["model"] == "claude-opus-x"


def test_resolve_invalid_override_falls_back_to_route_default(routes_file, caplog):
    from model_router import get_route_config
    cfg = get_route_config()
    # haiku 在 anthropic vendor 里有, 但故意传 worker.quality 不存在的别名
    r = cfg.resolve("worker.quality", model_override="ultra")
    # ultra 不存在, 应回退到 route 默认 opus
    assert r["tier"] == "opus"
    assert r["model"] == "claude-opus-x"


def test_resolve_unknown_route_falls_back_to_namespace_default(routes_file):
    from model_router import get_route_config
    cfg = get_route_config()
    r = cfg.resolve("worker.nonexistent_dim")
    assert r["route_id"] == "worker.default"
    assert r["model"] == "claude-sonnet-x"


def test_resolve_unknown_route_no_default_raises(routes_file):
    from model_router import get_route_config, RouteConfigError
    cfg = get_route_config()
    with pytest.raises(RouteConfigError, match="未注册且无 'eval.default' 兜底"):
        cfg.resolve("eval.bogus")


# ============================================================
# 3. route_call 端到端 (用 fake client)
# ============================================================

def test_route_call_dispatches_to_correct_vendor(routes_file):
    from model_router import route_call
    resp = route_call(
        "advisor.goshawk",
        system="sys",
        messages=[{"role": "user", "content": "hi"}],
    )
    assert FakeAnthropicCLI.last_call["model"] == "claude-sonnet-x"
    assert FakeAnthropicCLI.last_call["retry_policy"] == "advisor"
    assert resp.model == "claude-sonnet-x"


def test_route_call_native_transport(routes_file):
    from model_router import route_call
    resp = route_call(
        "router.intent",
        system="route prompt",
        messages=[{"role": "user", "content": "x"}],
    )
    # router.intent transport=native → 走 FakeAnthropicNative
    assert FakeAnthropicNative.last_call["model"] == "claude-haiku-x"
    assert resp.text_blocks[0]["text"].startswith("anthropic-native:")


def test_route_call_with_model_override(routes_file):
    from model_router import route_call
    route_call(
        "worker.compliance",
        system="x",
        messages=[],
        model_override="opus",
    )
    assert FakeAnthropicCLI.last_call["model"] == "claude-opus-x"


def test_route_call_disabled_raises(routes_file):
    from model_router import route_call, RouteDisabledError
    with pytest.raises(RouteDisabledError, match="advisor.goshawk.shadow"):
        route_call(
            "advisor.goshawk.shadow",
            system="x", messages=[],
        )


def test_route_call_uses_fallback_route_on_transient_failure(tmp_path, monkeypatch):
    yml = textwrap.dedent("""
    vendors:
      openai:
        cli_client: tests.test_model_router.FakeTransientFailingClient
        model_tiers: {gpt55: gpt-5.5}
        fallback_chain: [gpt55]
      deepseek:
        native_client: tests.test_model_router.FakeDeepSeekNative
        model_tiers: {pro: deepseek-v4-pro}
        fallback_chain: [pro]
    routes:
      worker.structure:
        vendor: openai
        transport: cli
        model: gpt55
        retry_policy: worker
        fallback_route: fallback.deepseek_v4_pro
      fallback.deepseek_v4_pro:
        vendor: deepseek
        transport: native
        model: pro
        retry_policy: worker
    """)
    path = tmp_path / "routes.yaml"
    path.write_text(yml, encoding="utf-8")
    monkeypatch.setenv("PECKER_ROUTES_FILE", str(path))

    import model_router
    from clients import factory
    model_router.reset_config_cache()
    factory.reset_clients()
    FakeDeepSeekNative.last_call = {}

    resp = model_router.route_call(
        "worker.structure",
        system="x",
        messages=[],
        tools=[{"name": "submit_review_items", "input_schema": {"type": "object"}}],
        tool_choice={"type": "any"},
    )

    assert resp.model == "deepseek-v4-pro"
    assert FakeDeepSeekNative.last_call["model"] == "deepseek-v4-pro"
    assert FakeDeepSeekNative.last_call["retry_policy"] == "worker"


def test_route_call_uses_fallback_route_on_cloudflare_524(tmp_path, monkeypatch):
    yml = textwrap.dedent("""
    vendors:
      openai:
        cli_client: tests.test_model_router.FakeGateway524FailingClient
        model_tiers: {gpt55: gpt-5.5}
        fallback_chain: [gpt55]
      deepseek:
        native_client: tests.test_model_router.FakeDeepSeekNative
        model_tiers: {pro: deepseek-v4-pro}
        fallback_chain: [pro]
    routes:
      worker.structure:
        vendor: openai
        transport: cli
        model: gpt55
        retry_policy: worker
        fallback_route: fallback.deepseek_v4_pro
      fallback.deepseek_v4_pro:
        vendor: deepseek
        transport: native
        model: pro
        retry_policy: worker
    """)
    path = tmp_path / "routes.yaml"
    path.write_text(yml, encoding="utf-8")
    monkeypatch.setenv("PECKER_ROUTES_FILE", str(path))

    import model_router
    from clients import factory
    model_router.reset_config_cache()
    factory.reset_clients()
    FakeDeepSeekNative.last_call = {}

    resp = model_router.route_call(
        "worker.structure",
        system="x",
        messages=[],
    )

    assert resp.model == "deepseek-v4-pro"
    assert FakeDeepSeekNative.last_call["model"] == "deepseek-v4-pro"


def test_pecker_model_override_env_only_applies_to_worker(routes_file, monkeypatch):
    """PECKER_MODEL_OVERRIDE 应只覆盖 worker.* tier, advisor/verify/router 不受影响"""
    from model_router import route_call
    monkeypatch.setenv("PECKER_MODEL_OVERRIDE", "haiku")

    # worker.* 应被 override
    route_call("worker.compliance", system="x", messages=[])
    assert FakeAnthropicCLI.last_call["model"] == "claude-haiku-x"

    # advisor 不应被 override (保持 route 默认 sonnet)
    route_call("advisor.goshawk", system="x", messages=[])
    assert FakeAnthropicCLI.last_call["model"] == "claude-sonnet-x"


def test_pecker_model_override_auto_is_noop(routes_file, monkeypatch):
    from model_router import route_call
    monkeypatch.setenv("PECKER_MODEL_OVERRIDE", "auto")
    route_call("worker.compliance", system="x", messages=[])
    # auto = 不 override, 用 route 默认 sonnet
    assert FakeAnthropicCLI.last_call["model"] == "claude-sonnet-x"


def test_get_model_for_route_respects_worker_env_override(routes_file, monkeypatch):
    """dry-run/telemetry model resolution must match route_call for worker routes."""
    from model_router import get_model_for_route

    monkeypatch.setenv("PECKER_MODEL_OVERRIDE", "haiku")

    assert get_model_for_route("worker.compliance") == "claude-haiku-x"
    assert get_model_for_route("advisor.goshawk") == "claude-sonnet-x"


# ============================================================
# 4. route_call_with_shadow
# ============================================================

def test_shadow_returns_none_when_disabled(routes_file):
    from model_router import route_call_with_shadow
    primary, shadow = route_call_with_shadow(
        "advisor.goshawk",
        system="x", messages=[],
    )
    assert primary.model == "claude-sonnet-x"
    assert shadow is None  # advisor.goshawk.shadow enabled=false


def test_shadow_runs_when_explicit_route_enabled(routes_file, tmp_path, monkeypatch):
    """显式指定 enabled=true 的 shadow_route_id 应实际跑并返回结果"""
    from model_router import route_call_with_shadow
    primary, shadow = route_call_with_shadow(
        "advisor.goshawk",
        shadow_route_id="advisor.goshawk.shadow_on",
        system="x", messages=[],
    )
    assert primary.model == "claude-sonnet-x"        # anthropic
    assert shadow is not None
    assert shadow.model == "gpt-pro"                  # openai/codex
    assert FakeCodexCLI.last_call["model"] == "gpt-pro"


def test_shadow_failure_does_not_break_primary(routes_file, monkeypatch):
    """shadow 抛异常时主路径仍应正常返回"""
    import clients.factory as factory
    from model_router import route_call_with_shadow

    # 替换 openai 的 cli client 为永远失败的
    factory.reset_clients()
    monkeypatch.setattr(
        "clients.factory._import_class",
        lambda path: FakeFailingClient if "Codex" in path else __import__(
            ".".join(path.split(".")[:-1]), fromlist=[path.split(".")[-1]]
        ).__dict__[path.split(".")[-1]],
    )
    primary, shadow = route_call_with_shadow(
        "advisor.goshawk",
        shadow_route_id="advisor.goshawk.shadow_on",
        system="x", messages=[],
    )
    assert primary.model == "claude-sonnet-x"
    assert shadow is None  # shadow 失败应吞掉返回 None


# ============================================================
# 5. factory 单例语义
# ============================================================

def test_factory_returns_same_instance(routes_file):
    from clients.factory import get_client
    a = get_client("anthropic", "cli")
    b = get_client("anthropic", "cli")
    assert a is b


def test_factory_different_transport_separate_instance(routes_file):
    from clients.factory import get_client
    cli = get_client("anthropic", "cli")
    native = get_client("anthropic", "native")
    assert cli is not native


def test_factory_unknown_vendor_raises(routes_file):
    from clients.factory import get_client
    with pytest.raises(ValueError, match="vendor 'bogus' 未在"):
        get_client("bogus", "cli")


def test_factory_missing_transport_path_raises(routes_file):
    """openai 没配 native_client, 请求 native transport 应明确报错"""
    from clients.factory import get_client
    with pytest.raises(ValueError, match="vendor 'openai' 没配置 native_client"):
        get_client("openai", "native")


# ============================================================
# 6. Convenience helpers
# ============================================================

def test_get_model_for_route_no_call(routes_file):
    from model_router import get_model_for_route
    m = get_model_for_route("verify.nli")
    assert m == "claude-haiku-x"
    # 不应 dispatch 到 client
    assert FakeAnthropicCLI.last_call == {}


def test_list_routes(routes_file):
    from model_router import list_routes
    routes = list_routes()
    assert "advisor.goshawk" in routes
    assert "worker.compliance" in routes
    assert "router.intent" in routes


def test_get_route_meta(routes_file):
    from model_router import get_route_meta
    meta = get_route_meta("worker.quality")
    assert meta["model"] == "claude-opus-x"
    assert meta["fallback_chain"] == ["opus", "sonnet", "haiku"]
