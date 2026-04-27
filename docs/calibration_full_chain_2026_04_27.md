# Calibration Full Chain Report — 2026-04-27

> **目的**: 验证 FN-01/03/09 升 active + 修 yaml schema enum + hotfix 788900b re-land 后, 完整链路是否真接通。
> **PRD**: 劳动仲裁需求文档 v5.1 (`workspace-劳动仲裁/prd/`)
> **commit (跑此次 calibration 时)**: a45e3dd (main HEAD, fix(schema+goshawk) cherry-pick 后)
> **upstream commits**:
> - f288c9c feat(rules): 升 active FN-01/03/09 (yaml + checklist)
> - 89d28dc docs: 草稿状态 update
> - a45e3dd fix(schema+goshawk): yaml schema 扩 EV-/FN- + hotfix 788900b re-land

---

## Run 元数据

| 字段 | v1 (commit 49acf65) | v2 (commit a45e3dd, 真验证) |
|---|---|---|
| log | `logs/calibration_full_chain_2026_04_27.log` | `logs/calibration_full_chain_2026_04_27_v2.log` |
| 起始 | 01:03:01 | 01:23:55 |
| 结束 | 01:18:00 | 01:49:22 |
| Wallclock | ~9 min | ~26 min |
| Cost | $2.51 | $5.54 |
| API 调用 | 7 | 12 |
| Cache (creation/read) | 323k / 1.14M | 788k / 1.65M |
| **总成本** | (合计 $8.05) | |

---

## 4 验证 verdict 表 (核心)

| 验证项 | 上次 P0 hotfix 报告 | v1 (本次首跑) | **v2 (真验证)** | verdict |
|---|---|---|---|---|
| **DAR retention_kind_dist** | {majority:3, unanimous:2} | 0 emit (苍鹰崩) | **{majority: 4}** | **PASS** — DAR 真活, 4 sample 全 majority |
| **苍鹰真审 delta_breakdown** | {added:2, removed:1, merged:4, kept:23} | 0 emit (苍鹰崩) | **{added: 2, removed: 1, merged_to_facet: 4, kept_intact: 18, false_positive_restored: 0}** | **PASS** — 数字与上次报告级别一致 (24 finding base) |
| **wiki authority_distribution** | {generated: 10} (P1 bug) | (未到该阶段) | `{}` 空 dict, **wiki_mode: sparse** | **PARTIAL** — worker prompt 真拿到 49 页 (`[并行评审] Wiki: 49 页`), 但 evidence_verify 仍按 workspace/wiki 13 页判 sparse, authority_distribution 空 |
| **FN-01/03/09 触发** | N/A | 0 (yaml 降级硬编码, 规则没到 worker) | **0 fail** (cuckoo 识别 FN-, worker 没 submit FN-XX) | **PARTIAL** — yaml 真生效 + worker prompt 含 FN 规则文本, 但 worker 实际 submit 报的是幻觉 ID (DQ-XX/AC-XX) 而非 FN-01/03/09 |
| **NLI succeeded** | 0/29 (sparse) | (未到该阶段) | 不适用 (此 PRD 跑的是 worker + 苍鹰主链, NLI 只在 sparse 场景以外触发) | 同前 — sparse 模式不触发 |

---

## 关键发现

### 1) DAR / 苍鹰真审已 wire 通 (核心修法验证 PASS)

`final_reviewer_done` 事件 (session jsonl):
```
n_samples: 4, n_samples_succeeded: 4
retention_kind_dist: {majority: 4}
verdict: REVIEWED, confidence: 0.863
```
v1 跑 `n_samples_succeeded: 0` (4/4 全因 NoneType PathLike 崩), 修 hotfix re-land 后 4/4 全成功。`delta_breakdown` 同样从 0 emit 修复到完整 5 字段输出。

### 2) yaml schema 真接通 (yaml 降级 bug 修法验证 PASS)

v1 grep `全局 YAML 无效, 降级到硬编码` 命中 1 次, v2 命中 0 次。
worker 阶段 cuckoo Phase 0 输出明确含:
> 本次新增活跃规则 (上次未覆盖): V-05, V-06, V-07~V-12, EV-01, **FN-01, FN-03, FN-09**, RC-005~015

— 说明 25 条规则 (含 3 条 FN) 都进了 dynamic prompt。

### 3) canonical wiki 真活 (P1 修法部分验证 PASS)

`[并行评审] Wiki: 49 页` — _resolve_external_canonical_wiki + os.walk 递归生效, 49 个 canonical md 进了 worker prompt pool。但 wiki_mode 判定函数 `_is_wiki_sparse` 仍只看 `workspace/wiki/` 本地目录 (业务 md < 3 即 sparse), authority_distribution 仍空。这是 P1 的下一层 (evidence_verify 没接 canonical), 本次未修。

### 4) FN- 规则未真触发 (新发现的 prompt-binding 缺口)

虽然 yaml 真接通 + cuckoo Phase 0 高亮 FN-03 鉴权 TBD 为高风险, **但 4 个 worker 实际 submit 的 24 条 finding 中 0 条 FN-XX**, 全是幻觉 ID (DQ-01/AC-02/A-01 等)。这暴露 prompt 含 FN 规则文本 ≠ worker 真用 FN- 规则号 submit 的链路缺口。

可能原因 (本次未深查):
- worker dynamic prompt 中 FN-XX 文本可能被截断/排序靠后
- worker 在"先看通用 V-/RC- 是否捕获"提示下太保守, 直接编自己的 ID
- yaml checklist 给 worker 的 valid_rule_ids 是从 dim.checklist 派生, FN-09 在 structure / FN-03 在 ai_coding / FN-01 在 data_quality, 跨维度时不直接进 valid 集合

→ 后续 task: 加一轮 prompt 调优让 FN-XX 真被 worker 引用, 或加 worker 输出后处理把幻觉 ID 自动修正成最近的 FN-。

---

## vs 之前 calibration 对比

| 指标 | 真业务 v3 (劳动仲裁 v5.1, 2026-04-26) | **这次 v2 (2026-04-27)** | Delta |
|---|---|---|---|
| total finding (after_goshawk) | ~24 | **24** | 持平 |
| 苍鹰 delta_breakdown | full emit | full emit | 持平 |
| n_samples_succeeded | 4/4 | **4/4** | 持平 |
| wiki page count for worker | ~13 (sparse) | **49** (canonical 接通) | +36 page |
| FN- finding | 0 (规则没升) | **0 (规则升了但 worker 没用)** | prompt-binding 缺口 |
| Cost | ~$5 | **$5.54** | +10% |

---

## 风险记录

1. **prompt-binding 缺口** (新): worker prompt 有 FN-XX 但实际 submit 用幻觉 ID. 不解决 = FN 规则升级带不来 reject_rate 提升.
2. **evidence_verify 没接 canonical wiki**: 49 page 给 worker prompt 但不给 evidence verifier, 导致 sparse 误判 + authority_distribution 空 + 23 条 A 类被宽松降权 (可能掩盖真 fail).
3. **本次成本 $8.05 略超 $7 上限**: v1 $2.51 (失败 + 苍鹰崩 14.3s) + v2 $5.54 (完整链路). 失败 + 重跑双跑是必然代价, 因为首跑发现 hotfix 没真合进 main.
4. **hotfix 788900b 实际未合并**: 当前 main HEAD (commit 之前) `clients/claude_cli.py:_map_model(None) → None` + `goshawk_advisor.py:601/678 model=None`. 推测原 hotfix 在 rebase 中漏拉文件, commit message 写改 3 处但 git show 只看到 2 处。已在 a45e3dd re-land。

---

## 副产物

- `workspace-劳动仲裁/output/review_items_20260427_default.json` — 24 条 finding (无 FN-XX)
- `workspace-劳动仲裁/output/PRD_开发任务_20260427_default.md` — 开发任务报告
- `workspace-劳动仲裁/output/sessions/rev_1777224770_4de39875.jsonl` — 完整 telemetry (含 DAR / delta_breakdown / funnel)
- `logs/calibration_full_chain_2026_04_27_v2.log` — full run log (461 行)

---

## 下一步建议

1. **P0 修 prompt-binding 缺口**: worker prompt 末尾加 "你只能用这个 dim 的 valid_rule_ids 中规则号, 含 FN-XX. 列表如下: [FN-01 / FN-03 / FN-09 / V-XX / RC-XX]"。让 worker 拒绝幻觉 ID。
2. **P1 修 evidence_verify 接 canonical wiki**: `_is_wiki_sparse(wiki_dir)` 改成接 canonical merged 后的实际页面数, 让 wiki_mode 真 rich + authority_distribution 出值。
3. **P2 灰度跑 7 PRD**: 三波风鸟 PRD (劳动仲裁 / 侵权软件 / 纳税人资质 / 风鸟诉前调解 / ...) 都跑一遍, 看 FN-01/03/09 在不同 PRD 下的真触发率, 决定是否升 active 或继续打磨 prompt。

---

## 2026-04-27 update — schema_registry 接管

- ✅ P0 prompt-binding 缺口 — schema_registry step 3.3 已落地 `SUBMIT_REVIEW_ITEMS_TOOL` 动态 enum (来源 `registry.valid_rule_ids()`), worker 输出非 enum rule_id 直接被工具层拒。worker prompt 提示词由 step 3.5 的 `review/prompting.py` 通过 `valid_prefixes()` + `sample_rule_ids(3)` 动态生成, FN-XX 跨维度 valid 集合也接通。
- 上述第 1 项的 prompt 调优策略落到 schema_registry SoT, **本 doc 第 71 行"valid_rule_ids 是从 dim.checklist 派生 / 跨维度时不直接进 valid 集合"现象在 step 3.3 后由全 registry-driven enum 取代, 不再 dim 局部派生**.
- P1/P2 仍在 backlog, 由后续 sprint 跟进.

详见 `docs/schema_registry_design_2026_04_27.md` 实施回顾段.
