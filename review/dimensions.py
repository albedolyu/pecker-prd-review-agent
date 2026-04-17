"""评审维度配置加载 + YAML schema 校验 + 默认值 fallback.

从 parallel_review.py 拆出 (2026-04-16):
- _CN_LABEL / _cn_label: 中文职能词映射(日志用)
- _DEFAULT_REVIEW_DIMENSIONS / _DEFAULT_DIMENSION_WIKI_KEYWORDS: 硬编码 fallback
- _REVIEW_DIMENSIONS_SCHEMA: YAML schema (jsonschema 格式)
- load_review_dimensions / get_review_dimensions / get_wiki_keywords: 对外 API
- MAX_WORKER_TURNS: 常量,maxTurns 约束

加载优先级: workspace/review-rules/review-dimensions.yaml → 根目录 review-dimensions.yaml → 硬编码。
PECKER_STRICT_YAML=1 时 schema 校验失败 fail-fast,不降级。

parallel_review.py re-export 这些符号,现有调用方无需改动 import 路径。
"""

import os

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
# 硬编码默认维度定义 (YAML 加载失败 fallback)
# ============================================================

_DEFAULT_REVIEW_DIMENSIONS = {
    "structure": {
        "name": "结构层",
        "codename": "织布鸟",
        "rules": """BMAD V-02~V-06，逐条检查：

V-02 格式规范性：验证 PRD 是否遵循标准模板（标准/变体/Legacy）。
V-03 信息密度：检测对话式填充、冗余表达、重复短语。反模式：
  - "The system will allow users to..." → 直接写功能
  - "Due to the fact that" → "because"
  严重度：≥10 处 = must
V-04 Brief 覆盖率：检查 Brief → PRD 的映射完整性，识别未覆盖的 Brief 要求。
V-05 信息完整性：PRD 中引用的所有信息（字段、规则、布局）能在文档内自洽，不依赖外部未注明的文档。
V-06 可追溯链完整性：验证 愿景 → FR → 用户故事 的链路完整，不能断链。""",
        "checklist": [
            {"rule_id": "V-02", "name": "格式规范性"},
            {"rule_id": "V-03", "name": "信息密度"},
            {"rule_id": "V-04", "name": "Brief 覆盖率"},
            {"rule_id": "V-05", "name": "信息完整性"},
            {"rule_id": "V-06", "name": "可追溯链完整性"},
        ],
        "model": "sonnet",
    },
    "quality": {
        "name": "质量层",
        "codename": "猫头鹰",
        "rules": """BMAD V-07~V-12，逐条检查：

V-07 逻辑一致性：检查 PRD 内部各章节的描述是否自洽，排序规则/筛选规则/字段映射等不能互相矛盾。
V-08 实现泄漏检测：FR 不应含技术实现细节（如具体 API、框架名、SQL 语句），除非在技术约定节中。
V-09 SMART 验证：成功标准须满足 SMART 原则 — Specific（具体明确）、Measurable（可量化）、Attainable（可实现）、Relevant（与目标相关）、Traceable（可追踪）。
V-10 领域合规性：检查 PRD 是否符合业务领域的法规和合规要求。
V-11 整体质量评估：综合评价 PRD 的完整性、一致性和可操作性。
V-12 完整性评估：检查是否有遗漏的核心功能模块、边界条件、异常处理。""",
        "checklist": [
            {"rule_id": "V-07", "name": "逻辑一致性"},
            {"rule_id": "V-08", "name": "实现泄漏检测"},
            {"rule_id": "V-09", "name": "SMART 验证"},
            {"rule_id": "V-10", "name": "领域合规性"},
            {"rule_id": "V-11", "name": "整体质量评估"},
            {"rule_id": "V-12", "name": "完整性评估"},
        ],
        "model": "sonnet",
    },
    "ai_coding": {
        "name": "AI Coding 友好度",
        "codename": "渡鸦",
        "rules": """RC-004~RC-008, RC-013~RC-015，逐条检查：

RC-004 技术约定节存在（must）：PRD 必须包含技术约定节（框架/鉴权方式/基础路径），不能依赖外部文档独立支撑开发。
RC-005 四态 UI 规范已定义（must）：PRD 必须定义加载中/请求失败/筛选无结果/空数据四种 UI 状态的文案与样式。
RC-006 图片路径使用相对路径（should）：PRD 中引用的图片应使用相对路径，避免绝对路径导致协作问题。
RC-007 复杂联动逻辑有伪代码（should）：复杂联动逻辑、非结构化文本处理等必须有伪代码或流程描述。
RC-008 筛选追溯完整（must）：筛选/查询逻辑须从用户操作追溯到 WHERE 条件，中间无断点；非常规逻辑（继承/降级/空值）需有具体示例覆盖。
RC-013 伪代码字段可追溯（must）：伪代码中每个字段均可在 DDL 中找到；跨表字段标注 JOIN 来源。
RC-014 筛选逻辑追溯到 WHERE（must）：筛选/查询逻辑从用户操作追溯到 WHERE 条件，中间无断点。
RC-015 非常规逻辑有示例（should）：非常规逻辑（继承/降级/空值）须有具体示例覆盖。""",
        "checklist": [
            {"rule_id": "RC-004", "name": "技术约定节存在"},
            {"rule_id": "RC-005", "name": "四态 UI 规范已定义"},
            {"rule_id": "RC-006", "name": "图片路径使用相对路径"},
            {"rule_id": "RC-007", "name": "复杂联动逻辑有伪代码"},
            {"rule_id": "RC-008", "name": "筛选追溯完整"},
            {"rule_id": "RC-013", "name": "伪代码字段可追溯"},
            {"rule_id": "RC-014", "name": "筛选逻辑追溯到 WHERE"},
            {"rule_id": "RC-015", "name": "非常规逻辑有示例"},
        ],
        "model": "opus",  # 需要深度推理
    },
    "data_quality": {
        "name": "数据质量",
        "codename": "鸬鹚",
        "rules": """RC-009~RC-010，逐条检查：

RC-009 字段映射一致性（must）：字段映射表中字段名与物理表 DDL 一致；跨表字段须标注 JOIN 来源和优先级。
RC-010 数值类字段标注来源（must）：数值类字段（分页数/导出上限/阈值）须标注来源或标注 TBD；跨表字段须说明空值降级处理。""",
        "checklist": [
            {"rule_id": "RC-009", "name": "字段映射一致性"},
            {"rule_id": "RC-010", "name": "数值类字段标注来源"},
        ],
        "model": "sonnet",  # haiku 对复杂字段映射判定不够稳定，升级到 sonnet
    },
}

_DEFAULT_DIMENSION_WIKI_KEYWORDS = {
    "structure": ["模板", "格式", "规范", "brief", "结构", "追溯"],
    "quality": ["逻辑", "一致", "合规", "SMART", "完整", "质量"],
    "ai_coding": ["技术", "UI", "伪代码", "字段", "筛选", "DDL", "coding", "开发"],
    "data_quality": ["字段", "映射", "DDL", "数值", "数据", "JOIN"],
}

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
                                    "pattern": r"^(V|RC)-\d+$",
                                },
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


# 运行时加载的维度配置（首次使用时初始化）
_loaded_dimensions = None
_loaded_wiki_keywords = None


def load_review_dimensions(workspace=None):
    """从 YAML 加载评审维度配置，支持 workspace 级覆盖 → 全局 fallback → 硬编码默认值。
    返回 (dimensions_dict, wiki_keywords_dict)"""

    yaml_content = None

    # 严格模式:PECKER_STRICT_YAML=1 时 schema 校验失败直接 fail-fast 不降级
    strict = os.environ.get("PECKER_STRICT_YAML", "").lower() in ("1", "true", "yes")

    # 1. workspace 级配置优先
    if workspace:
        ws_path = os.path.join(workspace, "review-rules", _YAML_FILENAME)
        if os.path.isfile(ws_path):
            try:
                with open(ws_path, "r", encoding="utf-8") as f:
                    loaded = yaml.safe_load(f)
                _validate_review_dimensions_yaml(loaded, ws_path)
                yaml_content = loaded
                log.info(f"[config] 从 workspace 加载评审维度: {ws_path}")
            except (yaml.YAMLError, OSError, ValueError) as e:
                log.warning(f"[config] workspace YAML 无效,降级: {e}")
                if strict:
                    raise

    # 2. 全局配置（脚本同目录）
    if yaml_content is None:
        global_path = os.path.join(_BASE_DIR, _YAML_FILENAME)
        if os.path.isfile(global_path):
            try:
                with open(global_path, "r", encoding="utf-8") as f:
                    loaded = yaml.safe_load(f)
                _validate_review_dimensions_yaml(loaded, global_path)
                yaml_content = loaded
                log.info(f"[config] 从全局路径加载评审维度: {global_path}")
            except (yaml.YAMLError, OSError, ValueError) as e:
                log.warning(f"[config] 全局 YAML 无效,降级到硬编码: {e}")
                if strict:
                    raise

    # 3. 硬编码默认值 fallback
    if yaml_content is None or "dimensions" not in yaml_content:
        log.info("[config] 使用硬编码默认评审维度")
        return _DEFAULT_REVIEW_DIMENSIONS, _DEFAULT_DIMENSION_WIKI_KEYWORDS

    # 解析 YAML 并转换为与硬编码相同的数据结构
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

    # 如果 YAML 中没有 wiki_keywords，用默认值补全
    for dim_key in dimensions:
        if dim_key not in wiki_keywords:
            wiki_keywords[dim_key] = _DEFAULT_DIMENSION_WIKI_KEYWORDS.get(dim_key, [])

    return dimensions, wiki_keywords


def get_review_dimensions(workspace=None):
    """获取评审维度配置（带缓存），首次调用时从 YAML 加载"""
    global _loaded_dimensions, _loaded_wiki_keywords
    if _loaded_dimensions is None:
        _loaded_dimensions, _loaded_wiki_keywords = load_review_dimensions(workspace)
    return _loaded_dimensions


def get_wiki_keywords(workspace=None):
    """获取 wiki 关键词配置（带缓存），首次调用时从 YAML 加载"""
    global _loaded_dimensions, _loaded_wiki_keywords
    if _loaded_wiki_keywords is None:
        _loaded_dimensions, _loaded_wiki_keywords = load_review_dimensions(workspace)
    return _loaded_wiki_keywords
