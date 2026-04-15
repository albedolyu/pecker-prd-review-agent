"""
并行评审模块 -- 啄木鸟 Phase 2 的四维度并行评审 Workers
功能：
  1. 四个评审维度并行调用 Messages API
  2. 结构化输出 tool schema（submit_review_items）
  3. 依据验证（Side Query）
  4. 合并去重
"""

import asyncio
import json
import os
import random
import re
import time
import glob as glob_module
from difflib import SequenceMatcher

import yaml

from logger import get_logger

log = get_logger("parallel")

from datetime import datetime


def _add_freshness_note(wiki_page_path, content):
    """给 wiki 页面加新鲜度标记（CC memoryAge.ts:33-42 模式）"""
    try:
        mtime = os.path.getmtime(wiki_page_path)
        days = (time.time() - mtime) / 86400
        if days > 7:
            return f"[此页面 {int(days)} 天未更新，内容可能过时，请交叉验证]\n\n{content}"
        elif days > 1:
            return f"[更新于 {int(days)} 天前]\n\n{content}"
    except OSError:
        pass
    return content


def build_wiki_manifest(wiki_pages, wiki_path=None):
    """构建 wiki 页面清单（CC extractMemories manifest 模式）"""
    lines = []
    for title, content in wiki_pages.items():
        mtime_str = ""
        if wiki_path:
            fpath = os.path.join(wiki_path, f"{title}.md")
            try:
                mtime = os.path.getmtime(fpath)
                mtime_str = f" ({datetime.fromtimestamp(mtime).strftime('%Y-%m-%d')})"
            except OSError:
                pass
        desc = content[:80].replace("\n", " ").strip()
        lines.append(f"- {title}{mtime_str}: {desc}")
    return "\n".join(lines)


# 信鸽反馈历史文件路径（延迟解析，避免在 import 时读不到 WORKSPACE 环境变量）
def _get_rule_perf_history_path():
    workspace = os.environ.get("WORKSPACE", os.path.join(os.path.dirname(__file__), "workspace"))
    return os.path.join(workspace, "output", "rule_performance_history.json")

# ============================================================
# 评审维度定义
# ============================================================

# 中文职能词映射 — 日志输出用,对齐 web/lib/roles.ts 的 UI 术语约定
# (鸟名 codename 仍保留为数据字段,向后兼容 + 彩蛋品牌)
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

# YAML 配置文件名
_YAML_FILENAME = "review-dimensions.yaml"
# 脚本所在目录（全局 fallback 路径）
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))

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

# ============================================================
# 结构化输出 Tool Schema
# ============================================================

SUBMIT_REVIEW_ITEMS_TOOL = {
    "name": "submit_review_items",
    "description": (
        "提交评审中发现的问题项。逐条检查 checklist 后,仅提交 fail 的规则。"
        "全部 pass 时,items 必须为空数组,同时 null_finding_reason 必须填写说明你已逐条看过"
        "(缺失 ④ Worker 拒答出口:允许承认 PRD 这一维度无问题,而不是硬找)。"
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "dimension": {"type": "string", "description": "评审维度"},
            "items": {
                "type": "array",
                "description": (
                    "仅提交发现问题的规则项。同一规则在多处违反时可提交多条"
                    "(rule_id 相同但 location 不同)。如果全部规则都通过则提交空数组。"
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "rule_id": {"type": "string", "description": "规则编号如 V-02, RC-005"},
                        "location": {"type": "string", "description": "PRD 中的章节"},
                        "issue": {"type": "string", "description": "具体问题"},
                        "suggestion": {"type": "string", "description": "改进建议"},
                        "severity": {"type": "string", "enum": ["must", "should"]},
                        "evidence_type": {"type": "string", "enum": ["A", "B", "C"]},
                        "evidence_content": {"type": "string", "description": "依据内容"},
                    },
                    "required": ["rule_id", "location", "issue", "suggestion", "severity", "evidence_type", "evidence_content"],
                },
            },
            "confidence_in_findings": {
                "type": "number",
                "minimum": 0.0,
                "maximum": 1.0,
                "description": (
                    "你对本次发现的整体置信度 0.0-1.0。如果 PRD 这一维度看完不确定有问题,"
                    "降低置信度;不要为了凑数硬找。"
                ),
                "default": 1.0,
            },
            "null_finding_reason": {
                "type": "string",
                "description": (
                    "items 为空时必填:简述你为什么认为本维度无 fail(逐条扫了哪些规则,"
                    "为什么都 pass)。这是缺失 ④ 的 Worker 拒答出口,胡乱拒答会被苍鹰反驳。"
                    "items 非空时此字段可为空。"
                ),
                "default": "",
            },
        },
        "required": ["dimension", "items"],
    },
}

# ============================================================
# Worker System Prompt 模板
# ============================================================

_WORKER_SHARED_RULES = """## 评审要求
1. 仔细阅读 PRD 内容和相关知识库页面
2. **严格只评审你 owner=自己 的规则** — 缺失 ② Worker 边界互斥:
   review-dimensions.yaml 给每条规则标了 owner,你只输出 owner=本维度的 fail。
   即使你看到其他维度的 owner 的规则违反,也禁止报告(那条规则会被对应 worker 处理)。
   越界报告会被苍鹰交叉校验降权 + 杜鹃 verdict 扣分。
3. 逐条对照检查清单,每条规则都要检查
4. 同一条规则如果在多个位置违反,每个位置单独提交一条(rule_id 相同但 location 不同)
5. 每条改进项必须有明确依据(A=内部知识, B=评审规则, C=外部参考)
6. 找不到依据的改动不得提出
7. **允许承认无问题** — 缺失 ④ Worker 拒答出口:
   如果本维度逐条看完没发现 fail,提交空 items 数组并填写 null_finding_reason 说明
   你扫了哪些规则、为什么都 pass。**禁止为了凑数硬找问题**。
8. 评审完成后,使用 submit_review_items 工具提交

## 依据分类
- A(内部知识):引用 wiki 页面,**严格使用 [[页面名]] 双方括号格式**,页面名必须在
  refs 清单中精确匹配(见后面的真实依据清单)。禁止使用《》书名号或其他括号。
- B(评审规则):引用规则编号和原文(RC-XXX 或 V-XX,必须在 refs 清单中)
- C(外部参考):竞品/行业惯例,**必须**标记「⚠️ 待确定」或「外部参考」字样

## 严重度
- must:必须修改,不改会导致 PRD 无法正确指导开发
- should:建议修改,改了会提升 PRD 质量"""

_WORKER_SYSTEM_TEMPLATE = """你是「{codename}」，啄木鸟评审团的 {dimension_name} 评审员。

## 你的逐条打分清单
{dimension_rules}

## 必须打分的规则列表
{checklist_list}

{shared_rules}
"""


def _build_worker_system(dim_key, rule_perf_history=None, dimensions=None, workspace=None):
    """为某个评审维度构建 system prompt，并动态注入：
    1. 信鸽反馈的高发问题规则（rule_perf_history）
    2. workspace 中的真实 rule_id / wiki 页面清单（防止 evidence 造假，借鉴百灵 load_real_imports）
    """
    dims = dimensions or get_review_dimensions()
    dim = dims[dim_key]

    # 构建 checklist 列表文本，明确告诉模型必须打分哪些规则
    checklist_lines = []
    for rule in dim["checklist"]:
        checklist_lines.append(f"- {rule['rule_id']}（{rule['name']}）")
    checklist_text = "\n".join(checklist_lines)

    base_prompt = _WORKER_SYSTEM_TEMPLATE.format(
        codename=dim["codename"],
        dimension_name=dim["name"],
        dimension_rules=dim["rules"],
        checklist_list=checklist_text,
        shared_rules=_WORKER_SHARED_RULES,
    )

    # --- 动态注入信鸽反馈 ---
    feedback_section = _build_feedback_section(dim_key, rule_perf_history, dims)
    if feedback_section:
        base_prompt += "\n" + feedback_section

    # --- 动态注入真实依据清单（防止 evidence 造假，对应路线图 B1 前置） ---
    refs_section = _build_real_refs_section(workspace)
    if refs_section:
        base_prompt += "\n" + refs_section

    return base_prompt


def _build_feedback_section(dim_key, rule_perf_history=None, dimensions=None):
    """从已加载的 history 中筛选当前维度的高发问题规则"""
    if rule_perf_history is None:
        try:
            with open(_get_rule_perf_history_path(), "r", encoding="utf-8") as f:
                rule_perf_history = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return ""

    if not isinstance(rule_perf_history, dict):
        return ""

    # 2. 提取当前维度涉及的规则编号
    dims = dimensions or get_review_dimensions()
    dim_rules_text = dims[dim_key]["rules"]
    dim_rule_ids = set(re.findall(r"(?:RC-\d+|V-\d+)", dim_rules_text))
    if not dim_rule_ids:
        return ""

    # 3. 筛选异常规则：rejection_rate > 0.3 或 missed > 2 或 eval precision/recall 过低
    flagged = []
    for rule_id, stats in rule_perf_history.items():
        if not isinstance(stats, dict):
            continue
        # 规则编号归一化匹配（history 中可能是 "RC-005" 或 "V-07"）
        canonical = rule_id.strip()
        if canonical not in dim_rule_ids:
            continue

        rejection_rate = stats.get("rejection_rate", 0)
        missed = stats.get("stats", {}).get("missed", 0)

        # F2: 同时考虑 eval_metrics 中的 precision/recall
        eval_m = stats.get("eval_metrics") or {}
        eval_precision = eval_m.get("precision", 1.0)
        eval_recall = eval_m.get("recall", 1.0)
        eval_has_data = bool(eval_m)  # 有数据才参与判断

        triggers = (
            rejection_rate > 0.3
            or missed > 2
            or (eval_has_data and eval_precision < 0.6)
            or (eval_has_data and eval_recall < 0.6)
        )

        if triggers:
            flagged.append({
                "rule_id": canonical,
                "rejection_rate": rejection_rate,
                "missed": missed,
                "name": stats.get("name", ""),
                "recent_total": stats.get("stats", {}).get("total", 0),
                "eval_precision": eval_precision if eval_has_data else None,
                "eval_recall": eval_recall if eval_has_data else None,
            })

    if not flagged:
        return ""

    # 4. 按 missed + rejection_rate + 1-precision 综合排序，取前 5 条
    def _severity(r):
        p = r["eval_precision"] if r["eval_precision"] is not None else 1.0
        return (r["missed"], r["rejection_rate"], 1.0 - p)
    flagged.sort(key=_severity, reverse=True)
    flagged = flagged[:5]

    # 5. 生成提示文本
    lines = ["## 近期反馈提示", "以下规则在最近的评审中表现异常，请加强审核："]
    for r in flagged:
        parts = []
        if r["name"]:
            label = f"{r['rule_id']}（{r['name']}）"
        else:
            label = r["rule_id"]

        if r["missed"] > 2:
            parts.append(f"漏报率高，近 {r.get('recent_total', '?')} 次评审中 {r['missed']} 次未检出")
        if r["rejection_rate"] > 0.3:
            pct = int(r["rejection_rate"] * 100)
            parts.append(f"驳回率 {pct}%，建议仅在有充分依据时提出")
        if r["eval_precision"] is not None and r["eval_precision"] < 0.6:
            parts.append(f"Eval 精确率 {int(r['eval_precision']*100)}%，降低误报")
        if r["eval_recall"] is not None and r["eval_recall"] < 0.6:
            parts.append(f"Eval 召回率 {int(r['eval_recall']*100)}%，加强检出")

        lines.append(f"- {label}：{'；'.join(parts)}")

    return "\n".join(lines) + "\n"


def _build_real_refs_section(workspace):
    """扫 workspace 的真实 rule_id 和 wiki 页面清单注入 Worker prompt。

    借鉴百灵（riskbird_test_agent.load_real_imports）的防 FQN 幻觉策略：
    LLM 倾向于编造不存在的规则号和 wiki 引用，明确给出可用清单后显著降低幻觉率。

    配合 review_fixer.fix_review_items 使用——生成后如果 evidence 仍指向清单外的
    规则或页面，verify_evidence 会标记 verification_status=failed 并降权。
    """
    if not workspace or not os.path.isdir(workspace):
        return ""

    # 1. 扫 review-rules/ 抽所有 rule_id
    rule_ids = set()
    rules_dir = os.path.join(workspace, "review-rules")
    if os.path.isdir(rules_dir):
        for root, _, files in os.walk(rules_dir):
            for fn in files:
                if fn.endswith((".md", ".yaml", ".yml", ".txt")):
                    try:
                        fp = os.path.join(root, fn)
                        with open(fp, "r", encoding="utf-8") as f:
                            text = f.read()
                        rule_ids.update(re.findall(r"(?:RC-\d+|V-\d+)", text))
                    except (OSError, UnicodeDecodeError):
                        continue

    # 2. 扫 wiki/ 抽所有页面名(去 .md 扩展名,排除隐藏文件)
    # 缺失 ⑤ A 类新鲜度: 同时记录 mtime,按 30/90/180 天分级标注,worker 自然会偏好新页面
    import time as _time
    now_ts = _time.time()
    wiki_pages = []  # [(name, age_days)]
    wiki_dir = os.path.join(workspace, "wiki")
    if os.path.isdir(wiki_dir):
        for fn in sorted(os.listdir(wiki_dir)):
            if fn.endswith(".md") and not fn.startswith("."):
                fp = os.path.join(wiki_dir, fn)
                try:
                    mtime = os.path.getmtime(fp)
                    age_days = int((now_ts - mtime) / 86400)
                except OSError:
                    age_days = 0
                wiki_pages.append((fn[:-3], age_days))

    if not rule_ids and not wiki_pages:
        return ""

    lines = [
        "## 真实依据清单（强制复用）",
        "以下清单由 workspace 扫描生成。verify_evidence 会对每条 item 的依据做硬验证：",
        "引用清单外的 rule_id 或 wiki 页面 → 标记 verification_status=failed → confidence_score 降权 50%。",
        "",
        "### 依据格式铁律（违反即 FAIL）",
        "",
        "- **B 类**：`evidence_content` 必须包含 `RC-\\d+` 或 `V-\\d+` 格式的真实规则号（从下表选），禁止只写规则描述。",
        "- **A 类**：`evidence_content` 必须包含 `[[页面名]]` 双方括号格式引用，**禁止使用《》书名号、「」、引号或其他符号**。页面名必须与下表精确一致。",
        "- **C 类**：竞品/行业/经验，必须在 `evidence_content` 里明确标注 `⚠️ 待确定` 或 `外部参考`，否则算 C 类违规。",
        "- **如果你想引用的规则/页面不在下表中**：降级为 C 类 + `⚠️ 待确定`，不要强行用 A/B 造假。",
        "",
    ]

    if rule_ids:
        lines.append(f"### 可用规则编号（{len(rule_ids)} 条，仅用于 evidence_type=B）")
        lines.append("")
        # 分行显示更紧凑,每行 5 个
        sorted_rules = sorted(rule_ids)
        for i in range(0, len(sorted_rules), 5):
            lines.append("  " + "  ".join(f"`{r}`" for r in sorted_rules[i:i+5]))
        lines.append("")

    if wiki_pages:
        lines.append(f"### 可用 wiki 页面({len(wiki_pages)} 条,仅用于 evidence_type=A)")
        lines.append("")
        lines.append("**正例**:`**依据**: [A] [[约束-接口命名规范]] 第 3 节约定所有 endpoint 必须 /api/v1 前缀`")
        lines.append("**反例**:`**依据**: [A] 知识库《约束-接口命名规范》...`  <- 书名号会被判 failed")
        lines.append("**反例**:`**依据**: [A] [[不存在的页面]]`  <- 页面不在下表会被判 failed")
        lines.append("")
        lines.append("**新鲜度标注** (缺失 ⑤): `🟢 新鲜` <30天 / `🟡 一般` 30-90天 / `🟠 旧` 90-180天 / `🔴 过期` >180天")
        lines.append("过期的 wiki 页面优先级低,如果新页面也能引用,优先用新的。")
        lines.append("")
        for p, age_days in wiki_pages:
            if age_days < 30:
                badge = "🟢"
            elif age_days < 90:
                badge = "🟡"
            elif age_days < 180:
                badge = "🟠"
            else:
                badge = "🔴"
            lines.append(f"- {badge} `[[{p}]]` ({age_days}d)")
        lines.append("")

    return "\n".join(lines)


def _build_worker_messages(prd_content, wiki_pages, dim_key=None, wiki_path=None, wiki_keywords=None, diff_context=None):
    """构建 worker 的 user messages，包含 PRD 和知识库内容"""
    wk = wiki_keywords or get_wiki_keywords()
    parts = [f"## 待评审 PRD\n\n{prd_content}"]
    if diff_context:
        parts.insert(0, diff_context)  # diff context before PRD content
    if wiki_pages:
        # 按维度筛选相关 wiki 页面，减少无关上下文
        if dim_key and dim_key in wk:
            keywords = wk[dim_key]
            relevant = {t: c for t, c in wiki_pages.items()
                        if any(kw in t for kw in keywords)}
            filtered = relevant if relevant else wiki_pages
        else:
            filtered = wiki_pages
        parts.append("## 相关知识库页面\n")
        for title, content in filtered.items():
            # 加新鲜度标记（CC memoryAge 模式）
            if wiki_path:
                fpath = os.path.join(wiki_path, f"{title}.md")
                content = _add_freshness_note(fpath, content)
            parts.append(f"### {title}\n{content}\n")
    parts.append("请评审以上 PRD，逐条对照你的检查清单，然后调用 submit_review_items 工具提交发现的所有改进项。每条改进项必须标注 rule_id。")
    return [{"role": "user", "content": "\n\n".join(parts)}]


# ============================================================
# 单个 Worker 调用
# ============================================================

def _extract_items_from_response(response):
    """从 Messages API 响应中提取所有 submit_review_items 的 tool_use 结果"""
    all_items = []
    for block in response.content:
        if block.type == "tool_use" and block.name == "submit_review_items":
            items = block.input.get("items", [])
            # 中转站大 payload 修复：items 可能被拆成字符数组，拼接后重新解析
            if items and isinstance(items[0], str) and len(items) > 10:
                try:
                    joined = "".join(items)
                    # 确保是有效的 JSON 数组
                    if not joined.strip().startswith("["):
                        joined = "[" + joined + "]"
                    parsed = json.loads(joined)
                    if isinstance(parsed, list):
                        items = parsed
                        log.info(f"修复字符数组: {len(items)} chars → {len(parsed)} items")
                except (json.JSONDecodeError, TypeError):
                    log.warning(f"字符数组修复失败，尝试提取 JSON 对象")
                    # 兜底：从拼接字符串中提取所有 JSON 对象
                    import re as _re
                    objects = _re.findall(r'\{[^{}]*\}', joined)
                    items = []
                    for obj_str in objects:
                        try:
                            items.append(json.loads(obj_str))
                        except json.JSONDecodeError:
                            continue
            all_items.extend(items)
    # 统一编号（过滤非 dict 元素）
    all_items = [item for item in all_items if isinstance(item, dict)]
    # B4: 给 Worker 产出的 item 打上 confidence_score,让 merge/伯劳能消费
    from cuckoo_parser import compute_confidence
    for i, item in enumerate(all_items, 1):
        if "id" not in item:
            item["id"] = f"R-{i:03d}"
        if "confidence_score" not in item:
            item["confidence_score"] = compute_confidence(item.get("evidence_type", ""))
    return all_items


def _has_tool_use(response):
    """检查响应中是否包含 tool_use block"""
    return any(block.type == "tool_use" for block in response.content)


def _extract_text(response):
    """从响应中提取纯文本"""
    return "\n".join(block.text for block in response.content if block.type == "text")


def _parse_items_from_text(text):
    """兜底：从纯文本中提取 JSON 格式的改进项（模型没调 tool 时）"""
    import re as _re
    from cuckoo_parser import compute_confidence  # B4
    # 尝试提取 JSON 数组
    m = _re.search(r'\[[\s\S]*?\]', text)
    if m:
        try:
            items = json.loads(m.group())
            if isinstance(items, list) and items:
                for i, item in enumerate(items, 1):
                    if isinstance(item, dict):
                        if "id" not in item:
                            item["id"] = f"R-{i:03d}"
                        if "confidence_score" not in item:
                            item["confidence_score"] = compute_confidence(item.get("evidence_type", ""))
                return items
        except (json.JSONDecodeError, TypeError):
            pass
    return []


def _worker_core(client, dim_key, prd_content, wiki_pages, model_tiers, rule_perf_history=None, wiki_path=None, diff_context=None):
    """Worker 核心逻辑（sync），返回首次 API 响应和处理后的 items 列表。
    async 版本通过 run_in_executor 包装此函数。"""
    dimensions = get_review_dimensions()
    wiki_keywords = get_wiki_keywords()
    dim = dimensions[dim_key]
    model = model_tiers.get(dim["model"], model_tiers["sonnet"])
    # 从 wiki_path 反推 workspace(wiki_path 总是 workspace/wiki),注入真实依据清单防幻觉
    workspace_dir = os.path.dirname(wiki_path) if wiki_path else None
    dynamic_system = _build_worker_system(dim_key, rule_perf_history, dimensions, workspace=workspace_dir)
    messages = _build_worker_messages(prd_content, wiki_pages, dim_key, wiki_path, wiki_keywords, diff_context)

    # CC 模式：system prompt 分静态/动态两段（参考 prompts.ts:560 的 DYNAMIC_BOUNDARY）
    # 静态段（共享规则）打 cache_control，4 个 worker 共享缓存
    # 动态段（维度规则 + 反馈注入）不缓存
    system_blocks = [
        {"type": "text", "text": _WORKER_SHARED_RULES, "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": dynamic_system},
    ]

    def _call(msgs):
        return client.create(
            model=model,
            max_tokens=8192,
            system=system_blocks,
            messages=msgs,
            tools=[SUBMIT_REVIEW_ITEMS_TOOL],
            tool_choice={"type": "any"},
            retry_policy="worker",
        )

    # client.create 内部已有分级重试，不再外层重复
    response = _call(messages)

    items = _extract_items_from_response(response)

    # Tool 调用检测 + 催促重试 + 文本兜底
    if not _has_tool_use(response):
        log.warning(f"[{_cn_label(dim_key)}] 未调用 tool，催促重试")
        text = _extract_text(response)
        followup_msgs = messages + [
            {"role": "assistant", "content": text},
            {"role": "user", "content": "请使用 submit_review_items 工具提交你的评审结果。"},
        ]
        time.sleep(2 + random.uniform(0, 0.5))
        try:
            response2 = _call(followup_msgs)
            items = _extract_items_from_response(response2)
            if _has_tool_use(response2):
                response = response2
        except Exception:
            pass

        if not items and text:
            items = _parse_items_from_text(text)
            if items:
                log.info(f"[{_cn_label(dim_key)}] 从文本中解析出 {len(items)} 条改进项")

    # 过滤非 dict 元素（模型偶尔返回字符串数组而非对象数组）
    items = [item for item in items if isinstance(item, dict)]

    for item in items:
        item["dimension"] = dim["name"]

    # 提取 worker 发现的关键规则 ID（供 scratchpad 跨 worker 共享）
    found_rule_ids = list(set(item.get("rule_id", "") for item in items if item.get("rule_id")))

    return {
        "dimension": dim_key,
        "dimension_name": dim["name"],
        "model": model,
        "items": items,
        "found_rule_ids": found_rule_ids,
        "usage": {
            "input_tokens": response.usage["input_tokens"],
            "output_tokens": response.usage["output_tokens"],
        },
    }


async def _run_worker_async(client, dim_key, prd_content, wiki_pages, model_tiers, rule_perf_history=None, wiki_path=None, diff_context=None):
    """异步包装：在线程池中执行 _worker_core，带超时保护"""
    from agent_config import WORKER_TIMEOUT
    loop = asyncio.get_running_loop()
    try:
        return await asyncio.wait_for(
            loop.run_in_executor(
                None, lambda: _worker_core(client, dim_key, prd_content, wiki_pages, model_tiers, rule_perf_history, wiki_path, diff_context)
            ),
            timeout=WORKER_TIMEOUT,
        )
    except asyncio.TimeoutError:
        # 超时 Worker 不抛出,返回错误结构,让 gather 正常汇总其他 Worker 结果
        dim_name = get_review_dimensions().get(dim_key, {}).get("name", dim_key)
        log.warning(f"[{_cn_label(dim_key)}] Worker 超时({WORKER_TIMEOUT}s),跳过")
        return {
            "dimension": dim_key,
            "dimension_name": dim_name,
            "error": f"Worker 超时({WORKER_TIMEOUT}s)",
            "items": [],
            "usage": {"input_tokens": 0, "output_tokens": 0},
            "status": "timeout",
        }


def _run_worker_sync(client, dim_key, prd_content, wiki_pages, model_tiers, rule_perf_history=None, wiki_path=None, diff_context=None):
    """同步包装：直接调用 _worker_core"""
    return _worker_core(client, dim_key, prd_content, wiki_pages, model_tiers, rule_perf_history, wiki_path, diff_context)




# ============================================================
# 并行评审主函数
# ============================================================

async def _single_round_async(client, prd_content, wiki_pages, model_tiers, wiki_path=None, diff_context=None, on_worker_done=None):
    """单轮并行评审（内部函数），返回 workers, merged_items, usage

    Args:
        on_worker_done: 可选 callback,签名为 (dim_key: str, result: dict) -> None
            每个 worker 完成时(成功或失败)都会调用,让上层(FastAPI SSE)感知进度。
            默认 None,保持向后兼容,CLI 现有流程零影响。
    """
    dimensions = get_review_dimensions()

    # 读一次 rule performance history，传给所有 worker（避免 4 次 I/O）
    rule_perf_history = None
    try:
        with open(_get_rule_perf_history_path(), "r", encoding="utf-8") as f:
            rule_perf_history = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass

    # 错峰启动: Windows 下 4 个 claude CLI 子进程同时启动会触发 Node.js libuv assertion
    # (UV_HANDLE_CLOSING / 0xC0000409 STATUS_STACK_BUFFER_OVERRUN),给每个 worker 加 stagger
    async def _staggered(idx, dim_key):
        await asyncio.sleep(idx * 0.5)
        try:
            result = await _run_worker_async(
                client, dim_key, prd_content, wiki_pages, model_tiers, rule_perf_history, wiki_path, diff_context
            )
            # 新增: worker 完成后通知外层(FastAPI SSE 用,CLI 模式下 callback 为 None 就跳过)
            if on_worker_done is not None:
                try:
                    on_worker_done(dim_key, result)
                except Exception:
                    pass  # callback 异常绝不影响主流程
            return result
        except Exception as e:
            # 失败也要通知,这样 UI 能显示 worker 失败状态而不是永远挂 pending
            if on_worker_done is not None:
                try:
                    on_worker_done(dim_key, {"error": str(e)[:200]})
                except Exception:
                    pass
            raise

    tasks = [
        _staggered(idx, dim_key)
        for idx, dim_key in enumerate(dimensions)
    ]

    # 总体超时兜底:即使单 Worker 超时被捕获,线程池层面仍可能因极端情况拖住
    from agent_config import TOTAL_REVIEW_TIMEOUT
    try:
        results = await asyncio.wait_for(
            asyncio.gather(*tasks, return_exceptions=True),
            timeout=TOTAL_REVIEW_TIMEOUT,
        )
    except asyncio.TimeoutError:
        # 外层 deadman switch 触发,把未完成的任务占位为 timeout 错误
        log.error(f"并行评审总体超时({TOTAL_REVIEW_TIMEOUT}s),强制结束")
        results = [
            asyncio.TimeoutError(f"总体超时({TOTAL_REVIEW_TIMEOUT}s)")
            for _ in tasks
        ]

    workers = []
    all_items = []
    total_input = 0
    total_output = 0

    failed_dims = []
    api_unavailable = False
    for dim_key, result in zip(dimensions, results):
        if isinstance(result, Exception):
            err_msg = str(result)
            log.warning(f"[{_cn_label(dim_key)}] Worker 失败: {err_msg[:80]}")
            failed_dims.append(dim_key)
            workers.append({
                "dimension": dim_key,
                "dimension_name": dimensions[dim_key]["name"],
                "error": err_msg,
                "items": [],
            })
            if "503" in err_msg or "No available account" in err_msg or "upstream_error" in err_msg:
                api_unavailable = True
        else:
            workers.append(result)
            all_items.extend(result["items"])
            total_input += result["usage"]["input_tokens"]
            total_output += result["usage"]["output_tokens"]

    # API 不可用时给出明确提示，不要报"过多 Worker 失败"
    if api_unavailable and len(failed_dims) > 1:
        raise RuntimeError(f"API 不可用（503），请检查中转站额度后重试")

    # 允许最多 1 个 worker 失败，超过则报错
    if len(failed_dims) > 1:
        raise RuntimeError(f"过多 Worker 失败 ({len(failed_dims)}/4): {failed_dims}")

    # Scratchpad：记录各 worker 发现的规则 ID（CC coordinatorMode.ts 的 scratchpad 模式）
    scratchpad = {}
    for w in workers:
        if "error" not in w or not w.get("error"):
            dim = w.get("dimension", "")
            scratchpad[dim] = {
                "found_rule_ids": w.get("found_rule_ids", []),
                "item_count": len(w.get("items", [])),
            }

    merged = merge_and_deduplicate(all_items)
    return workers, merged, total_input, total_output


async def parallel_review(client, prd_content, wiki_pages, model_tiers, voting_rounds=1, wiki_path=None, diff_context=None, on_worker_done=None):
    """
    并行执行 4 个评审维度的 worker，合并结果
    - client: anthropic.Anthropic 实例
    - prd_content: PRD 全文字符串
    - wiki_pages: dict {页面标题: 页面内容}，可为空 dict
    - model_tiers: {"opus": "claude-opus-4-6", "sonnet": "claude-sonnet-4-6", "haiku": "claude-haiku-4-5"}
    - voting_rounds: 评审轮次，1=单次（默认），>=2 时启用多数投票
    - on_worker_done: 可选 callback (dim_key, result_dict) -> None,
      每个 worker 完成时调用,给 FastAPI SSE 层推进度。默认 None 保持 CLI 兼容。
    返回: {"workers": [...], "merged_items": [...], "total_usage": {...}}
    """
    if voting_rounds <= 1:
        # 单轮评审，保持原有行为
        workers, merged, total_input, total_output = await _single_round_async(
            client, prd_content, wiki_pages, model_tiers, wiki_path, diff_context,
            on_worker_done=on_worker_done,
        )
        return {
            "workers": workers,
            "merged_items": merged,
            "total_usage": {
                "input_tokens": total_input,
                "output_tokens": total_output,
            },
        }

    # 多轮评审 + 多数投票
    all_rounds_merged = []  # 每轮的 merged_items
    last_workers = []
    total_input = 0
    total_output = 0

    for round_idx in range(voting_rounds):
        if round_idx > 0:
            log.info(f"[majority_vote] 第 {round_idx + 1}/{voting_rounds} 轮评审，等待 5 秒...")
            await asyncio.sleep(5)

        log.info(f"[majority_vote] 开始第 {round_idx + 1}/{voting_rounds} 轮评审")
        workers, merged, inp, out = await _single_round_async(
            client, prd_content, wiki_pages, model_tiers, wiki_path, diff_context,
            on_worker_done=on_worker_done,
        )
        all_rounds_merged.append(merged)
        last_workers = workers
        total_input += inp
        total_output += out
        log.info(f"[majority_vote] 第 {round_idx + 1} 轮完成，发现 {len(merged)} 条改进项")

    # 多数投票筛选
    voted_items = majority_vote(all_rounds_merged, min_votes=2)
    log.info(f"[majority_vote] 投票完成：{sum(len(m) for m in all_rounds_merged)} 条 → {len(voted_items)} 条")

    return {
        "workers": last_workers,
        "merged_items": voted_items,
        "total_usage": {
            "input_tokens": total_input,
            "output_tokens": total_output,
        },
    }


def _single_round_sync(client, prd_content, wiki_pages, model_tiers, wiki_path=None, diff_context=None):
    """单轮顺序评审（内部函数），返回 workers, merged_items, usage"""
    dimensions = get_review_dimensions()

    # 读一次 rule performance history，传给所有 worker（避免 4 次 I/O）
    rule_perf_history = None
    try:
        with open(_get_rule_perf_history_path(), "r", encoding="utf-8") as f:
            rule_perf_history = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass

    workers = []
    all_items = []
    total_input = 0
    total_output = 0
    failed_dims = []

    for dim_key in dimensions:
        try:
            result = _run_worker_sync(client, dim_key, prd_content, wiki_pages, model_tiers, rule_perf_history, wiki_path, diff_context)
            workers.append(result)
            all_items.extend(result["items"])
            total_input += result["usage"]["input_tokens"]
            total_output += result["usage"]["output_tokens"]
        except Exception as e:
            err_msg = str(e)
            log.warning(f"[{_cn_label(dim_key)}] Worker 失败: {err_msg[:80]}")
            failed_dims.append(dim_key)
            workers.append({
                "dimension": dim_key,
                "dimension_name": dimensions[dim_key]["name"],
                "error": err_msg,
                "items": [],
            })
            # API 不可用（503/账户耗尽）时直接中断，不浪费后续 worker 的调用
            if "503" in err_msg or "No available account" in err_msg or "upstream_error" in err_msg:
                log.warning(f"API 不可用，跳过剩余 worker")
                for remaining_key in list(dimensions.keys()):
                    if remaining_key not in [w.get("dimension") for w in workers]:
                        failed_dims.append(remaining_key)
                        workers.append({
                            "dimension": remaining_key,
                            "dimension_name": dimensions[remaining_key]["name"],
                            "error": "跳过（API 不可用）",
                            "items": [],
                        })
                break

    # 允许最多 1 个 worker 失败，超过则报错
    if len(failed_dims) > 1:
        raise RuntimeError(f"过多 Worker 失败 ({len(failed_dims)}/4): {failed_dims}")

    # Scratchpad：记录各 worker 发现的规则 ID
    scratchpad = {}
    for w in workers:
        if "error" not in w or not w.get("error"):
            dim = w.get("dimension", "")
            scratchpad[dim] = {
                "found_rule_ids": w.get("found_rule_ids", []),
                "item_count": len(w.get("items", [])),
            }

    merged = merge_and_deduplicate(all_items)
    return workers, merged, total_input, total_output


def parallel_review_sync(client, prd_content, wiki_pages, model_tiers, voting_rounds=1, wiki_path=None, diff_context=None):
    """
    同步版本：顺序执行 4 个 worker（给不方便用 async 的场景）
    接口和返回值与 parallel_review 一致
    - voting_rounds: 评审轮次，1=单次（默认），>=2 时启用多数投票
    """
    if voting_rounds <= 1:
        workers, merged, total_input, total_output = _single_round_sync(
            client, prd_content, wiki_pages, model_tiers, wiki_path, diff_context
        )
        return {
            "workers": workers,
            "merged_items": merged,
            "total_usage": {
                "input_tokens": total_input,
                "output_tokens": total_output,
            },
        }

    # 多轮评审 + 多数投票
    all_rounds_merged = []
    last_workers = []
    total_input = 0
    total_output = 0

    for round_idx in range(voting_rounds):
        if round_idx > 0:
            log.info(f"[majority_vote] 第 {round_idx + 1}/{voting_rounds} 轮评审，等待 5 秒...")
            time.sleep(5)

        log.info(f"[majority_vote] 开始第 {round_idx + 1}/{voting_rounds} 轮评审")
        workers, merged, inp, out = _single_round_sync(
            client, prd_content, wiki_pages, model_tiers, wiki_path, diff_context
        )
        all_rounds_merged.append(merged)
        last_workers = workers
        total_input += inp
        total_output += out
        log.info(f"[majority_vote] 第 {round_idx + 1} 轮完成，发现 {len(merged)} 条改进项")

    voted_items = majority_vote(all_rounds_merged, min_votes=2)
    log.info(f"[majority_vote] 投票完成：{sum(len(m) for m in all_rounds_merged)} 条 → {len(voted_items)} 条")

    return {
        "workers": last_workers,
        "merged_items": voted_items,
        "total_usage": {
            "input_tokens": total_input,
            "output_tokens": total_output,
        },
    }


# ============================================================
# 依据验证 (Side Query)
# ============================================================

def _build_wiki_index(wiki_dir):
    """构建 wiki 文件索引（一次 glob，多次复用）"""
    if not os.path.isdir(wiki_dir):
        return {}
    index = {}
    for wiki_file in glob_module.glob(os.path.join(wiki_dir, "*.md")):
        basename = os.path.basename(wiki_file)
        index[basename] = wiki_file
    return index


def verify_evidence(items, workspace):
    """
    验证每条改进项的依据是否可回溯

    v1.2(B1): 细化返回字段
    - item["status"]: "VERIFIED" / "RETRACTED"  (向后兼容,run_session.py:336 的过滤仍有效)
    - item["verification_status"]: "verified" / "verified_with_caveat" / "retracted"  (细粒度)
    - item["verification_reason"]: 详细原因(成功/失败都有)
    - item["verification_details"]: {evidence_type, target, found}
    - item["retract_reason"]: 向后兼容(同 verification_reason)

    Args:
        items: 改进项列表
        workspace: 工作目录路径

    Returns:
        验证后的 items 列表(失败的标记 RETRACTED)
    """
    wiki_dir = os.path.join(workspace, "wiki")
    rules_dir = os.path.join(workspace, "review-rules")
    wiki_index = _build_wiki_index(wiki_dir)

    verified = []
    for item in items:
        ev_type = item.get("evidence_type", "")
        ev_content = item.get("evidence_content", "")
        retract_reason = None
        v_status = "verified"
        v_reason = f"{ev_type} 类依据通过校验" if ev_type else "无依据类型标注,跳过校验"
        v_details = {
            "evidence_type": ev_type or "unknown",
            "target": (ev_content or "")[:100],
        }

        if ev_type == "A":
            # A 类:检查 wiki/ 中是否存在对应页面
            if not _find_wiki_page(ev_content, wiki_dir, wiki_index):
                retract_reason = f"A 类依据验证失败:wiki 中未找到相关页面「{ev_content}」"
                v_status = "retracted"
                v_reason = retract_reason
                v_details["found"] = False
                v_details["reason_code"] = "A_missing_wiki_page"
            else:
                v_details["found"] = True

        elif ev_type == "B":
            # B 类:检查规则编号是否在 review-rules/ 中存在
            if not _find_rule_reference(ev_content, rules_dir):
                retract_reason = f"B 类依据验证失败:review-rules 中未找到规则「{ev_content}」"
                v_status = "retracted"
                v_reason = retract_reason
                v_details["found"] = False
                v_details["reason_code"] = "B_missing_rule"
            else:
                v_details["found"] = True

        elif ev_type == "C":
            # C 类:必须标记"待确定⚠️"
            if "待确定" not in ev_content and "⚠️" not in ev_content:
                # 自动补标,不 retract;但状态标为 verified_with_caveat(需人工确认)
                item["evidence_content"] = ev_content + "(待确定⚠️)"
                v_status = "verified_with_caveat"
                v_reason = "C 类依据自动补标'待确定⚠️',需人工确认"
                v_details["reason_code"] = "C_auto_annotated"
            else:
                v_status = "verified_with_caveat"
                v_reason = "C 类依据已标注待确定,需人工确认"
                v_details["reason_code"] = "C_pending_confirm"

        # 写入 item(保留旧字段 + 新字段)
        if retract_reason:
            item["status"] = "RETRACTED"
            item["retract_reason"] = retract_reason
        else:
            item["status"] = "VERIFIED"

        item["verification_status"] = v_status
        item["verification_reason"] = v_reason
        item["verification_details"] = v_details

        verified.append(item)

    return verified


def summarize_verification(items):
    """从验证后的 items 统计概要(供 shrike 门禁使用)

    v1.2(B1): 把 verification_status 汇总,给伯劳做决策

    Returns:
        {
            "total": N,
            "verified": N,              # verified + verified_with_caveat
            "retracted": N,
            "caveat": N,                # verified_with_caveat (C 类待确认)
            "retracted_by_reason_code": {"A_missing_wiki_page": N, ...},
            "reliability": 0.0-1.0,     # verified / total
        }
    """
    from collections import Counter
    total = len(items)
    if total == 0:
        return {"total": 0, "verified": 0, "retracted": 0, "caveat": 0,
                "retracted_by_reason_code": {}, "reliability": 1.0}

    verified_count = 0
    retracted_count = 0
    caveat_count = 0
    by_code = Counter()
    for item in items:
        vs = item.get("verification_status", "")
        if vs == "verified":
            verified_count += 1
        elif vs == "verified_with_caveat":
            verified_count += 1
            caveat_count += 1
        elif vs == "retracted":
            retracted_count += 1
            code = item.get("verification_details", {}).get("reason_code", "unknown")
            by_code[code] += 1

    reliability = verified_count / total if total > 0 else 1.0
    return {
        "total": total,
        "verified": verified_count,
        "retracted": retracted_count,
        "caveat": caveat_count,
        "retracted_by_reason_code": dict(by_code),
        "reliability": round(reliability, 3),
    }


def _find_wiki_page(evidence_content, wiki_dir, wiki_index=None):
    """在 wiki 目录中搜索依据提到的页面"""
    if not os.path.isdir(wiki_dir):
        return False

    # 从依据内容中提取 [[页面名]] 格式的引用
    import re
    page_refs = re.findall(r"\[\[(.+?)\]\]", evidence_content)

    if page_refs:
        # 有明确的页面引用，检查文件是否存在
        for ref in page_refs:
            for basename in (wiki_index or {}):
                if ref in basename:
                    return True
            if not wiki_index:
                pattern = os.path.join(wiki_dir, f"*{ref}*")
                if glob_module.glob(pattern):
                    return True
        return False

    # 模糊搜索用索引代替 glob
    all_basenames = list(wiki_index.keys()) if wiki_index else [
        os.path.basename(f) for f in glob_module.glob(os.path.join(wiki_dir, "*.md"))
    ]
    cn_keywords = re.findall(r'[\u4e00-\u9fff]{2,4}', evidence_content)
    en_keywords = [w for w in re.findall(r'[a-zA-Z_-]+', evidence_content) if len(w) > 2]
    keywords = cn_keywords + en_keywords
    for basename in all_basenames:
        for kw in keywords[:5]:
            if kw in basename:
                return True
    return False


def _find_rule_reference(evidence_content, rules_dir):
    """检查规则编号是否在 review-rules 目录中存在"""
    if not os.path.isdir(rules_dir):
        return False

    # 提取规则编号（如 RC-005, V-07, BMAD V-02 等）
    import re
    rule_ids = re.findall(r"(?:RC-\d+|BMAD\s+V-\d+|V-\d+)", evidence_content)
    if not rule_ids:
        # 没有明确规则编号，视为验证失败
        return False

    # 在 review-rules 目录下递归搜索
    all_rules_files = glob_module.glob(os.path.join(rules_dir, "**", "*"), recursive=True)
    for rules_file in all_rules_files:
        if not os.path.isfile(rules_file):
            continue
        try:
            with open(rules_file, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
            for rid in rule_ids:
                # 去掉 "BMAD " 前缀做匹配
                clean_rid = rid.replace("BMAD ", "")
                if clean_rid in content:
                    return True
        except OSError:
            continue

    return False


# ============================================================
# 合并与去重
# ============================================================

def majority_vote(all_runs_items, min_votes=2):
    """
    多数投票：多轮评审结果取交集，只保留出现 >= min_votes 次的改进项
    - all_runs_items: list[list[dict]]，每轮评审的合并后改进项列表
    - min_votes: 最少出现次数，默认 2
    - 匹配逻辑：优先用 rule_id 精确匹配；无 rule_id 时降级为 issue 文本相似度 >= 0.6
    - 对于匹配上的 items，保留文本最长的那条（信息最丰富）
    """
    if not all_runs_items:
        return []

    # 把所有轮次的 items 展平，标记来源轮次
    tagged = []
    for run_idx, items_in_run in enumerate(all_runs_items):
        for item in items_in_run:
            tagged.append((run_idx, item))

    # 分组：按 rule_id + location 聚类，无 rule_id 时用 issue 文本相似度
    clusters = []  # 每个 cluster 是 list[(run_idx, item)]

    for run_idx, item in tagged:
        rule_id = item.get("rule_id", "")
        issue_text = item.get("issue", "")
        matched_cluster = None

        for cluster in clusters:
            representative = cluster[0][1]
            rep_rule_id = representative.get("rule_id", "")

            # 优先 rule_id 精确匹配
            if rule_id and rep_rule_id and rule_id == rep_rule_id:
                loc_sim = SequenceMatcher(
                    None,
                    item.get("location", ""),
                    representative.get("location", ""),
                ).ratio()
                if loc_sim >= 0.5:
                    matched_cluster = cluster
                    break
            else:
                # rule_id 不同或缺失时，用 issue 文本相似度兜底
                rep_issue = representative.get("issue", "")
                if issue_text and rep_issue:
                    sim = SequenceMatcher(None, issue_text, rep_issue).ratio()
                    if sim >= 0.6:
                        matched_cluster = cluster
                        break

        if matched_cluster is not None:
            matched_cluster.append((run_idx, item))
        else:
            clusters.append([(run_idx, item)])

    # 筛选：只保留出现在 >= min_votes 个不同轮次的 cluster
    result = []
    for cluster in clusters:
        distinct_runs = len(set(run_idx for run_idx, _ in cluster))
        if distinct_runs >= min_votes:
            # 保留文本最长的那条（issue + suggestion 总长度）
            best = max(
                cluster,
                key=lambda t: len(t[1].get("issue", "")) + len(t[1].get("suggestion", "")),
            )
            result.append(best[1])

    # 重新排序和编号
    severity_rank = {"must": 0, "should": 1}
    result.sort(key=lambda x: severity_rank.get(x.get("severity", "should"), 1))
    for i, item in enumerate(result, start=1):
        item["id"] = f"R-{i:03d}"

    return result


def merge_and_deduplicate(items):
    """
    合并多个 worker 的改进项，去重并重新编号
    - 如果两条 item 的 location + issue 相似度 > 80%，保留严重度更高的
    - 重新编号为 R-001, R-002, ...
    - 按严重度排序（must 在前）
    """
    if not items:
        return []

    # 严重度排序权重
    severity_rank = {"must": 0, "should": 1}

    # 按严重度排序（must 优先）
    sorted_items = sorted(items, key=lambda x: severity_rank.get(x.get("severity", "should"), 1))

    # 去重：逐条检查是否与已保留的 item 高度相似
    kept = []
    for item in sorted_items:
        is_dup = False
        item_text = f"{item.get('location', '')} {item.get('issue', '')}"

        for existing in kept:
            existing_text = f"{existing.get('location', '')} {existing.get('issue', '')}"
            similarity = SequenceMatcher(None, item_text, existing_text).ratio()
            if similarity > 0.8:
                is_dup = True
                # 如果当前 item 严重度更高，替换已有的
                if severity_rank.get(item.get("severity"), 1) < severity_rank.get(existing.get("severity"), 1):
                    kept.remove(existing)
                    kept.append(item)
                break

        if not is_dup:
            kept.append(item)

    # 重新排序：must 在前
    kept.sort(key=lambda x: severity_rank.get(x.get("severity", "should"), 1))

    # 重新编号
    for i, item in enumerate(kept, start=1):
        item["id"] = f"R-{i:03d}"

    return kept
