"""按 route_id 路由 LLM 调用到对应 vendor + client + model 的统一抽象层。

调用约定:
    from model_router import route_call

    resp = route_call(
        route_id="advisor.goshawk",      # 关键: 用 route_id 而非裸 model 名
        system=...,
        messages=...,
        tools=...,                        # 可选
        tool_choice=...,                  # 可选
        max_tokens=8192,                  # 可选
        temperature=0.2,                  # 可选
        model_override="gpt55",           # 可选: worker tier 别名,兼容 --model 风格覆盖
    )

route_id 命名空间见 model_routes.yaml 头部注释。

为什么用 route_id 而不是裸 model 字符串:
- 解耦"调用语义"(我是 worker.compliance) 与"承载实现"(例如 openai.gpt54 还是 deepseek.flash)
- 一处改 routes.yaml 全链路生效, 不需要 grep 散落硬编码
- 评测/影子/灰度可以按 route_id 切流量 (route_call_with_shadow)
- 跨 vendor 时 model_tiers 各家不同,按 tier 别名抽象避免 if-vendor 写满代码
"""
from __future__ import annotations

import json
import os
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

import yaml

from logger import get_logger

log = get_logger("model_router")


# ============================================================
# 异常
# ============================================================

class RouteDisabledError(Exception):
    """route 在 routes.yaml 标记 enabled: false (e.g. 未启用的影子 route)"""
    pass


class RouteConfigError(ValueError):
    """routes.yaml 配置不合法 (vendor 未定义 / tier 缺失 / transport 非法)"""
    pass


# ============================================================
# Route 配置加载 (单例 + 显式 reload)
# ============================================================

class RouteConfig:
    """从 model_routes.yaml 加载的路由配置 (vendor + routes 两段)。"""

    def __init__(self, routes_path: str):
        self.routes_path = routes_path
        with open(routes_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        self.vendors: Dict[str, Dict[str, Any]] = data.get("vendors", {}) or {}
        self.routes: Dict[str, Dict[str, Any]] = data.get("routes", {}) or {}
        self._validate()

    def _validate(self):
        if not self.vendors:
            raise RouteConfigError(f"{self.routes_path}: 必须至少配一个 vendor")
        if not self.routes:
            raise RouteConfigError(f"{self.routes_path}: 必须至少配一个 route")

        for vname, v in self.vendors.items():
            if not (v.get("cli_client") or v.get("native_client")):
                raise RouteConfigError(
                    f"vendor {vname!r}: 必须有 cli_client 或 native_client"
                )
            if not v.get("model_tiers"):
                raise RouteConfigError(f"vendor {vname!r}: 必须有 model_tiers")
            if not v.get("fallback_chain"):
                raise RouteConfigError(f"vendor {vname!r}: 必须有 fallback_chain")

        for rid, r in self.routes.items():
            v = r.get("vendor")
            if v not in self.vendors:
                raise RouteConfigError(f"route {rid!r}: vendor {v!r} 未定义")
            transport = r.get("transport")
            if transport not in ("cli", "native"):
                raise RouteConfigError(
                    f"route {rid!r}: transport 必须是 cli 或 native (实际 {transport!r})"
                )
            tier = r.get("model")
            if tier not in self.vendors[v]["model_tiers"]:
                raise RouteConfigError(
                    f"route {rid!r}: model tier {tier!r} 不在 vendor {v!r} 的 model_tiers 中 "
                    f"(可选: {sorted(self.vendors[v]['model_tiers'].keys())})"
                )
            fallback_route = r.get("fallback_route")
            if fallback_route:
                if fallback_route == rid:
                    raise RouteConfigError(f"route {rid!r}: fallback_route must not point to itself")
                if fallback_route not in self.routes:
                    raise RouteConfigError(
                        f"route {rid!r}: fallback_route {fallback_route!r} is not registered"
                    )

    def resolve(
        self,
        route_id: str,
        model_override: Optional[str] = None,
    ) -> Dict[str, Any]:
        """解析 route_id 到 dict(vendor, transport, model_real, retry_policy, enabled, ...)。

        model_override 是 tier 别名 (团队版常用 gpt55/gpt54/gpt54mini),用于
        worker 兼容旧 dim["model"] 字段以及 --model CLI 参数。如果 override 的 tier 在目标 vendor
        的 model_tiers 中不存在, 回退到 route 默认 tier 并 warn。
        """
        # 未注册 route_id 时 fallback 到同 namespace 的 default
        if route_id not in self.routes:
            ns = route_id.split(".")[0]
            default_id = f"{ns}.default"
            if default_id in self.routes:
                log.warning(
                    f"route {route_id!r} 未在 {self.routes_path} 注册, 回退到 {default_id!r}"
                )
                route_id = default_id
            else:
                raise RouteConfigError(
                    f"route {route_id!r} 未注册且无 {default_id!r} 兜底, "
                    f"请检查 model_routes.yaml"
                )

        r = self.routes[route_id]
        vendor = r["vendor"]
        v_cfg = self.vendors[vendor]
        tier = (model_override or "").strip() or r["model"]

        if tier not in v_cfg["model_tiers"]:
            log.warning(
                f"tier {tier!r} 不在 vendor {vendor!r} 的 model_tiers, "
                f"回退到 route {route_id!r} 默认 {r['model']!r}"
            )
            tier = r["model"]

        return {
            "route_id": route_id,
            "vendor": vendor,
            "transport": r["transport"],
            "tier": tier,
            "model": v_cfg["model_tiers"][tier],
            "retry_policy": r.get("retry_policy", "foreground"),
            "enabled": r.get("enabled", True),
            "fallback_chain": list(v_cfg.get("fallback_chain", [])),
            "model_tiers": dict(v_cfg["model_tiers"]),
            "fallback_route": r.get("fallback_route"),
        }


_config_lock = threading.Lock()
_config_cache: Optional[RouteConfig] = None
_model_call_limiter_lock = threading.Lock()
_model_call_limiter: Optional[threading.BoundedSemaphore] = None
_model_call_limiter_size: Optional[int] = None


def get_route_config(force_reload: bool = False) -> RouteConfig:
    """加载 (并缓存) RouteConfig 单例。

    优先级:
        env PECKER_ROUTES_FILE > 项目根 model_routes.yaml
    """
    global _config_cache
    if _config_cache is not None and not force_reload:
        return _config_cache
    with _config_lock:
        if _config_cache is not None and not force_reload:
            return _config_cache
        path = os.environ.get("PECKER_ROUTES_FILE", "").strip() or _default_routes_path()
        _config_cache = RouteConfig(path)
        log.info(
            f"loaded model_routes from {path}: "
            f"{len(_config_cache.routes)} routes, {len(_config_cache.vendors)} vendors"
        )
    return _config_cache


def _default_routes_path() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(here, "model_routes.yaml")


def reset_config_cache():
    """单测用: 强制下次 get_route_config 重新加载"""
    global _config_cache
    with _config_lock:
        _config_cache = None


def _get_model_call_limiter() -> Optional[threading.BoundedSemaphore]:
    raw = os.environ.get("PECKER_MAX_CONCURRENT_MODEL_CALLS", "").strip()
    if not raw:
        return None
    try:
        size = int(raw)
    except ValueError:
        log.warning("PECKER_MAX_CONCURRENT_MODEL_CALLS must be an integer; limiter disabled")
        return None
    if size <= 0:
        return None

    global _model_call_limiter, _model_call_limiter_size
    with _model_call_limiter_lock:
        if _model_call_limiter is None or _model_call_limiter_size != size:
            _model_call_limiter = threading.BoundedSemaphore(size)
            _model_call_limiter_size = size
        return _model_call_limiter


def _get_model_call_queue_timeout() -> Optional[float]:
    raw = os.environ.get("PECKER_MODEL_CALL_QUEUE_TIMEOUT", "").strip()
    if not raw:
        return None
    try:
        value = float(raw)
    except ValueError:
        log.warning("PECKER_MODEL_CALL_QUEUE_TIMEOUT must be a number; queue timeout disabled")
        return None
    if value <= 0:
        return None
    return value


def reset_model_call_limiter():
    """Test helper: clear the process-wide model-call gate."""
    global _model_call_limiter, _model_call_limiter_size
    with _model_call_limiter_lock:
        _model_call_limiter = None
        _model_call_limiter_size = None


# ============================================================
# 路由调用 — 主入口
# ============================================================

def _is_transient_route_error(exc: Exception) -> bool:
    if isinstance(exc, TimeoutError):
        return True
    text = f"{type(exc).__name__}: {exc}".lower()
    markers = (
        "timeout",
        "timed out",
        "rate limit",
        "429",
        "500",
        "520",
        "521",
        "522",
        "523",
        "524",
        "502",
        "503",
        "504",
        "connection",
        "temporarily",
        "overloaded",
        "server error",
    )
    return any(marker in text for marker in markers)


def _effective_worker_model_override(
    route_id: str,
    model_override: Optional[str] = None,
) -> Optional[str]:
    """Mirror route_call's worker-only PECKER_MODEL_OVERRIDE behavior.

    Dry-run helpers and telemetry must resolve the same model that the real
    request will use, otherwise the UI can show gpt-5.4 while the request is
    actually sent to gpt-5.5.
    """
    env_override = os.environ.get("PECKER_MODEL_OVERRIDE", "").strip()
    if env_override and env_override != "auto" and route_id.startswith("worker."):
        return env_override
    return model_override


def route_call(
    route_id: str,
    *,
    system: Any,
    messages: List[Dict[str, Any]],
    tools: Optional[List[Dict[str, Any]]] = None,
    tool_choice: Optional[Dict[str, Any]] = None,
    max_tokens: int = 8192,
    temperature: float = 0.2,
    model_override: Optional[str] = None,
) -> Any:
    """按 route_id 路由 LLM 调用, 返回 client.create() 的 UnifiedResponse。

    全局 env override (仅作用于 worker.*):
        PECKER_MODEL_OVERRIDE=auto|gpt55|gpt54|gpt54mini    覆盖所有 worker.* 的 tier
        ("auto" 等价于不 override)
    """
    cfg = get_route_config()

    # 全局 PECKER_MODEL_OVERRIDE (等价 --model) 仅对 worker.* 路由生效, 模拟旧 --model 全局参数语义
    model_override = _effective_worker_model_override(route_id, model_override)

    resolved = cfg.resolve(route_id, model_override=model_override)
    if not resolved["enabled"]:
        raise RouteDisabledError(
            f"route {route_id!r} 在 {cfg.routes_path} 标记 enabled: false"
        )

    from clients.factory import get_client
    client = get_client(resolved["vendor"], resolved["transport"])

    log.info(
        f"[route_call] {route_id} → vendor={resolved['vendor']} "
        f"transport={resolved['transport']} model={resolved['model']} "
        f"(tier={resolved['tier']}) policy={resolved['retry_policy']}"
    )

    limiter = _get_model_call_limiter()
    acquired = False
    wait_start = time.time()
    try:
        if limiter is not None:
            queue_timeout = _get_model_call_queue_timeout()
            if queue_timeout is None:
                limiter.acquire()
            else:
                acquired = limiter.acquire(timeout=queue_timeout)
                if not acquired:
                    raise TimeoutError(
                        f"Timed out waiting for model-call slot after {queue_timeout:.1f}s "
                        f"(route={route_id}, model={resolved['model']})"
                    )
            acquired = True
            waited_ms = int((time.time() - wait_start) * 1000)
            if waited_ms > 1000:
                log.info(
                    f"[route_call] waited {waited_ms}ms for model-call slot "
                    f"route={route_id} model={resolved['model']}"
                )
        try:
            return client.create(
                model=resolved["model"],
                max_tokens=max_tokens,
                system=system,
                messages=messages,
                tools=tools,
                tool_choice=tool_choice,
                temperature=temperature,
                retry_policy=resolved["retry_policy"],
            )
        except Exception as primary_exc:
            fallback_route = resolved.get("fallback_route")
            if not fallback_route or not _is_transient_route_error(primary_exc):
                raise
            try:
                fallback_resolved = cfg.resolve(fallback_route)
                if not fallback_resolved["enabled"]:
                    raise RouteDisabledError(
                        f"fallback route {fallback_route!r} is disabled"
                    )
                from clients.factory import get_client as _get_fallback_client
                fallback_client = _get_fallback_client(
                    fallback_resolved["vendor"],
                    fallback_resolved["transport"],
                )
                log.warning(
                    f"[route_call] {route_id} transient failure, fallback to {fallback_route}: "
                    f"{type(primary_exc).__name__}: {str(primary_exc)[:160]}"
                )
                return fallback_client.create(
                    model=fallback_resolved["model"],
                    max_tokens=max_tokens,
                    system=system,
                    messages=messages,
                    tools=tools,
                    tool_choice=tool_choice,
                    temperature=temperature,
                    retry_policy=fallback_resolved["retry_policy"],
                )
            except Exception as fallback_exc:
                log.warning(
                    f"[route_call] fallback {fallback_route} also failed; keep primary error. "
                    f"fallback={type(fallback_exc).__name__}: {str(fallback_exc)[:160]}"
                )
                raise primary_exc
    finally:
        if acquired and limiter is not None:
            limiter.release()


# ============================================================
# 影子路由 — P2 双苍鹰 / 跨 vendor 实验槽位
# ============================================================

def route_call_with_shadow(
    route_id: str,
    shadow_route_id: Optional[str] = None,
    **kwargs,
) -> Tuple[Any, Optional[Any]]:
    """主路由 + 影子路由并发 (实际同步先后), shadow 仅落 logs/ 不影响主路径返回。

    用于 P2 影子苍鹰对照实验 (scripts/eval_dual_advisor.py)。

    shadow_route_id None 时默认查 <route_id>.shadow, 该 route 不存在或 enabled=false
    则退化为普通 route_call (返回 (primary_resp, None))。

    返回: (primary_response, shadow_response_or_None)
    """
    if shadow_route_id is None:
        shadow_route_id = f"{route_id}.shadow"

    primary_resp = route_call(route_id, **kwargs)

    cfg = get_route_config()
    shadow_resp = None
    if shadow_route_id in cfg.routes:
        try:
            shadow_resp = route_call(shadow_route_id, **kwargs)
            _log_shadow(route_id, shadow_route_id, primary_resp, shadow_resp)
        except RouteDisabledError:
            pass
        except Exception as e:
            log.warning(
                f"[shadow] {shadow_route_id!r} 失败 (不影响主路径): {type(e).__name__}: {e}"
            )

    return primary_resp, shadow_resp


def _log_shadow(primary_id: str, shadow_id: str, primary_resp: Any, shadow_resp: Any):
    """影子苍鹰输出落 logs/shadow_<primary_safe>_<ts>.jsonl"""
    out_dir = os.path.join(os.path.dirname(_default_routes_path()), "logs")
    try:
        os.makedirs(out_dir, exist_ok=True)
    except OSError:
        return  # 写不进去就放弃, 不阻断主路径

    ts = time.strftime("%Y%m%d_%H%M%S")
    safe_primary = primary_id.replace(".", "_").replace("/", "_")
    path = os.path.join(out_dir, f"shadow_{safe_primary}_{ts}.jsonl")
    rec = {
        "ts": ts,
        "primary_route": primary_id,
        "shadow_route": shadow_id,
        "primary_text": _extract_text(primary_resp),
        "shadow_text": _extract_text(shadow_resp),
        "primary_model": getattr(primary_resp, "model", ""),
        "shadow_model": getattr(shadow_resp, "model", ""),
    }
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError as e:
        log.warning(f"[shadow] 写日志失败 {path}: {e}")


def _extract_text(resp: Any) -> str:
    """从 UnifiedResponse 取 text (供影子日志记录, 截断防文件爆)。"""
    if resp is None:
        return ""
    try:
        for block in getattr(resp, "text_blocks", []) or []:
            if isinstance(block, dict):
                t = block.get("text", "")
            else:
                t = getattr(block, "text", "")
            if t:
                return t[:4000]
    except Exception:
        pass
    return ""


# ============================================================
# 便捷工具 — migration / metrics / dry-run
# ============================================================

def get_model_for_route(
    route_id: str,
    model_override: Optional[str] = None,
) -> str:
    """只解析 model 名, 不真的发请求 (供 migration 期 logging / metrics / dry-run 用)。"""
    cfg = get_route_config()
    model_override = _effective_worker_model_override(route_id, model_override)
    resolved = cfg.resolve(route_id, model_override=model_override)
    return resolved["model"]


def list_routes() -> List[str]:
    """列出所有已注册 route_id (供 scripts/eval_baseline.py 全表跑用)。"""
    cfg = get_route_config()
    return sorted(cfg.routes.keys())


def get_route_meta(route_id: str) -> Dict[str, Any]:
    """返回 resolve 后的 route 元信息 dict (不发请求, 供评测脚本 / dashboard 用)。"""
    cfg = get_route_config()
    return cfg.resolve(route_id)
