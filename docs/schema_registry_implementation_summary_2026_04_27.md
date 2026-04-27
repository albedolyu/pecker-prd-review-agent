# schema_registry 8 substep 实施 summary (2026-04-27)

## TL;DR

- `review/schema_registry.py` 单点 SoT 落地, **17 wiring 点**全部归一
- 8 substep / 12h wall clock / **+141 新测试** / pytest 932 → 1073
- 加规则改 1 处 6 处自动 propagate (e2e 层证明)
- RC-014 zombie 端到端不复活 (anti-corruption 6 workspace 全过)
- 不动 hotfix 路径 (`goshawk_advisor.py` / `clients/claude_cli.py` 不在变更范围)

---

## 改动文件清单 (7 production + 6 测试)

### Production (7)

| 文件 | 净行数变化 | 说明 |
|---|---|---|
| `review/schema_registry.py` | **+604 (新)** | 单点 SoT, valid_rule_ids / rule_id_pattern / valid_prefixes / sample_rule_ids / anti-corruption transformer 全集中 |
| `review/dimensions.py` | **−91** | 删 `_DEFAULT_REVIEW_DIMENSIONS` + `_DEFAULT_DIMENSION_WIKI_KEYWORDS`, 改为从 registry 拉 |
| `review/worker.py` | **+39** | `SUBMIT_REVIEW_ITEMS_TOOL` 加动态 enum (`registry.valid_rule_ids()`) |
| `review/evidence_verify.py` | **+76** | regex `(RC|V|EV|FN)-\d+` SoT 化, 改用 `registry.rule_id_pattern()` |
| `review/prompting.py` | **+38** | worker prompt 错误提示文本动态化 (`valid_prefixes()` + `sample_rule_ids(3)`) |
| `review_fixer.py` | **+19** | regex SoT 化 (有 word boundary caveat, e2e 注释覆盖) |
| `cuckoo_scorer.py` | **+25** | rule_id 引用全部 SoT 化 |
| `parallel_review.py` | **−2** | re-export `_DEFAULT_REVIEW_DIMENSIONS` 删 (内部符号 `_` 开头, 无 public contract) |

### 测试 (6 新文件 + 已有扩展)

| 文件 | 测试数 | 说明 |
|---|---|---|
| `tests/test_schema_registry.py` | 14 | step 3.1 骨架单测 |
| `tests/test_dimensions_registry_wiring.py` | 14 | step 3.2 dimensions 接 registry |
| `tests/test_worker_dynamic_enum.py` | 7 | step 3.3 SUBMIT_REVIEW_ITEMS_TOOL 动态 enum |
| `tests/test_evidence_verify_registry.py` | 10 | step 3.4 evidence_verify regex SoT |
| `tests/test_prompting_registry.py` + `test_review_fixer_registry.py` + `test_cuckoo_scorer_registry.py` | 47 | step 3.5 三处接 registry |
| `tests/test_schema_registry_anticorruption.py` | 27 | step 3.6 5 workspace 老 yaml schema 转译 |
| `tests/test_schema_registry_e2e.py` | 28 | step 3.7 端到端集成 (加规则 / 加前缀 / RC-014 zombie 不复活) |

**总计: +147 测试用例, pytest 1073 全绿**.

---

## 8 substep 路线图 (PM 审 PR 时按这顺序看)

1. **step 3.1** — `review/schema_registry.py` (骨架) + `tests/test_schema_registry.py`
2. **step 3.2** — `review/dimensions.py` (删 fallback dict) + `parallel_review.py` (re-export 删) + `tests/test_dimensions_registry_wiring.py`
3. **step 3.3** — `review/worker.py` (SUBMIT_REVIEW_ITEMS_TOOL 动态 enum) + `tests/test_worker_dynamic_enum.py`
4. **step 3.4** — `review/evidence_verify.py` (regex SoT) + `tests/test_evidence_verify_registry.py`
5. **step 3.5** — `review/prompting.py` + `review_fixer.py` + `cuckoo_scorer.py` + 3 测试
6. **step 3.6** — `review/schema_registry.py` (anti-corruption section, 5 workspace 老 yaml schema) + `tests/test_schema_registry_anticorruption.py`
7. **step 3.7** — `tests/test_schema_registry_e2e.py` (端到端集成)
8. **step 3.8** — `docs/*` (本次, 不动代码)

---

## 关键 e2e 用例 (来自 `tests/test_schema_registry_e2e.py`)

- ✅ 加新规则 V-13 / RC-017 / FN-04 → registry 1 处改 → 6 处自动 propagate (worker enum / evidence_verify regex / prompting hint / cuckoo / dimensions / review_fixer)
- ✅ 加新前缀 DQ-99 → 正确 raise `SchemaRegistryError`, 强制 PM 改 `schema_registry.py` 一处, 不能绕过
- ✅ RC-014 在所有 6 workspace anti-corruption 转译时被 fail-safe drop, 端到端不复活 (主链路 finding 中无 RC-014)
- ✅ 5 workspace 老 yaml schema (`rules` 数组) 转译成 SoT 兼容 dict 100% 通过

---

## 后续 backlog (本次未处置)

- 5 workspace 老 yaml 手动清 zombie (RC-014 等) — anti-corruption fail-safe 已挡, 但 PM 可清 yaml 让 SoT 干净
- 6 workspace yaml byte-by-byte 一致 → 后续可考虑合到全局 yaml 删 `review-checklist.yaml` 这套并行 schema
- `review_fixer` regex 无 word boundary 边缘 bug (`tests/test_schema_registry_e2e.py` 注释了 caveat)
- `rule_perf` wiring (设计 doc `with_perf` 接口骨架已落, 联动 step 留下次)
- `evidence_verify` 接 canonical wiki (sprint Day4 calibration_full_chain_2026_04_27.md P1 项, 不在 schema_registry 范围)

---

## 验收清单 (PM 审 PR 前自查)

- [ ] `pytest` 1073 全绿
- [ ] `grep -rn "_DEFAULT_REVIEW_DIMENSIONS\|_DEFAULT_DIMENSION_WIKI_KEYWORDS" review/ --include="*.py"` 0 命中
- [ ] `grep -rn "(?:RC|V|EV|FN)-\\\\d" review/ --include="*.py"` 仅命中 `review/schema_registry.py` (SoT) + `review/dimensions.py` 注释 / 默认 yaml
- [ ] `tests/test_schema_registry_e2e.py` 加新规则 case 通过
- [ ] `tests/test_schema_registry_anticorruption.py` 6 workspace 全过
- [ ] hotfix 路径 (`goshawk_advisor.py` / `clients/claude_cli.py`) 不在 PR diff

---

**生成日期**: 2026-04-27
**关联文档**:
- `docs/schema_registry_design_2026_04_27.md` (设计 doc, 末尾有实施回顾)
- `docs/audit_drift_pollution_2026_04_26.md` (Day4 漂移审查, 末尾有 04-27 update 标修复项)
- `docs/calibration_full_chain_2026_04_27.md` (full chain 验证, 末尾有 04-27 update 标 P0 接管)
