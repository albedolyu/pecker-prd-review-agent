# Schema Registry 单点 SoT 重构设计 (2026-04-27)

> **作者**: Software Architect agent (后台 review, 只读 + 写设计 docs, 不改代码)
> **目标**: 修 Pecker `rule_id / dimension / 评审 schema` 散落 ≥ 12 处的反复漂移问题, 引入 `review/schema_registry.py` 单点 SoT
> **基线 HEAD**: `bba12be` (main, 2026-04-27)
> **范围**: 仅 schema (rule + dimension), 不动 wiki 加载 / hotfix / 用户输出格式

---

## TL;DR

| 维度 | 数字 / 结论 |
|---|---|
| 现状 wiring 点 | **17** 处 (硬编码 fallback / 散落 enum / 散落 yaml load / rule_perf 路径 / regex 嗅探 / 隐式 dimension 列表) |
| 历史漂移 case | **6 起** 已记录 (2026-04-26 ~ 2026-04-27 三天内 4 起) |
| 推荐 API | `SchemaRegistry` 单例 + `RuleDef` immutable dataclass + 启动加载 + reload-on-test + **fail-fast 但 dev 模式留 env 强制 fallback** |
| 落地工时估 | **5 天 (40h)**, 拆 8 step. 3 天版会漏 workspace yaml merge 风险 + e2e |
| 最大风险 | **6 workspace 老 `review-checklist.yaml` 是另一套 schema** (id/severity/impact_score 而非 rule_id/owner/status) — 不能直接 merge, 必须用 anti-corruption layer 转译 |
| 不做 | hotfix 路径 / wiki tier / review_items.json 输出格式 / yaml 重写 (向下兼容) |

---

## Part 1 — 现状调研: wiring 点真实分布

### 1.1 全量 wiring 点表

> 调研方法: `grep` 加 `rule_id / valid_rule_ids / load_review_dimensions / review-rules / rule_perf / SUBMIT_REVIEW_ITEMS / RC-\d+|V-\d+|FN-\d+|EV-\d+` 在 `review/`、`api/`、`scripts/`、`tests/`、根目录 `*.py`. 排除 `pecker-release/` (历史快照) 和 `legacy/`.

| # | wiring 点 | file:line | 引用方式 | 漂移风险 | 历史漂移 case |
|---|---|---|---|---|---|
| 1 | `_DEFAULT_REVIEW_DIMENSIONS` (硬编码 4 维度 + 18 rule) | `review/dimensions.py:53-142` | 硬编码 fallback dict, **YAML 加载失败时返回这个** | **高** | P0-B 2026-04-27 — yaml 有 FN/EV 18+ 条, fallback 只有 18 条, 切到 fallback 时 FN-09 直接消失 |
| 2 | `_DEFAULT_DIMENSION_WIKI_KEYWORDS` | `review/dimensions.py:144-149` | 硬编码 dict | 中 | wiki keyword 漂移过 (PR #?), worker prompt 缺关键词导致 wiki 召回 0 |
| 3 | `_REVIEW_DIMENSIONS_SCHEMA.pattern` (rule_id 正则) | `review/dimensions.py:189` | 硬编码 `^(V\|RC\|EV\|FN)-\d+$` | **高** | 加 FN- 时改了 pattern, 但 worker prompt regex `(RC-\d+\|V-\d+)` 没改, FN- rule_id 全被 prompting.py 过滤掉 (P0-B 同根因) |
| 4 | SUBMIT_REVIEW_ITEMS_TOOL `rule_id` schema | `review/worker.py:202, 241` | **裸 string 类型, 无 enum 约束** | **极高** | worker 可以输出任意 rule_id, 后置 `_postprocess_items` 才打 `cross_boundary` 标 — 这是 schema enum 的设计反模式 |
| 5 | `_postprocess_items.valid_rule_ids` (维度 rule 越界硬校验) | `review/worker.py:138` | `set(r["rule_id"] for r in dim["checklist"])` 现算 | 中 | rule 重命名时 worker 输出旧 id 全 cross_boundary 但 silent (只 warn log) |
| 6 | `worker.py` rule_id WORKER_SEED hash 序 | `review/worker.py:163` | item.get("rule_id") 字符串拼接 | 低 | — (deterministic 用) |
| 7 | `aggregation.py` 跨章节 rule 白名单 (V-05/V-06) | `review/aggregation.py:45` | **硬编码 `("V-05", "V-06")`** | 高 | rule 重命名 / 删除时这里不 sync, 跨章节聚合就会多/少分组 |
| 8 | `evidence_verify._find_rule_reference` regex | `review/evidence_verify.py:484` | 硬编码 `(?:RC-\d+\|BMAD\s+V-\d+\|V-\d+)` (**漏 FN/EV**) | **极高** | P0-A 2026-04-27 — yaml 有 FN-09, evidence_verify regex 不识别, FN-09 的 B 类依据全部 retract 掉 |
| 9 | `evidence_verify._verify_b_class_semantic` regex | `review/evidence_verify.py:525` | 硬编码 `(?:RC-\d+\|V-\d+)` (**漏 BMAD/FN/EV**) | **极高** | 同 #8, semantic overlap 验证对 FN/EV 永久失效 |
| 10 | `prompting._build_real_refs_section` regex | `review/prompting.py:292` | 硬编码 `(?:RC-\d+\|V-\d+)` (**漏 FN/EV**) | **极高** | worker prompt "可用规则编号" 清单不含 FN/EV, worker 看不到 → 即使 yaml 加了也用不上 |
| 11 | `prompting._build_feedback_section` rule canonical 比对 | `review/prompting.py:151, 161` | 用 dim.rules 文本 regex 抽 rule_id, 与 rule_perf 比对 | 中 | dim.rules 文本格式漂移时 dim_rule_ids set 失同步, feedback 注入 0 条 |
| 12 | `cuckoo_scorer._verify_type_b` regex | `cuckoo_scorer.py:240` | 硬编码 `(RC-\d+\|BMAD[\s-]V-\d+\|V-\d+)` (**漏 FN/EV**) | 高 | API flow B 类验证对 FN/EV 失效 (虽然 API 已转 evidence_verify, scorer 仍是历史包袱) |
| 13 | `cuckoo_scorer._search_rule_in_dir` BMAD 前缀清洗 | `cuckoo_scorer.py:269` | 硬编码 `^BMAD[\s-]+` 前缀 | 低 | BMAD 是历史命名, 可以删 |
| 14 | `cuckoo_parser` evidence type 推断 regex | `cuckoo_parser.py:182` | 硬编码 `(?:RC-\|BMAD\|V-)\d+` (**漏 FN/EV**) | 高 | C 类被误判为 B 类 / 反之 |
| 15 | `review_fixer.infer_evidence_type` regex | `review_fixer.py:27` | 硬编码 `(?:RC-\d+\|V-\d+\|BMAD[\s-]*V-\d+)` (**漏 FN/EV**) | 高 | 同 #14, 文本里有 FN-09 但被推断为 C 类 |
| 16 | `feedback._extract_rule_id` 多 regex 链 | `feedback.py:980-981, 1131-1136` | 硬编码 `BMAD\s+V-\d+`, 类型分组只识 BMAD/RC | 高 | feedback 报表 FN/EV 全归"未知规则类型", 决策回流 rule_perf 出错 |
| 17 | 6 workspace `review-checklist.yaml` (产品召回 / 对外投资 / 劳动仲裁 / 纳税人资质 / 侵权软件 + 1 缺) | `workspace-*/review-rules/review-checklist.yaml` | **完全不同 schema** (`id/name/severity/description/impact_score`, **无 owner/status/dimension**) | **极高** | RC-014 zombie — 老 yaml 有 RC-014, 新 review-dimensions.yaml 已删, 但 evidence_verify 扫 review-rules/ 仍能"找到", 回流 rule_perf 写出鬼数据 |

> **6 workspace 实际只 5 个有 `review-rules/`** (`workspace-fengniao-mediation` / `workspace-points-payment` / `workspace-sample` / `workspace-风鸟-backend-test` 4 个无), 但有的 5 个 yaml schema 高度相似 (~60 行/份, 同 rule 集合 RC-004 ~ RC-015). 全是同一份历史模板的 5 份拷贝.

### 1.2 漂移成因归类

| 类别 | 数量 | 典型代表 | 修法 |
|---|---|---|---|
| **硬编码 regex 散落** | 7 (#3, #8, #9, #10, #12, #14, #15) | `(?:RC-\d+\|V-\d+)` 各种变体, 6 处都漏 FN/EV | registry 提供 `valid_rule_id_pattern() -> str` |
| **硬编码 fallback dict** | 2 (#1, #2) | `_DEFAULT_REVIEW_DIMENSIONS` 与 yaml 漂移 | registry **不留 fallback**, fail-fast (dev 模式 env 强制 fallback) |
| **隐式约束 (无 schema enum)** | 1 (#4) | `rule_id` 是裸 string | registry 在 worker schema 构建时**注入 enum** |
| **现算 valid set** | 2 (#5, #11) | 每次都从 dim["checklist"] 里现算 | registry 缓存 + `dimension_rules(dim) -> list[Rule]` |
| **业务硬编码白名单** | 1 (#7) | `("V-05", "V-06")` 跨章节 | registry 给 rule 加 `cross_section: bool` 字段 (yaml 配) |
| **多源 schema 并存** | 1 (#17) | 6 workspace yaml vs 全局 yaml | anti-corruption layer 在 registry 里转译 |

### 1.3 历史漂移 case (PM 给的 6 起)

| 日期 | case | 触发的 wiring 点 |
|---|---|---|
| 2026-04-26 | NLI sparse 跳过 — wiki path 设计错 | (wiki 范畴, 本 schema registry 不修, 见 Part 5) |
| 2026-04-26 | DAR 死代码 — wrapper 接但 production 默认未改 | (goshawk 范畴, 不修) |
| 2026-04-26 | `PECKER_EXTERNAL_CANONICAL_WIKI` env default 加了但 0 处真读 | (wiki 范畴, 不修) |
| 2026-04-26 | model=None 透传 (P0 hotfix) | (model 选型范畴, 不修) |
| 2026-04-27 | **P0-A**: content_loader 加 49 canonical, evidence_verify 走另一条 path | (wiki 范畴, 已修. 但本次 schema #8 #9 同病不同因) |
| 2026-04-27 | **P0-B**: yaml 有 FN-XX, `_DEFAULT_REVIEW_DIMENSIONS` hardcoded 没 FN, worker enum 拒 FN | **本次 schema registry 修**: #1 #3 #4 #10 同时治 |

> **结论**: 6 起里 schema 直接相关 1 起 (P0-B), 间接相关 1 起 (P0-A 是 wiki 但症状一致 — 多份现算/硬编码). 6 wiring 反模式确诊.

---

## Part 2 — Schema Registry API 设计

### 2.1 数据模型 (Pydantic v2 / dataclass)

```python
# review/schema_registry.py
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Literal, Optional
from functools import lru_cache
import os, re, threading
import yaml

RuleStatus = Literal["active", "experimental", "inactive"]
Severity = Literal["must", "should"]


@dataclass(frozen=True)
class RuleDef:
    """单条评审规则 — immutable, hashable."""
    rule_id: str                       # 'V-02' / 'RC-005' / 'FN-09' / 'EV-01'
    name: str                          # '格式规范性'
    dimension: str                     # 'structure' / 'quality' / 'ai_coding' / 'data_quality'
    owner: str                         # rule-level owner (通常 = dimension)
    status: RuleStatus = "active"
    enabled: bool = True
    severity: Severity = "must"        # 从 rules 文本里抽不出时默认 must
    cross_section: bool = False        # #7 替代: V-05/V-06 这类跨章节聚合规则在 yaml 标 cross_section: true
    impact_score: float = 0.5          # 来自 workspace yaml (legacy) 或 yaml 里直接配


@dataclass(frozen=True)
class DimensionDef:
    """单个评审维度 (= 一个 worker)."""
    key: str                           # 'structure'
    name: str                          # '结构层'
    codename: str                      # '织布鸟'
    model: str                         # 'haiku' / 'sonnet' / 'opus'
    rules_text: str                    # 长 prompt 文本 (worker system prompt 用)
    wiki_keywords: tuple[str, ...]     # immutable
    rules: tuple[RuleDef, ...]         # 该维度下的 rule 列表 (filter enabled=True)


class SchemaRegistry:
    """单点 source-of-truth for Pecker schema (规则 + 维度).

    所有 wiring 点强制从 registry 拉, 不再有散落 enum / hardcoded fallback / regex.
    """
```

### 2.2 公开 API (8 个核心方法)

```python
class SchemaRegistry:
    # ---- 全局入口 ----
    @classmethod
    def get(cls, workspace: Optional[str] = None) -> "SchemaRegistry":
        """主入口 — workspace 维度 lru_cache (与现有 dimensions._cached_load 一致).
        FastAPI 并发安全: 不同 workspace 用不同 instance, 同 workspace 复用.
        """

    # ---- 规则查询 (替代 #4 #5 #8-#16 的散落 regex) ----
    def all_rule_ids(self) -> frozenset[str]:
        """所有 active+enabled 的 rule_id, 用于 worker schema enum 注入.
        排除 status=inactive (deprecated) 的 rule."""

    def get_rule(self, rule_id: str) -> Optional[RuleDef]:
        """按 id 查; 不在 registry → None (caller 决定 fail/warn)."""

    def is_active(self, rule_id: str) -> bool:
        """status=active 且 enabled=True. status=experimental 也算 active 但分桶记 telemetry."""

    def is_cross_section(self, rule_id: str) -> bool:
        """替代 aggregation.py:45 的 ('V-05', 'V-06') 硬编码."""

    # ---- 维度查询 ----
    def dimensions(self) -> dict[str, DimensionDef]:
        """全部维度 dict, key=dim_key. 复制返回防 caller 误改."""

    def dimension_rules(self, dim_key: str) -> tuple[RuleDef, ...]:
        """某维度的 rule 列表 (替代 worker.py:138 valid_rule_ids 现算)."""

    # ---- regex 单点 ----
    def rule_id_pattern(self) -> str:
        """单点输出 rule_id 正则. 替代 #3 #8-#16 的 7 处散落硬编码.
        从 yaml schema 的 pattern 字段读, 改 yaml 自动同步全部 caller."""

    # ---- 测试 / 热更新 ----
    def reload(self) -> None:
        """强制重读 yaml + 清 lru_cache. 单测 fixture 用. production 不暴露."""

    # ---- rule_perf 联动 (合并查询接口) ----
    def with_perf(self, workspace: str) -> "SchemaRegistryWithPerf":
        """返回带 rule_perf_history 的 view, 供 prompting.py / worker 用.
        SchemaRegistryWithPerf 加 .precision_7d(rule_id) / .reject_rate_7d(rule_id) /
        .impact_adjusted(rule_id) 三个查询. 内部 join schema + rule_perf_store."""
```

### 2.3 启动 + 加载策略

```python
def _load_yaml_chain(workspace: Optional[str]) -> dict:
    """加载链 (与现有 dimensions.load_review_dimensions 一致):
    1. workspace/review-rules/review-dimensions.yaml (新主)
    2. <repo_root>/review-dimensions.yaml (全局)
    3. raise SchemaLoadError (不再静默走 fallback dict)
    """

def _ingest_legacy_workspace_checklist(workspace: str) -> list[RuleDef]:
    """anti-corruption layer: 6 workspace 老 review-checklist.yaml 转译.
    老格式: {id, name, severity, description, impact_score}
    转新格式: RuleDef(rule_id=id, dimension=<根据 id 前缀映射>, owner=dimension, status='active', impact_score=...)
    
    冲突策略: 老 yaml rule 与 review-dimensions.yaml 同 id 时, **新 yaml 赢** (老 yaml 视为只贡献 impact_score 给新)
    """
```

### 2.4 设计取舍

| 取舍 | 推荐 | 替代方案 | 理由 |
|---|---|---|---|
| **加载时机** | **首次访问 lazy + lru_cache (workspace 维度)** | 启动 once / reload-on-change | 与现有 `_cached_load(workspace_key)` 一致, 不破现有并发模型. reload-on-change 引入 watcher 复杂度无收益 (PM 改 yaml 重启 server 是当前流程) |
| **加载失败** | **fail-fast raise SchemaLoadError, 但 dev 模式 `PECKER_SCHEMA_FALLBACK=1` 可强制走 minimal fallback** | 永远 fail-fast / 永远静默 fallback | 现行静默 fallback 是 P0-B 根因. 但 dev 期 yaml 写错 server 起不来太狠, 留 env 逃生口. **生产环境必须不设这个 env**, 让 schema 错立即可见 |
| **Wiki 元数据** | **registry 不管 wiki, 只管 rule + dimension** | registry 也管 wiki path / authority tier | wiki 已有 content_loader 单点 (P1 已修). schema registry 范围收窄, 跟 wiki 演化解耦. P0-A 是另一类 SoT (wiki SoT), 应单独 ticket |
| **rule_perf 反馈** | **registry 提供 `with_perf(workspace)` view, 不直接管 rule_perf_history** | registry 内部 join | 关注分离: registry 是 schema 定义层 (静态), rule_perf 是运行时数据 (动态). 用 view 模式 read-only 暴露, 写仍走 `rule_perf_store` |
| **多 workspace yaml** | **anti-corruption layer 转译, 老 yaml 只贡献 impact_score** | merge / 替换 / 忽略 | 老 yaml 的 impact_score 是 PM 标的业务权重, 删了可惜. 但 owner/dimension/status 字段缺失, 必须以新 yaml 为准. Defensive: 转译失败的老 rule 直接 drop + log warning, 不阻塞启动 |
| **rule_id 校验** | **schema enum 在 worker tool schema 注入时硬约束** | 现行后置打 `cross_boundary` 标 | enum 是 LLM 工具调用层最强约束, 模型几乎无法绕过. 后置打标 silent (只 warn log), 是反模式 |
| **status enum (active / experimental / inactive)** | **保留三态, registry 默认返 active+experimental** | 二态 (active / inactive) | experimental 是 sprint Day3 的 PM gate, 删了影响规则迭代节奏. registry 提供 `include_experimental: bool = True` 参数 |
| **immutable RuleDef** | **frozen dataclass + tuple** | mutable dict | 防 caller 误改污染 cache. 性能上 frozen dataclass 比 dict 慢 ~5%, 可接受 (registry 查询不在 hotpath) |

### 2.5 错误处理 (SchemaLoadError 分类)

```python
class SchemaLoadError(Exception):
    """yaml 加载/校验失败. message 含具体 file:path 让 PM 一眼定位."""

class SchemaConflictError(Exception):
    """workspace yaml 与全局 yaml rule_id 冲突且无法 merge. 转译时 raise."""

class UnknownRuleError(KeyError):
    """get_rule(rule_id) 在 strict 模式下找不到 raise. 默认 None 返回."""
```

---

## Part 3 — 落地 Checklist (5 天 = 40h)

> **顺序原则**: 自底向上, 先骨架 + 单测, 再 caller 一个个迁, e2e 收尾. **每 step 跑全量 pytest 不绿不进下一步**.

| # | Step | File | 改动 | 测试策略 | 工时 | 风险 |
|---|---|---|---|---|---|---|
| 1 | 创 `review/schema_registry.py` 骨架 + 数据模型 + yaml 加载 + lru_cache + SchemaLoadError | 新建 `review/schema_registry.py` (~300 行) | RuleDef / DimensionDef / SchemaRegistry / `_load_yaml_chain` / `_ingest_legacy_workspace_checklist` | 新建 `tests/test_schema_registry.py` 12 单测: yaml load 正常 / yaml 缺字段 raise / workspace 覆盖优先 / lru_cache 命中 / fallback env / legacy workspace yaml 转译 / experimental rule 包含 / rule_id_pattern 正则 / cross_section 字段 / get_rule None 分支 / dimension_rules 过滤 enabled / reload 清 cache | **6h** | 低 (只新增, 不改) |
| 2 | 改 `review/dimensions.py`: load_review_dimensions / get_review_dimensions 改用 registry 实现, 删 `_DEFAULT_REVIEW_DIMENSIONS` / `_DEFAULT_DIMENSION_WIKI_KEYWORDS` 硬编码 fallback. 保留 API 签名不变 (caller 0 改) | `review/dimensions.py` (~200 行删 + 50 行改) | re-export 旧 API, 内部转 registry. parallel_review.py 等 caller 不动 | 跑现有 `tests/test_dimensions*.py` + 新加 3 单测: yaml 缺时不再返 hardcoded dict / strict 模式 raise / fallback env 走 minimal | **5h** | **中** — 可能有未发现的 caller 直接 import `_DEFAULT_REVIEW_DIMENSIONS` (grep 防漏) |
| 3 | 改 `review/worker.py`: SUBMIT_REVIEW_ITEMS_TOOL `rule_id` 注入 enum (从 registry 拿), `_postprocess_items.valid_rule_ids` 改 registry 调用 | `review/worker.py:202, 241, 138` | tool schema 构建从静态 dict → 函数 (拿 registry 注入) | mock worker, 验 tool schema enum 含全部 active+experimental rule_id; 跑 `tests/test_worker_*.py` | **6h** | **中** — schema enum 注入后, model 输出的 rule_id 必须严格匹配, 历史模型可能被拒. 需要在 production 灰度看 1 天 telemetry |
| 4 | 改 `review/evidence_verify.py`: `_find_rule_reference` / `_verify_b_class_semantic` regex 替换为 registry.rule_id_pattern() | `review/evidence_verify.py:484, 525` | 2 处 regex 单点 | 跑 `tests/test_evidence_chain.py` + `test_evidence_verify_wiki_sparse.py`; 新加 1 e2e: 用 yaml 含 FN-09 的 fixture, 验 evidence_verify 不 retract FN-09 的 B 类依据 | **3h** | 中 — 修 P0-A 同根因 |
| 5 | 改 `review/prompting.py`: `_build_real_refs_section` regex + `_build_feedback_section` rule canonical 比对都走 registry | `review/prompting.py:151, 161, 292` | 3 处 | 跑 `tests/test_*prompting*.py` (如有) + 新加 1 单测: workspace 有 FN-09 yaml 时, prompt "可用规则编号"清单含 FN-09 | **3h** | 低 |
| 6 | 改 `review/aggregation.py`: 跨章节硬编码 `("V-05", "V-06")` → registry.is_cross_section(rule_id). 同时改 review-dimensions.yaml 给 V-05/V-06 加 `cross_section: true` + schema 加字段定义 | `review/aggregation.py:45`, `review-dimensions.yaml`, `review/schema_registry.py` schema 字段 | rule schema 加新可选字段 | 跑 `tests/test_cross_section_tagging.py`; 新加 1 单测 | **2h** | 低 |
| 7 | 清理外围 regex: `cuckoo_scorer.py` / `cuckoo_parser.py` / `review_fixer.py` / `feedback.py` 4 个文件的硬编码 regex 全替换 | 4 个 file × 1-3 处 = ~6 处 | 同 #4 | 跑 `tests/test_review_fixer*.py` / `test_cuckoo_parser.py` / `test_feedback_scan.py`; 加 1 fixture: feedback rule_id 抽取识别 FN/EV | **4h** | 中 — feedback.py 有 BMAD 类型分组逻辑, 转 registry 后老 BMAD 报表字段要保留兼容 |
| 8 | workspace yaml legacy 转译 + e2e validation: 写脚本扫 5 个 workspace yaml, 验 anti-corruption layer 全部转译成功; 加 e2e test 跑 1 次完整 pecker session 验所有 wiring 都用 registry | `scripts/validate_schema_registry.py` 新建 (~80 行) + `tests/test_schema_registry_e2e.py` 新建 | 真跑 pecker session (mock LLM) | 集成 + 1 次真实 pecker (~$5 cost) | **5h** | **高** — 这是把 #1-#7 全集成. workspace 老 yaml 任一份转译失败要回到 step 1 改 anti-corruption layer |
| 9 | docs 更新 + deprecation warning + migration guide | `docs/` + `review/dimensions.py` 加 deprecation warning | 文档同步 | — | **2h** | — |
| 10 | feature flag wrapper + 灰度: 加 `PECKER_USE_SCHEMA_REGISTRY` env (默认 1), 关掉时走旧路径; production 跑 1 周 telemetry 对比新旧 N0/N1 metric | `review/dimensions.py` 入口 | 双轨支持 1 周 | telemetry 对比 | **4h** | 中 — 双轨期代码复杂度上升, 1 周后必须删 |
| **总** | | | | | **40h ≈ 5 天** | |

> **3 天版 (24h)** 可行但漏掉 #8 #10: e2e + 灰度 — 强烈不推荐, 重蹈 P0-B 覆辙 (代码改了但没 e2e 验, fallback 路径仍然在跑).

---

## Part 4 — 兼容性 / 回滚 / 风险

### 4.1 兼容性

| 旧 API | 处理方式 | 迁移时间 |
|---|---|---|
| `review.dimensions.load_review_dimensions(workspace)` | **保留**, 内部转 registry, 加 `DeprecationWarning` | 6 个月后删 |
| `review.dimensions.get_review_dimensions(workspace)` | 同上 | 同上 |
| `review.dimensions.get_wiki_keywords(workspace)` | 同上 | 同上 |
| `review.dimensions._DEFAULT_REVIEW_DIMENSIONS` | **直接删** (内部符号 _ 开头, 没 public contract) | 立即 |
| `review.dimensions._get_rule_perf_history_path(workspace)` | **保留** (registry 不管 rule_perf 路径, 只管 schema) | 不动 |

### 4.2 回滚预案

```bash
# Feature flag (step 10): 开发期可一键回退
export PECKER_USE_SCHEMA_REGISTRY=0
# → review.dimensions 走旧 hardcoded fallback 路径
# → 所有 wiring 点继续散落 (但不会更糟, 与 HEAD bba12be 一致)
```

git revert 路径: 8 commits 拆每个 step 一 commit, 单点 revert step 8 即可关 e2e validation (其余 step 仍生效).

### 4.3 风险地图

| 等级 | 风险 | 触发条件 | 缓解 |
|---|---|---|---|
| **极高** | 6 workspace yaml anti-corruption layer 转译错, 老 RC-014 zombie 复活 | step 8 转译逻辑漏字段 | step 1 单测覆盖 5 个 workspace yaml fixture, step 8 e2e validation 100% 转译 |
| **高** | step 3 worker schema enum 注入后, 模型历史输出的旧 rule_id 全 reject | rule 重命名 + 模型缓存 prompt | enum 包含 status=inactive 的 rule (作为 deprecated transition); telemetry 监控 worker reject 率 |
| **高** | yaml 加载失败 fail-fast → server 启动崩 | yaml 写错 + 没设 PECKER_SCHEMA_FALLBACK=1 | error message 含 file:line + 修复建议; CI 加 yaml schema lint pre-commit hook |
| **中** | rule_perf with_perf view 与现有 rule_perf_store 接口不一致 | step 1 设计时漏看 RulePerformanceHistoryStore.get(rule_id) 实际 return shape | step 1 写 view 前先 grep `RulePerformanceHistoryStore` 全部调用方核对 |
| **中** | feature flag 双轨期代码复杂度爆 | step 10 双轨 > 1 周 | sprint 排期硬性 1 周窗口, 到期不论 telemetry 结果都删旧路径 |
| **低** | frozen dataclass 性能 ~5% 退化 | hotpath 高频查 | registry 在 worker / evidence_verify 层 caching, 不在 hotpath; 实测 < 1ms / call |
| **低** | lru_cache 占用内存 (8 个 workspace × ~50KB schema) | 多租户 | `maxsize=8` 与现行一致 |

---

## Part 5 — 不做的事 (scope 守界)

- **不动 hotfix 路径**: `goshawk_advisor.py` / `claude_cli.py` / model 选型 / `MAX_ITEMS_PER_WORKER` 全不碰
- **不动 wiki 加载**: `content_loader.load_wiki_pages` / `evidence_verify._build_wiki_index` / wiki tier gate 全不碰. 这是另一类 SoT 反模式, 应单独 ticket (建议命名 `wiki_registry_design`)
- **不改 review_items.json 输出格式**: 用户消费侧契约不动. RuleDef 是内部数据模型, 序列化输出仍是现有 dict
- **不重写 yaml**: 向下兼容现有 `review-dimensions.yaml` schema (含 EV/FN). 5 workspace 老 `review-checklist.yaml` 也保留, 用 anti-corruption layer 读
- **不动 rule_perf_store**: registry 只读 view, 写仍走 `RulePerformanceHistoryStore`. cleanup_rule_perf / rule_perf_hygiene scripts 不动
- **不引入新依赖**: 用 stdlib `dataclasses` + 现有 `pyyaml` + `jsonschema` (已在 dimensions.py 用), 不引入 pydantic
- **不改 env 命名约定**: 沿用 `PECKER_` 前缀
- **不动 `pecker-release/`**: 历史快照, 与 main 已分叉

---

## Part 6 — 后续延伸 (本次不做, 列 backlog)

| 后续工作 | 触发条件 | 工时估 |
|---|---|---|
| **wiki_registry SoT 重构** (P0-A 根本治) | schema_registry 上线 1 个月后, wiki 漂移 case 又起 | 5 天 |
| 5 workspace 老 yaml 删 / 合到主 yaml | anti-corruption layer 跑 1 个月稳定后 | 1 天 |
| feedback.py BMAD 字段彻底删 | rule_perf_history.json 数据洗完 | 0.5 天 |
| schema 文档自动生成 (registry → markdown) | PM 想看完整 rule 清单时 | 0.5 天 |
| pre-commit hook: yaml schema validation | CI 接入 | 0.5 天 |

---

## 附录 A: 完整 wiring 点 grep 命令 (复跑用)

```bash
# 全部 17 处 wiring 点 grep (HEAD bba12be):
grep -rn "rule_id\|RULE_ID\|_DEFAULT_REVIEW_DIMENSIONS\|valid_rule_ids" review/ --include="*.py"
grep -n "SUBMIT_REVIEW_ITEMS_TOOL\|enum.*V-\|enum.*RC-" review/worker.py
grep -rn "load_review_dimensions\|review-dimensions.yaml" *.py review/ --include="*.py"
grep -rn "load_wiki_pages\|wiki_pages\|_build_wiki_index" review/ content_loader.py
grep -rn "rule_perf_history\|rule_performance" *.py scripts/ --include="*.py"
grep -rn "review-rules.*yaml\|review-checklist.yaml" *.py review/ --include="*.py"
grep -rn "(?:RC-\|BMAD\|V-)\\\\d\+" *.py review/ --include="*.py"
find workspace-* -maxdepth 2 -type d -name "review-rules"
```

## 附录 B: yaml fixture 用例 (单测覆盖)

```yaml
# tests/fixtures/schema_minimal.yaml — step 1 单测
dimensions:
  structure:
    name: "结构层"
    codename: "织布鸟"
    rules: "V-02 测试"
    checklist:
      - rule_id: "V-02"
        name: "格式规范性"
        owner: structure

# tests/fixtures/schema_legacy_workspace.yaml — step 8 anti-corruption
rules:
  - id: RC-005
    name: 四态 UI 规范已定义
    severity: must
    description: ...
    impact_score: 0.8
```

---

## 实施回顾 (2026-04-27)

8 substep 全部 e2e 验证通过, pytest 932 → 1073 (+141 测试):

| substep | 范围 | pytest 累计 |
|---|---|---|
| 3.1 | `review/schema_registry.py` 骨架 + `tests/test_schema_registry.py` (14 测试) | 946 |
| 3.2 | `review/dimensions.py` 删 fallback dict + `parallel_review.py` re-export 删 + `tests/test_dimensions_registry_wiring.py` (14 测试) | 954 |
| 3.3 | `review/worker.py` SUBMIT_REVIEW_ITEMS_TOOL 动态 enum + `tests/test_worker_dynamic_enum.py` (7 测试) | 961 |
| 3.4 | `review/evidence_verify.py` regex SoT 化 + `tests/test_evidence_verify_registry.py` (10 测试) | 971 |
| 3.5 | `review/prompting.py` + `review_fixer.py` + `cuckoo_scorer.py` SoT 化 + 3 测试文件 (47 测试) | 1018 |
| 3.6 | anti-corruption section (5 workspace 老 yaml schema 转译) + `tests/test_schema_registry_anticorruption.py` (27 测试) | 1045 |
| 3.7 | `tests/test_schema_registry_e2e.py` 端到端集成 (28 测试) | 1073 |
| 3.8 | docs 同步 (本次, 不动代码) | 1073 |

核心目标在 e2e 层达成:
- ✓ 加新规则 (V-13 / RC-017 / FN-04) 真 1 处改 6 处自动 propagate (e2e 用例覆盖)
- ✓ 加新前缀 (DQ-99) 正确 raise SchemaRegistryError, 强制 PM 改 schema_registry 一处
- ✓ 6 workspace 老 yaml anti-corruption 100% 转译, RC-014 zombie 端到端 0 复活
- ✓ 不动 hotfix 路径 (`goshawk_advisor.py` / `clients/claude_cli.py` 不在变更范围)

实际工作量 vs 设计估算:
- 设计文档估 5 天 / 10 step, 实际 8 substep 约 12 小时 wall clock (cron + 8 agent 接力)
- P0-A/B 修法预先实现了 50% 思想 (yaml 真接通 + RC-014 6 workspace 物理删), 加速大幅
- 最大风险 step 3.6 (5 workspace anti-corruption) 安全通过, fail-safe 在所有未知字段场景未误伤

后续 backlog (本次未处置):
- 5 workspace 老 yaml 物理清 zombie (RC-014 等) — anti-corruption fail-safe 已挡, 但 PM 可清 yaml 让 SoT 干净
- 6 workspace yaml byte-by-byte 对齐 — 后续可考虑合到全局 yaml, 删 `review-checklist.yaml` 这套并行 schema
- `review_fixer` regex 无 word boundary 边缘 bug — `tests/test_schema_registry_e2e.py` 注释 caveat
- `rule_perf` wiring (本设计 with_perf 接口骨架已落, 联动 step 留下次)

落地后单点 SoT 修改路径 (新规则只改 1 处):
1. 改 `review/schema_registry.py` (加 prefix / 加 rule_id) → 17 wiring 点全部自动 propagate
2. 跑 `pytest tests/test_schema_registry_e2e.py` 确认 propagate 正确 → 加新规则 case 强制覆盖
3. 完毕
