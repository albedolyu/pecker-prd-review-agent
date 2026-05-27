"""评审维度配置加载 + YAML schema 校验.

从 parallel_review.py 拆出 (2026-04-16, step 3.2 重构于 2026-04-27):
- _CN_LABEL / _cn_label: 中文职能词映射(日志用)
- _REVIEW_DIMENSIONS_SCHEMA: YAML schema (jsonschema 格式)
- load_review_dimensions / get_review_dimensions / get_wiki_keywords: 对外 API
- MAX_WORKER_TURNS: 常量,maxTurns 约束

加载优先级: workspace/review-rules/review-dimensions.yaml → 根目录 review-dimensions.yaml.
PECKER_STRICT_YAML=1 时 schema 校验失败 fail-fast,不降级。

step 3.2 (2026-04-27) 重构要点:
- 删 `_DEFAULT_REVIEW_DIMENSIONS` / `_DEFAULT_DIMENSION_WIKI_KEYWORDS` 硬编码 fallback
  (P0-B 暴露的反模式根因 — 与 yaml 漂移).
- yaml 缺失时新行为: 返回空 dict + warn (不再硬编码 fallback).
- PECKER_STRICT_YAML=1 时 yaml 缺失 raise (老行为保留).
- PECKER_SCHEMA_FALLBACK=1 时 yaml 缺失返回空 dict (与 SchemaRegistry 一致).
- 老 API 签名/返回格式 0 break, 内部不直接调 SchemaRegistry, 但与 registry 共享 yaml 路径常量.

parallel_review.py re-export 这些符号 (除被删的 fallback dict),现有调用方无需改动 import 路径。
"""

import os
from functools import lru_cache

import yaml

from logger import get_logger

log = get_logger("parallel")


# ============================================================
# 中文职能词映射 (日志用,对齐 web/lib/roles.ts 术语)
# ============================================================

_CN_LABEL = {
    "structure": "责编",
    "quality": "审校",
    "ai_coding": "技术编辑",
    "data_quality": "数据核对员",
}


def _cn_label(dim_or_key):
    """从 dim dict 或 dim_key 字符串取中文职能词,找不到就回退到 codename。"""
    if isinstance(dim_or_key, dict):
        # 需要拿到 key:尝试 dim 里是否有 'key' 字段,否则回退 codename
        key = dim_or_key.get("key", "")
        if key in _CN_LABEL:
            return _CN_LABEL[key]
        return dim_or_key.get("codename", "unknown")
    return _CN_LABEL.get(dim_or_key, dim_or_key)


# ============================================================
# 硬编码 fallback 已删除 (step 3.2, 2026-04-27)
# ============================================================
#
# 历史: 这里曾有 _DEFAULT_REVIEW_DIMENSIONS / _DEFAULT_DIMENSION_WIKI_KEYWORDS
# 两个硬编码 dict 作 yaml 加载失败 fallback. P0-B (2026-04-27) 暴露这是反模式根因:
# yaml 加 FN-XX/EV-XX 时, fallback 漂移忘了同步, 切到 fallback 路径 rule 直接消失.
#
# 新行为 (yaml 缺失场景):
# - 默认: 返回空 dict + warn (不再 silent 切 hardcoded). 调用方拿空 dict 不会崩,
#         但 worker 会跑出 0 条 finding, log 里立刻能看到 schema 加载警告.
# - PECKER_STRICT_YAML=1: raise (老行为保留, 严格模式).
# - PECKER_SCHEMA_FALLBACK=1: 与 SchemaRegistry 一致, 强制返回空 dict 不抛错 (dev 逃生口).

# Worker 最大对话轮次 (CC maxTurns 约束: 超过直接走文本兜底)
MAX_WORKER_TURNS = 2

_YAML_FILENAME = "review-dimensions.yaml"
# 脚本所在目录（全局 fallback 路径）— 指向仓库根目录(__file__ 在 review/,parent 才是根)
_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# review-dimensions.yaml 的 schema 定义(B2: 启动时校验,不合法 fail-fast)
_REVIEW_DIMENSIONS_SCHEMA = {
    "type": "object",
    "required": ["dimensions"],
    "properties": {
        "dimensions": {
            "type": "object",
            "minProperties": 1,
            "additionalProperties": {
                "type": "object",
                "required": ["name", "codename", "rules", "checklist"],
                "properties": {
                    "name": {"type": "string", "minLength": 1},
                    "codename": {"type": "string", "minLength": 1},
                    "model": {"type": "string", "enum": ["haiku", "sonnet", "opus"]},
                    "wiki_keywords": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "rules": {"type": "string", "minLength": 1},
                    "checklist": {
                        "type": "array",
                        "minItems": 1,
                        "items": {
                            "type": "object",
                            "required": ["rule_id", "name"],
                            "properties": {
                                "rule_id": {
                                    "type": "string",
                                    # 2026-04-27: 扩 EV- (experimental 验收标准类) + FN- (示例产品领域规则).
                                    # EV-01/EV-04 已 active (sprint Day3), FN-01/03/09 升 active 第一波.
                                    "pattern": r"^(V|RC|EV|FN)-\d+$",
                                },
                                "status": {
                                    "type": "string",
                                    "enum": ["active", "experimental", "inactive"],
                                },
                                "owner": {"type": "string"},
                                "name": {"type": "string", "minLength": 1},
                                "enabled": {"type": "boolean"},
                            },
                        },
                    },
                },
            },
        }
    },
}


# ============================================================
# YAML 加载 + 校验
# ============================================================


def _validate_review_dimensions_yaml(yaml_content, source_path):
    """使用 jsonschema 校验 review-dimensions.yaml(B2)

    校验失败时抛 ValueError,让 load_review_dimensions 处理降级;
    schema 定义在 _REVIEW_DIMENSIONS_SCHEMA。
    """
    try:
        import jsonschema
    except ImportError:
        log.warning("[config] jsonschema 未安装,跳过 YAML schema 校验")
        return
    try:
        jsonschema.validate(yaml_content, _REVIEW_DIMENSIONS_SCHEMA)
    except jsonschema.ValidationError as e:
        # 组装精简的错误路径
        path_str = "/".join(str(p) for p in e.absolute_path) or "<root>"
        raise ValueError(
            f"{source_path}: {path_str} 不合法 — {e.message}"
        ) from e


def load_review_dimensions(workspace=None):
    """从 YAML 加载评审维度配置, 支持 workspace 级覆盖 → 全局 yaml 路径.

    返回 (dimensions_dict, wiki_keywords_dict).

    step 3.2 (2026-04-27) 行为:
    - yaml 加载成功: 同老语义, 解析成 dim/wiki dict.
    - yaml 缺失/损坏:
        * 默认: 返回 ({}, {}) + log warn (不再 silent fallback 硬编码).
        * PECKER_STRICT_YAML=1: raise (老严格模式行为保留).
        * PECKER_SCHEMA_FALLBACK=1: 强制返回 ({}, {}) 不抛错 (与 SchemaRegistry 一致逃生口).
    - wiki_keywords 不在 yaml 时, 该维度 wiki_keywords 为 [] (老语义是查 _DEFAULT_DIMENSION_WIKI_KEYWORDS,
      新语义不再有硬编码 default. 真 yaml 已配齐, 这条路径只在残缺 yaml 触发).
    """

    yaml_content = None

    # 严格模式: PECKER_STRICT_YAML=1 时 schema 校验失败直接 fail-fast 不降级
    strict = os.environ.get("PECKER_STRICT_YAML", "").lower() in ("1", "true", "yes")
    fallback_env = os.environ.get("PECKER_SCHEMA_FALLBACK", "").strip() == "1"

    tried_paths = []

    # 1. workspace 级配置优先
    if workspace:
        ws_path = os.path.join(workspace, "review-rules", _YAML_FILENAME)
        tried_paths.append(ws_path)
        if os.path.isfile(ws_path):
            try:
                with open(ws_path, "r", encoding="utf-8") as f:
                    loaded = yaml.safe_load(f)
                _validate_review_dimensions_yaml(loaded, ws_path)
                yaml_content = loaded
                log.info(f"[config] 从 workspace 加载评审维度: {ws_path}")
            except (yaml.YAMLError, OSError, ValueError) as e:
                log.warning(f"[config] workspace YAML 无效, 尝试全局路径: {e}")
                if strict:
                    raise

    # 2. 全局配置 (脚本同目录)
    if yaml_content is None:
        global_path = os.path.join(_BASE_DIR, _YAML_FILENAME)
        tried_paths.append(global_path)
        if os.path.isfile(global_path):
            try:
                with open(global_path, "r", encoding="utf-8") as f:
                    loaded = yaml.safe_load(f)
                _validate_review_dimensions_yaml(loaded, global_path)
                yaml_content = loaded
                log.info(f"[config] 从全局路径加载评审维度: {global_path}")
            except (yaml.YAMLError, OSError, ValueError) as e:
                log.warning(f"[config] 全局 YAML 无效: {e}")
                if strict:
                    raise

    # 3. yaml 缺失 fallback
    # step 3.2 反模式清理: 不再回硬编码 _DEFAULT_REVIEW_DIMENSIONS,
    # 改与 SchemaRegistry 行为对齐 (空 dict + warn / strict raise / fallback env 强制空).
    if yaml_content is None or "dimensions" not in yaml_content:
        if strict and not fallback_env:
            # 严格模式: 显式 raise, caller 看得见 (例如 server 启动期 yaml 损坏)
            raise ValueError(
                f"[schema] review-dimensions.yaml 加载失败 — 路径全部缺失/损坏: {tried_paths}. "
                f"修 yaml 或 export PECKER_SCHEMA_FALLBACK=1 走空 dict 兜底."
            )
        log.warning(
            f"[schema] review-dimensions.yaml 加载失败, 返回空维度 dict (尝试路径: {tried_paths}). "
            f"如果 server 启动期看到此 warn, 请检查 yaml 是否就位 — 不再有硬编码 fallback."
        )
        return {}, {}

    # 解析 YAML 并转换为与老 schema 相同的数据结构
    dimensions = {}
    wiki_keywords = {}

    for dim_key, dim_cfg in yaml_content["dimensions"].items():
        # 过滤 enabled: false 的 checklist 项
        raw_checklist = dim_cfg.get("checklist", [])
        filtered_checklist = [
            {"rule_id": item["rule_id"], "name": item["name"]}
            for item in raw_checklist
            if item.get("enabled", True)
        ]

        dimensions[dim_key] = {
            "name": dim_cfg["name"],
            "codename": dim_cfg["codename"],
            "rules": dim_cfg["rules"].rstrip("\n"),
            "checklist": filtered_checklist,
            "model": dim_cfg.get("model", "sonnet"),
        }

        # wiki_keywords 从 YAML 中提取
        if "wiki_keywords" in dim_cfg:
            wiki_keywords[dim_key] = dim_cfg["wiki_keywords"]

    # wiki_keywords 兜底: yaml 没配的维度给空 list (新语义, 不再有硬编码 default).
    # 真 yaml 已为 4 维度全配, 这条只在残缺 yaml 触发.
    for dim_key in dimensions:
        if dim_key not in wiki_keywords:
            wiki_keywords[dim_key] = []

    return dimensions, wiki_keywords


_DEFAULT_WS_KEY = "<default>"


def _resolve_workspace_key(workspace):
    """把 workspace 参数解析成 lru_cache 的稳定 key.

    关键: 调用方不传 workspace 时不能直接用 None 做 key, 否则所有 None 调用
    都命中同一 cache entry, CLI 切 os.environ["WORKSPACE"] 后仍返回第一次
    的配置. 这里把 None 显式解析成 env 里的实际 workspace 路径(没设则用
    _DEFAULT_WS_KEY 占位)作为 cache key, 让 lru_cache 按真实路径分桶.
    """
    if workspace is not None:
        return workspace
    return os.environ.get("WORKSPACE", "") or _DEFAULT_WS_KEY


@lru_cache(maxsize=8)
def _cached_load(workspace_key):
    """按 workspace_key(已 resolve) 缓存 YAML 加载结果. workspace_key 是 str,
    _DEFAULT_WS_KEY 代表"无 workspace 上下文 / 硬编码 fallback"分支.
    替代 2026-04-23 前的模块 global (_loaded_dimensions / _loaded_wiki_keywords).
    """
    actual = None if workspace_key == _DEFAULT_WS_KEY else workspace_key
    return load_review_dimensions(actual)


def get_review_dimensions(workspace=None):
    """获取评审维度配置(带 lru_cache 按 workspace 缓存)."""
    return _cached_load(_resolve_workspace_key(workspace))[0]


def get_wiki_keywords(workspace=None):
    """获取 wiki 关键词配置(带 lru_cache 按 workspace 缓存)."""
    return _cached_load(_resolve_workspace_key(workspace))[1]


# 信鸽反馈历史文件路径.
# 优先用显式传入的 workspace 参数(多租户并发安全);
# 无参时回退到 os.environ["WORKSPACE"](单进程 CLI 兼容)。
# 注: FastAPI 并发路径必须传参,否则 2 个并发 review 会互污染 rule_perf 查询,
# 这是 2026-04-23 定位的并发 bug 的修复点。
def _get_rule_perf_history_path(workspace=None):
    if not workspace:
        workspace = os.environ.get(
            "WORKSPACE",
            os.path.join(os.path.dirname(os.path.dirname(__file__)), "workspace"),
        )
    return os.path.join(workspace, "output", "rule_performance_history.json")
