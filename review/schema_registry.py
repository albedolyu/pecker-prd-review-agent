"""Schema Registry: Pecker 规则 / 维度 schema 单点 SoT.

参考 docs/schema_registry_design_2026_04_27.md (step 3.1 骨架).

设计意图:
- 替代散落 17 处 wiring 点 (rule_id 硬编码 regex / valid_rule_ids 现算 / hardcoded fallback dict).
- yaml 加载失败 fail-fast (raise SchemaRegistryError), 但 PECKER_SCHEMA_FALLBACK=1 dev 逃生口.
- 不留 hardcoded 镜像 fallback dict — 那是 P0-B 漂移根因.
- 不动 hotfix 路径 (goshawk_advisor / claude_cli / model 选型).

加载链复用 review.dimensions.load_review_dimensions, 不重写 yaml 解析.
本模块只在其上加 immutable 数据模型 + 单点查询 API.
"""

from __future__ import annotations

import os
import re
import threading
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Literal, Optional

from logger import get_logger

log = get_logger("schema_registry")


# ============================================================
# 数据模型 (immutable, hashable)
# ============================================================

# rule status 状态机:
#   active        — 正常生效, 计入 N0/precision metric
#   experimental  — sprint 实验期 (1 周观察 reject_by_reason 决定升降)
#   noisy         — 临时降级 (rule_perf 噪声超阈值, 仍发但权重低)
#   deprecated    — 已废弃 (registry 默认不输出, 但保留 enum 防历史 reject)
RuleStatus = Literal["active", "experimental", "noisy", "deprecated"]


# severity: 老 workspace yaml 用 'must'/'should' 标记规则强度, 新 yaml schema 没保留这字段
# (severity 现在落到 review_items 层而非 rule 层). step 3.6 anti-corruption 把这字段
# Optional 加进 RuleDef, 老 yaml 转译时填上, 新 yaml 转译时为 None.
Severity = Literal["must", "should"]


@dataclass(frozen=True)
class RuleDef:
    """单条评审规则定义, 跟 review-dimensions.yaml schema 对齐.

    cross_section 字段是新增的 (yaml 暂未配, 由 registry 启动时按 _CROSS_SECTION_RULES
    清单标), 替代 aggregation.py:45 的 ('V-05', 'V-06') 硬编码白名单.

    severity / impact_score 是 step 3.6 anti-corruption 加的 Optional 字段, 用于保留
    老 workspace `review-checklist.yaml` 的业务字段 (PM 标的"必须/可选" + 0..1 影响分).
    新 yaml 无这两字段时为 None, 不影响新 caller 行为.
    """
    rule_id: str
    dimension: str                                # 'data_quality' / 'quality' / 'structure' / 'ai_coding'
    name: str
    description: str                              # 来自 yaml dim['rules'] 文本里抽不出时, fallback 为 name
    checklist: tuple[tuple[str, str], ...] = ()   # 子项清单 ((子项 key, 子项描述), ...) — yaml 暂未结构化, 默认空
    owner: str = ""                               # rule-level owner (通常 = dimension)
    status: RuleStatus = "active"
    cross_section: bool = False                   # 跨章节聚合规则 (V-05/V-06/RC-009)
    severity: Optional[Severity] = None           # step 3.6: 老 workspace yaml 'must'/'should', 新 yaml 为 None
    impact_score: Optional[float] = None          # step 3.6: 老 workspace yaml 0..1 影响分, 新 yaml 为 None


# ============================================================
# 例外定义
# ============================================================


class SchemaRegistryError(Exception):
    """yaml 加载/校验失败. message 含具体 file:path 让 PM 一眼定位."""


# ============================================================
# 跨章节规则白名单 (替代 aggregation.py 硬编码)
# ============================================================

# 跨章节规则: 这几条规则按设计本质上跨多个章节聚合.
# V-05 信息自洽性 / V-06 章节完整性 — yaml 已有, structure 维度
# RC-009 物理表定义一致性 — 跨字段映射多章节, data_quality 维度
# 后续 step 可改为 yaml 配 cross_section: true 字段, 这一步先用清单.
_CROSS_SECTION_RULES = frozenset(("V-05", "V-06", "RC-009"))


# ============================================================
# SchemaRegistry 主类
# ============================================================


class SchemaRegistry:
    """单点 source-of-truth for Pecker schema (规则 + 维度).

    使用方式:
        reg = SchemaRegistry.get(workspace="...")
        rule_ids = reg.all_rule_ids()
        rule = reg.get_rule("V-05")
        pattern = reg.rule_id_pattern()
    """

    # 模块级锁, 防 reload 与 get 并发
    _lock = threading.RLock()

    def __init__(self, rules: dict[str, RuleDef], dimensions: tuple[str, ...]):
        # rules: rule_id -> RuleDef (immutable view)
        self._rules: dict[str, RuleDef] = dict(rules)
        # dimensions: 出现过的 dimension key 列表 (按 yaml 顺序, 用 tuple 防误改)
        self._dimensions: tuple[str, ...] = dimensions

    # ----- 类入口 (lru_cache 单例) -----

    @classmethod
    def get(cls, workspace: Optional[str] = None) -> "SchemaRegistry":
        """主入口 — workspace 维度 lru_cache. 不同 workspace 返回不同实例.

        FastAPI 并发安全: 不同 workspace 用不同 instance, 同 workspace 复用.
        """
        # 把 workspace=None 解析成稳定 cache key (复用 dimensions._resolve_workspace_key 逻辑)
        from review.dimensions import _resolve_workspace_key
        key = _resolve_workspace_key(workspace)
        return cls._cached_get(key)

    @classmethod
    @lru_cache(maxsize=8)
    def _cached_get(cls, workspace_key: str) -> "SchemaRegistry":
        """按 workspace_key 缓存 instance. workspace=None / 空时 key=_DEFAULT_WS_KEY."""
        from review.dimensions import _DEFAULT_WS_KEY
        actual = None if workspace_key == _DEFAULT_WS_KEY else workspace_key
        return cls._build(actual)

    @classmethod
    def _build(cls, workspace: Optional[str]) -> "SchemaRegistry":
        """从 yaml 加载链构造 registry.

        加载策略:
        - 复用 review.dimensions.load_review_dimensions 拿 dim 数据
        - yaml 加载失败 → raise SchemaRegistryError
        - 但 PECKER_SCHEMA_FALLBACK=1 时 fallback 到空 registry (warn)
        """
        fallback_env = os.environ.get("PECKER_SCHEMA_FALLBACK", "").strip()
        try:
            return cls._load_from_dimensions(workspace)
        except SchemaRegistryError as exc:
            # 严格模式下抛出的 yaml 缺失/校验错也走 fallback env
            if fallback_env == "1":
                log.warning(
                    f"[schema_registry] yaml 加载失败 (workspace={workspace!r}), "
                    f"PECKER_SCHEMA_FALLBACK=1 走空 registry: {exc}"
                )
                return cls(rules={}, dimensions=())
            raise
        except Exception as exc:
            # 其他 unexpected error (yaml 损坏 / load_review_dimensions raise 等) → 包成 SchemaRegistryError
            if fallback_env == "1":
                log.warning(
                    f"[schema_registry] yaml 加载失败 (workspace={workspace!r}), "
                    f"PECKER_SCHEMA_FALLBACK=1 走空 registry: {exc}"
                )
                return cls(rules={}, dimensions=())
            raise SchemaRegistryError(
                f"加载 review-dimensions.yaml 失败 (workspace={workspace!r}): {exc}. "
                f"PM 修 yaml 或临时 export PECKER_SCHEMA_FALLBACK=1 让 server 起来."
            ) from exc

    @classmethod
    def _load_from_dimensions(cls, workspace: Optional[str]) -> "SchemaRegistry":
        """加载 yaml 构造 registry.

        策略:
        - dimensions.load_review_dimensions 只保留 rule_id+name (drop 了 status/owner),
          所以这里要直接读原 yaml 拿全字段.
        - 复用 dimensions._BASE_DIR / _YAML_FILENAME 路径常量.
        """
        import yaml

        from review.dimensions import _BASE_DIR, _YAML_FILENAME

        # 解析 yaml 路径链 (与 load_review_dimensions 同一优先级)
        ws_path = (
            os.path.join(workspace, "review-rules", _YAML_FILENAME)
            if workspace else None
        )
        global_path = os.path.join(_BASE_DIR, _YAML_FILENAME)

        yaml_path = None
        if ws_path and os.path.isfile(ws_path):
            yaml_path = ws_path
        elif os.path.isfile(global_path):
            yaml_path = global_path

        if yaml_path is None:
            raise SchemaRegistryError(
                f"找不到 {_YAML_FILENAME} (尝试 workspace={ws_path!r} / global={global_path!r})"
            )

        with open(yaml_path, "r", encoding="utf-8") as f:
            yaml_content = yaml.safe_load(f)

        if not yaml_content or "dimensions" not in yaml_content:
            raise SchemaRegistryError(
                f"yaml 内容缺 'dimensions' 顶级 key: {yaml_path}"
            )

        rules: dict[str, RuleDef] = {}
        dim_keys: list[str] = []

        for dim_key, dim_cfg in yaml_content["dimensions"].items():
            dim_keys.append(dim_key)
            checklist_items = dim_cfg.get("checklist", []) or []
            for item in checklist_items:
                # 跳过 enabled: false 的 rule
                if not item.get("enabled", True):
                    continue
                rule_id = (item.get("rule_id") or "").strip()
                if not rule_id:
                    continue
                # rule_id 格式校验 (与 yaml schema 的 pattern 同)
                if not re.match(r"^(V|RC|EV|FN)-\d+$", rule_id):
                    raise SchemaRegistryError(
                        f"非法 rule_id: {rule_id!r} (期望 ^(V|RC|EV|FN)-\\d+$, "
                        f"workspace={workspace!r})"
                    )
                # status: yaml 默认 'active', 老 yaml 'inactive' 兼容映射到 deprecated
                status_val = item.get("status", "active")
                if status_val not in ("active", "experimental", "noisy", "deprecated"):
                    if status_val == "inactive":
                        status_val = "deprecated"
                    else:
                        status_val = "active"

                rules[rule_id] = RuleDef(
                    rule_id=rule_id,
                    dimension=dim_key,
                    name=item.get("name", rule_id),
                    description=item.get("name", ""),  # yaml 暂无 description, 用 name
                    checklist=(),
                    owner=item.get("owner", dim_key),
                    status=status_val,                     # type: ignore[arg-type]
                    cross_section=(rule_id in _CROSS_SECTION_RULES),
                    severity=None,        # 新 yaml schema 不含 severity (留给老 yaml 转译填)
                    impact_score=None,    # 新 yaml schema 不含 impact_score
                )

        # step 3.6: anti-corruption layer — 6 workspace 老 review-checklist.yaml 转译 + merge
        # 关键: 即使老 yaml 有 RC-014 zombie, _merge_workspace_rules 走 global 优先级
        # 不让 zombie 复活. 老 yaml 缺失 / 损坏 fail-soft (返回 [] / 抛 SchemaRegistryError).
        if workspace:
            try:
                legacy_rules = _load_legacy_workspace_yaml(workspace)
                if legacy_rules:
                    rules = _merge_workspace_rules(rules, legacy_rules)
            except SchemaRegistryError:
                # yaml 损坏 — 重 raise (PM 必须修)
                raise
            except Exception as exc:
                # 其他 unexpected 错 — fail-soft (设计 doc: 老 yaml 不阻塞启动)
                log.warning(
                    f"[anti-corruption] 老 workspace yaml 加载异常 (workspace={workspace!r}): "
                    f"{exc}, 跳过 (走纯 global yaml)"
                )

        return cls(rules=rules, dimensions=tuple(dim_keys))

    # ----- 查询 API -----

    def all_rule_ids(self) -> frozenset[str]:
        """全部已知 rule_id (含 deprecated). frozen 防 caller 误改.

        替代 worker.py:138 valid_rule_ids 现算.
        """
        return frozenset(self._rules.keys())

    def get_rule(self, rule_id: str) -> RuleDef:
        """按 id 查 rule. 找不到 raise KeyError (caller 决定怎么处理)."""
        if rule_id not in self._rules:
            raise KeyError(f"未知 rule_id: {rule_id!r}")
        return self._rules[rule_id]

    def dimension_rules(self, dim_key: str) -> tuple[RuleDef, ...]:
        """某维度的 rule 列表 (按 yaml 顺序). 替代 worker.py:138 现算 valid_rule_ids."""
        return tuple(r for r in self._rules.values() if r.dimension == dim_key)

    def rule_id_pattern(self) -> str:
        """单点输出 rule_id 正则.

        替代散落 7 处硬编码 regex (#3 #8-#16). 当前实现按已知 rule_id 前缀动态拼,
        yaml 加 EV-/FN- 不需要改 caller — registry 会自动同步.
        """
        if not self._rules:
            # 空 registry (fallback 模式) — 给一个 permissive 默认, 避免 caller regex 崩
            return r"^(V|RC|EV|FN)-\d+$"
        prefixes = sorted({rid.split("-")[0] for rid in self._rules.keys()})
        return r"^(" + "|".join(prefixes) + r")-\d+$"

    def valid_prefixes(self) -> tuple[str, ...]:
        """已注册的 rule_id 前缀列表 (按字母序).

        替代 prompting.py 错误提示文本里的"RC-/V-/EV-/FN-"硬列举.
        加新前缀 (如 BMAD-XX / DQ-) 时自动出现, 不需要再改 prompting.

        Returns:
            按字母序排列的前缀 tuple, 如 ("EV", "FN", "RC", "V").
            空 registry 走 permissive 默认 ("EV", "FN", "RC", "V").
        """
        if not self._rules:
            return ("EV", "FN", "RC", "V")
        return tuple(sorted({rid.split("-")[0] for rid in self._rules.keys()}))

    def sample_rule_ids(self, n: int = 3) -> tuple[str, ...]:
        """各前缀挑代表 rule_id 给 prompt 当例子.

        给 worker 看"如 V-07 / RC-009 / FN-01"这种 sample 比单纯写正则更直观.
        每个前缀挑首个 rule_id (按 yaml 顺序), 最多 n 个.

        Args:
            n: 最多返几个 sample (按前缀分组后取首条).

        Returns:
            如 ("V-02", "RC-009", "EV-01") — 顺序按 valid_prefixes.
        """
        if not self._rules:
            return ()
        # 按前缀分组取首个
        seen_prefix: dict[str, str] = {}
        for rid in self._rules.keys():
            prefix = rid.split("-")[0]
            if prefix not in seen_prefix:
                seen_prefix[prefix] = rid
        # 按前缀字母序输出, 截 n 个
        sorted_prefixes = sorted(seen_prefix.keys())
        return tuple(seen_prefix[p] for p in sorted_prefixes[:n])

    def reload(self) -> None:
        """强制清 cache + 重 build (单测用; production 不暴露给 PM)."""
        with self._lock:
            type(self)._cached_get.cache_clear()


# ============================================================
# rule_perf 联动 view (骨架, step 3.5 联动 review_fixer 真填数据)
# ============================================================


# ============================================================
# Anti-corruption layer (step 3.6, 2026-04-27)
# ============================================================
#
# 背景: 6 workspace 各自有 review-checklist.yaml 老 schema:
#   {id, name, severity, description, impact_score}    # 老
# 新 yaml schema (review-dimensions.yaml):
#   {rule_id, name, status, owner, enabled, ...}       # 新
# 老 yaml 把 PM 标的 severity/impact_score 业务字段保住, 但缺 owner/status/dimension.
# 转译策略: 老字段 → 新 RuleDef, 缺的字段填 anti-corruption 默认.
# 冲突策略: 同 rule_id 在 global+legacy 都有 → global 优先 (新 yaml 已删的 zombie 不复活).

# 老 yaml 文件名 (与新 yaml review-dimensions.yaml 区分)
_LEGACY_YAML_FILENAME = "review-checklist.yaml"

# rule_id 前缀 → dimension 推断映射
# 设计 doc Part 4 要求: dimension 从 rule_id prefix 推断, 不让 caller 猜.
# 真实分布参考 review-dimensions.yaml:
#   V-XX:  V-02..V-06 在 structure, V-07..V-12 在 quality
#   RC-XX: RC-004..008/013/015 在 ai_coding, RC-009/010 在 data_quality
#   EV-XX: EV-01 在 structure, EV-04 在 data_quality
#   FN-XX: FN-09 在 structure, FN-03 在 ai_coding, FN-01 在 data_quality
# anti-corruption 用前缀**首选** dimension (老 yaml 无 dimension 字段), 真冲突走 global 优先级覆盖
_PREFIX_DIMENSION_HINT: dict[str, str] = {
    "V": "structure",        # 老 yaml 大多 V-XX 都在 structure (V-02 等), quality V-07+ 是新加
    "RC": "ai_coding",       # 老 yaml 全是 RC-004..010/013..015, 大多 ai_coding
    "EV": "structure",       # 验收类默认 structure
    "FN": "data_quality",    # 风鸟领域规则首选 data_quality
}

# 默认 fallback dimension (未知前缀 / 推断不出)
_DEFAULT_DIMENSION = "structure"


def _infer_dimension_from_prefix(rule_id: str) -> str:
    """从 rule_id prefix 推断 dimension (老 yaml 无 dimension 字段时用).

    策略:
    - V-XX → structure  (老 yaml 全是 structure 类)
    - RC-XX → ai_coding (老 yaml RC-004..010/013/015 大多是 ai_coding)
    - EV-XX → structure
    - FN-XX → data_quality
    - 未知 prefix → fallback _DEFAULT_DIMENSION

    冲突时 (legacy 推断与 global 实际不一致): _merge_workspace_rules 用 global 覆盖,
    所以本函数不强求与 global 完全匹配, 只是给 legacy-only rule 一个合法 dimension.

    Args:
        rule_id: 'V-02' / 'RC-004' / 'EV-01' / 'FN-09' / ZZ-99 (未知)

    Returns:
        合法 dimension key ('structure' / 'quality' / 'ai_coding' / 'data_quality').
        永不 raise, 未知前缀走 _DEFAULT_DIMENSION.
    """
    if "-" not in rule_id:
        return _DEFAULT_DIMENSION
    prefix = rule_id.split("-")[0]
    return _PREFIX_DIMENSION_HINT.get(prefix, _DEFAULT_DIMENSION)


def _load_legacy_workspace_yaml(workspace: str) -> list[RuleDef]:
    """anti-corruption: 把老 workspace-*/review-rules/review-checklist.yaml 转译成 RuleDef list.

    老 yaml schema (示例):
        rules:
          - id: RC-004
            name: 接口契约口径
            severity: must
            description: PRD 接口若涉及契约口径...
            impact_score: 0.7

    转译策略 (设计 doc Part 4):
    - id          → rule_id (校验 ^(V|RC|EV|FN)-\\d+$ 否则 skip + warn)
    - name        → name
    - description → description
    - severity    → RuleDef.severity (Optional['must','should'])
    - impact_score → RuleDef.impact_score (Optional[float])
    - dimension   → 从 rule_id prefix 推断 (_infer_dimension_from_prefix)
    - owner       → 默认 'legacy_workspace'
    - status      → 默认 'active' (兼容老行为)
    - cross_section → 按 _CROSS_SECTION_RULES 标 (与新 yaml 一致)
    - checklist   → ()  (老 yaml 没结构化子项)

    Args:
        workspace: workspace 目录绝对路径 (如 '/repo/workspace-劳动仲裁')

    Returns:
        RuleDef list. yaml 文件不存在 → 空 list (fail-soft, 不阻塞启动).

    Raises:
        SchemaRegistryError: yaml 损坏 / 无法解析 (硬错误, 让 PM 看见).

    Defensive:
        - 单条 rule 字段缺 (如 id 空) → skip + warn
        - rule_id 非法前缀 (如 ZZ-99) → skip + warn
        - 整个 yaml 损坏 → raise (PM 必须修)
    """
    import yaml as _yaml

    yaml_path = os.path.join(workspace, "review-rules", _LEGACY_YAML_FILENAME)
    if not os.path.isfile(yaml_path):
        return []

    # 2026-04-28: 先做硬校验 (语法损坏直接 raise, 与历史 behavior 一致),
    # 再走新 SSOT loader 拿到合并后的 rules (带 extends 自动展开).
    try:
        with open(yaml_path, "r", encoding="utf-8") as f:
            _yaml.safe_load(f)  # 仅做语法校验, 不用返回值
    except (_yaml.YAMLError, OSError) as exc:
        raise SchemaRegistryError(
            f"老 workspace yaml 损坏: {yaml_path}: {exc}"
        ) from exc

    try:
        from review.rule_loader import load_review_checklist
        raw_rules = load_review_checklist(workspace)
    except Exception as exc:
        raise SchemaRegistryError(
            f"老 workspace yaml 损坏 (SSOT loader 失败): {yaml_path}: {exc}"
        ) from exc

    if not isinstance(raw_rules, list):
        log.warning(
            f"[anti-corruption] {yaml_path}: SSOT loader 返回非 list, 跳过"
        )
        return []

    rule_id_pattern = re.compile(r"^(V|RC|EV|FN)-\d+$")
    translated: list[RuleDef] = []

    for idx, item in enumerate(raw_rules):
        if not isinstance(item, dict):
            log.warning(
                f"[anti-corruption] {yaml_path} rules[{idx}] 非 dict, skip"
            )
            continue

        # 老 yaml 用 id, 新 yaml 用 rule_id — 兼容两种
        raw_id = (item.get("id") or item.get("rule_id") or "").strip()
        if not raw_id:
            log.warning(
                f"[anti-corruption] {yaml_path} rules[{idx}] 缺 id/rule_id, skip"
            )
            continue

        if not rule_id_pattern.match(raw_id):
            log.warning(
                f"[anti-corruption] {yaml_path} rules[{idx}] id={raw_id!r} "
                f"不匹配 ^(V|RC|EV|FN)-\\d+$, skip"
            )
            continue

        # severity 解析 (must / should, 容错老 yaml 偶尔写 'MUST' 等)
        raw_severity = item.get("severity")
        severity_val: Optional[str] = None
        if isinstance(raw_severity, str):
            sv = raw_severity.strip().lower()
            if sv in ("must", "should"):
                severity_val = sv

        # impact_score 解析 (老 yaml 有时是 str '0.7', 有时是 float 0.7, 都接受)
        raw_score = item.get("impact_score")
        score_val: Optional[float] = None
        if raw_score is not None:
            try:
                score_val = float(raw_score)
                # clamp 到 [0, 1] 防老 yaml 误填超界
                if score_val < 0.0 or score_val > 1.0:
                    log.warning(
                        f"[anti-corruption] {yaml_path} {raw_id} impact_score={score_val} "
                        f"超出 [0, 1], clamp"
                    )
                    score_val = max(0.0, min(1.0, score_val))
            except (TypeError, ValueError):
                log.warning(
                    f"[anti-corruption] {yaml_path} {raw_id} impact_score={raw_score!r} "
                    f"无法转 float, 设 None"
                )

        translated.append(
            RuleDef(
                rule_id=raw_id,
                dimension=_infer_dimension_from_prefix(raw_id),
                name=item.get("name", raw_id),
                description=item.get("description") or item.get("name", ""),
                checklist=(),
                owner="legacy_workspace",      # 老 yaml 无 owner 字段, 标记来源
                status="active",                # 兼容老行为, 不让默认就 deprecated
                cross_section=(raw_id in _CROSS_SECTION_RULES),
                severity=severity_val,          # type: ignore[arg-type]
                impact_score=score_val,
            )
        )

    return translated


def _merge_workspace_rules(
    global_rules: dict[str, RuleDef], legacy_rules: list[RuleDef]
) -> dict[str, RuleDef]:
    """合并全局 review-dimensions.yaml + workspace 老 review-checklist.yaml.

    优先级 (与 P0-A iter_wiki_files 一致): **global > legacy**.
    冲突 (同 rule_id 两边都有) → global 完整覆盖 legacy.
    legacy-only rule (新 yaml 已删的, 如 RC-014 zombie) → drop + warn.

    设计意图: 新 yaml 是 source of truth, 已删的 rule 不让老 yaml 复活.
    老 yaml 只起"贡献历史业务字段"作用 (severity/impact_score 给同 rule_id 的 global rule
    填补 — 但当前实现暂不做此 enrichment, 留给后续 step), 已 deprecated 的 rule 不复活.

    Args:
        global_rules: rule_id → RuleDef (来自 review-dimensions.yaml)
        legacy_rules: RuleDef list (来自 _load_legacy_workspace_yaml)

    Returns:
        merged dict (rule_id → RuleDef). 完全等价于 global_rules 的子集 + 可能的字段 enrich.
        当前实现: 直接返回 dict(global_rules), legacy 只用来 warn drop 信息.
    """
    merged: dict[str, RuleDef] = dict(global_rules)
    global_ids = set(global_rules.keys())

    legacy_only_ids: list[str] = []
    for legacy_rule in legacy_rules:
        rid = legacy_rule.rule_id
        if rid not in global_ids:
            # legacy 有 / global 没有 — 新 yaml 已删, 不让老 yaml 复活 zombie
            legacy_only_ids.append(rid)

    if legacy_only_ids:
        log.warning(
            f"[anti-corruption] 老 workspace yaml 含 {len(legacy_only_ids)} 条 "
            f"全局已 drop 的 rule_id, 不复活 (zombie 防御): "
            f"{sorted(legacy_only_ids)}"
        )

    return merged


# ============================================================
# rule_perf 联动 view (骨架, step 3.5 联动 review_fixer 真填数据)
# ============================================================


@dataclass(frozen=True)
class SchemaRegistryWithPerf:
    """rule_perf 联动 view (read-only join). step 3.1 只放骨架.

    step 3.5 实际填: 内部 join schema + rule_perf_history.json (per-workspace),
    暴露 .precision_7d(rule_id) / .reject_rate_7d(rule_id) / .impact_adjusted(rule_id).
    """
    registry: SchemaRegistry
    workspace: str

    def precision_7d(self, rule_id: str) -> Optional[float]:
        """7 天精度 (实际逻辑留 step 3.5)."""
        return None

    def reject_rate_7d(self, rule_id: str) -> Optional[float]:
        """7 天 reject 率 (实际逻辑留 step 3.5)."""
        return None
