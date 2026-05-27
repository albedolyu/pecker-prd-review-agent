"""并行评审模块 facade — 原 1833 行单文件拆分后的兼容层.

2026-04-16 SPLIT_PLAN 完成拆分:
- review.dimensions      维度配置加载 + YAML schema + _get_rule_perf_history_path
- review.prompting       Worker system prompt / user messages / wiki 清单注入
- review.worker          单 Worker 执行 (prompt → Claude API → items 抽取)
- review.orchestration   4 Worker 并行编排 + 多轮投票
- review.evidence_verify A/B/C 三类依据硬验证 + wiki 索引
- review.aggregation     merge_and_deduplicate + majority_vote

本文件仅做 re-export, 不含业务逻辑。历史路径 `from parallel_review import X` 全部保持可用。
如果需要新增符号, 请直接加到对应 review/*.py 子模块, 再在这里 re-export。
"""

# Cluster A — 维度配置
# step 3.2 (2026-04-27): 删 _DEFAULT_REVIEW_DIMENSIONS / _DEFAULT_DIMENSION_WIKI_KEYWORDS
# re-export — 这俩硬编码 fallback 已从 review.dimensions 移除 (P0-B 反模式根因).
# 老 caller 若直接 import 这俩 symbol 会 ImportError, 应改用 SchemaRegistry / load_review_dimensions.
from review.dimensions import (  # noqa: F401
    MAX_WORKER_TURNS,
    _BASE_DIR,
    _CN_LABEL,
    _REVIEW_DIMENSIONS_SCHEMA,
    _YAML_FILENAME,
    _cn_label,
    _get_rule_perf_history_path,
    _validate_review_dimensions_yaml,
    get_review_dimensions,
    get_wiki_keywords,
    load_review_dimensions,
)

# Cluster B — Prompt 构建
from review.prompting import (  # noqa: F401
    _WORKER_SHARED_RULES,
    _WORKER_SYSTEM_TEMPLATE,
    _add_freshness_note,
    _build_feedback_section,
    _build_real_refs_section,
    _build_worker_messages,
    _build_worker_system,
    _maybe_compact_wiki,
    build_wiki_manifest,
)

# Cluster C — Worker 执行
from review.worker import (  # noqa: F401
    SUBMIT_REVIEW_ITEMS_TOOL,
    _extract_items_from_response,
    _extract_text,
    _get_compact_tool_schema,
    _has_tool_use,
    _is_empty_tool_submission,
    _parse_items_from_text,
    _run_worker_async,
    _run_worker_sync,
    _worker_core,
)

# Cluster D — 并行编排 (对外公共 API)
from review.orchestration import (  # noqa: F401
    _single_round_async,
    _single_round_sync,
    parallel_review,
    parallel_review_sync,
)

# Cluster E — 依据验证
from review.evidence_verify import (  # noqa: F401
    _build_wiki_index,
    _find_rule_reference,
    _find_wiki_page,
    _verify_b_class_semantic,
    summarize_verification,
    verify_evidence,
)

# Cluster F — 合并与去重
from review.aggregation import majority_vote, merge_and_deduplicate  # noqa: F401
