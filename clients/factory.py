"""Vendor → Client 实例工厂注册表。

按 (vendor, transport) 单例 client 实例, 复用 SDK 客户端的连接池/cache。

新增 vendor 步骤:
1. 在 clients/<vendor>_cli.py 或 clients/<vendor>_native.py 实现兼容 create() 签名的 client 类:
       def create(self, model, max_tokens, system, messages, tools=None,
                  tool_choice=None, temperature=0.2, retry_policy="foreground")
                  -> UnifiedResponse
2. 在 model_routes.yaml 的 vendors 段注册:
       vendors:
         <name>:
           cli_client: clients.<vendor>_cli.<ClassName>      # 可选
           native_client: clients.<vendor>_native.<ClassName> # 可选
           model_tiers: {tier1: model_id1, ...}
           fallback_chain: [tier1, tier2, ...]
3. 在 clients/shared.py 的 MODEL_PRICING 加 vendor 的定价 (cost dashboard 用,可后补)
4. 跑 scripts/eval_admission.py 过 5 维准入门槛, PASS 才启用对应 route

注意:
- factory 不直接 import client 类, 用 importlib 按 routes.yaml 路径动态加载,
  保证未启用的 vendor (如 openai) 不需要装对应 SDK 也能跑测试。
"""
from __future__ import annotations

import importlib
import threading
from typing import Any, Dict, Tuple

_clients: Dict[Tuple[str, str], Any] = {}
_lock = threading.Lock()


def get_client(vendor: str, transport: str) -> Any:
    """按 (vendor, transport) 拿 client 单例 (无则按 routes.yaml 注册路径动态加载)。

    transport: "cli" | "native"
    """
    key = (vendor, transport)
    if key in _clients:
        return _clients[key]
    with _lock:
        if key in _clients:
            return _clients[key]
        # 延迟 import 避免循环 (model_router 也要 import factory)
        from model_router import get_route_config

        cfg = get_route_config()
        v_cfg = cfg.vendors.get(vendor)
        if not v_cfg:
            raise ValueError(f"vendor {vendor!r} 未在 model_routes.yaml 注册")

        path_key = "cli_client" if transport == "cli" else "native_client"
        client_path = v_cfg.get(path_key)
        if not client_path:
            raise ValueError(
                f"vendor {vendor!r} 没配置 {path_key} (routes.yaml.vendors.{vendor}.{path_key})"
            )

        cls = _import_class(client_path)
        _clients[key] = cls()
        return _clients[key]


def _import_class(path: str):
    """'clients.claude_cli.ClaudeCodeCLIClient' → 类对象"""
    module_path, _, cls_name = path.rpartition(".")
    if not module_path:
        raise ValueError(f"不合法的 client class path: {path!r}")
    mod = importlib.import_module(module_path)
    return getattr(mod, cls_name)


def reset_clients():
    """单测用: 清单例缓存 (配合 model_router.reset_config_cache 一起用)"""
    global _clients
    with _lock:
        _clients = {}
