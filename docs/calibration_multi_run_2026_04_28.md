# Pecker multi-run 3 轮 calibration (2026-04-28) — schema_registry 真业务验证

## 元数据

- 3 轮跑劳动仲裁 v5.1, working tree 含 schema_registry 26 文件 (HEAD dc439b2 + 8 substep 落地, pytest 1073)
- PRD: `workspace-劳动仲裁/prd/劳动仲裁需求文档 v5.1.md` (49815 bytes)
- 任务: 验证 schema_registry 在真业务上是否达成"1 处改 6 处 propagate"预期 + 算 sampling noise + overlap on core
- 执行时间: 06:22 ~ 08:09 (约 1h47min, 含 4 次 R2/R3 失败 retry)
- 总成本: $5.19 (R1) + $4.69 (R2) + $5.47 (R3) = **$15.35** (上限 $18, 留 $2.65 buffer)

## R1 / R2 / R3 单轮指标

| 指标 | R1 | R2 | R3 |
|------|------|------|------|
| 总耗时 | ~22min | ~12min | ~13min |
| 成本 | $5.19 | $4.69 | $5.47 |
| 总 API 调用 | 12 | 12 | 12 |
| **N0 worker_raw** | 24 | 23 | **35** |
| - structure | 6 | 7 | 8 |
| - quality | 7 | 6 | 8 |
| - ai_coding | 6 | 6 | **10** (含 AC-01..10) |
| - data_quality | 5 | 4 | **9** (含 DQ-01..06) |
| N1 after_dedup | 24 | 23 | 35 |
| N2 after_evidence_verify | 20 | 16 | 28 |
| N3 after_goshawk | 19 | 18 | 30 |
| **final** | **19** | **18** | **30** |
| must / should / could | 11/3/5 | 10/4/4 | 8/16/6 |
| wiki_mode | rich | rich | **sparse** |
| authority_distribution | canonical:47 | canonical:47 | **空** |
| evidence retract_by_reason | B_missing_rule:4 | B_missing_rule:7 | B_missing_rule:7 |
| evidence downgrade_by_reason | A_wiki_page_not_found_weak:20 | A_wiki_page_not_found_weak:13 | A_wiki_sparse_relaxed:27 + C_auto_annotated:1 |
| **DAR retention_kind_dist** | minority:5, majority:2, unanimous:1 | minority:1, majority:1, unanimous:2 | majority:1, unanimous:2 |
| n_samples_succeeded | 4/4 | 4/4 | 4/4 |
| **苍鹰 delta_breakdown** | added:2, removed:5, merged_to_facet:5, kept:12 | added:2, removed:1, merged_to_facet:4, kept:12 | added:2, removed:0, merged_to_facet:6, kept:22 |
| confidence | 0.86 | 0.865 | 0.857 |

## Overlap on core

按 `(章节号, rule_id)` 严格聚类:

| 集合 | size |
|------|------|
| R1 | 19 |
| R2 | 18 |
| R3 | 30 |
| R1∩R2 | 0 |
| R1∩R3 | 0 |
| R2∩R3 | 0 |
| **三轮交集 (core)** | **0** |
| **overlap on core ratio** | **0%** |

按 `章节号宽松匹配` (取 `[一二三]/x.y` 章节号):

| 集合 | size |
|------|------|
| R1 (宽) | 18 |
| R2 (宽) | 18 |
| R3 (宽) | 29 |
| R1∩R2 | 3 |
| R1∩R3 | 5 |
| R2∩R3 | 7 |
| **三轮交集 (loose loc)** | **3** |
| **overlap ratio (loose)** | **10.3%** |

3 轮稳定识别的核心问题章节:
- 三/风险扫描 / 1.2 风险扫描洗数任务 (开发占位符)
- 二/企业主页 / 1.4 脱敏规则 (内部矛盾)
- 三/技术约定 / AI Coding 参考 (TBD 项)

## Sampling noise (DAR / 苍鹰跨 3 轮)

### 总条数 / severity 方差

| 字段 | R1 | R2 | R3 | range |
|------|------|------|------|------|
| total | 19 | 18 | 30 | **12** |
| must | 11 | 10 | 8 | 3 |
| should | 3 | 4 | 16 | **13** |
| could | 5 | 4 | 6 | 2 |

R3 should 暴增是因为 16 条幻觉 ID (AC/DQ-) 标 should/could 默认严重度。

### N0 worker_raw 波动

| | structure | quality | ai_coding | data_quality | total |
|---|---|---|---|---|---|
| R1 | 6 | 7 | 6 | 5 | **24** |
| R2 | 7 | 6 | 6 | 4 | **23** |
| R3 | 8 | 8 | **10** | **9** | **35** |
| range | 2 | 2 | 4 | 5 | 12 |

R3 ai_coding/data_quality worker 在 schema_registry 启用后**变本加厉吐幻觉 ID** (AC-01..10 / DQ-01..06), 不是 schema_registry 本意。

### DAR retention_kind_dist 跨 3 轮

| | minority | majority | unanimous |
|---|---|---|---|
| R1 | **5** | 2 | 1 |
| R2 | 1 | 1 | 2 |
| R3 | 0 | 1 | 2 |
| range | 5 | 1 | 1 |

minority 数差异巨大 (R1=5, R3=0). 表示 R1 时苍鹰 sample 之间分歧大, R3 sample 趋于一致 (但部分原因是 R3 worker 提交了大量低质量越界 item, sample 容易达成 unanimous).

### 苍鹰 delta_breakdown 跨 3 轮

| | added | removed | merged_to_facet | kept_intact |
|---|---|---|---|---|
| R1 | 2 | 5 | 5 | 12 |
| R2 | 2 | 1 | 4 | 12 |
| R3 | 2 | 0 | 6 | **22** |
| range | 0 | 5 | 2 | 10 |

added 极稳定 (3 轮都 = 2). removed 大方差 (5→0), 因为 R3 苍鹰**未识别幻觉 ID 为 false positive 而 kept**。kept_intact 跨 3 轮 12→22 成倍跳, 主要因为 R3 N3=30 vs 之前 N3=19。

## Schema_registry 真业务效果

| 关键 | R1 | R2 | R3 | 发挥作用? |
|------|------|------|------|------|
| **FN- 触发率** (worker submit 含 FN-rule) | 0 | **3** (FN-01/03/09) | 0 | R2 部分起作用 |
| **worker submit 用幻觉 ID 比例** | 0 | 0 | **16/30 = 53%** | R3 完全失守 |
| - 幻觉前缀 | - | - | AC-01..10, DQ-01..06 | |
| **wiki canonical 接通** | canonical:47 | canonical:47 | **空** (sparse 模式) | R1/R2 接通, R3 退化 |
| **NLI 触发** (n_samples_succeeded) | 4/4 | 4/4 | 4/4 | DAR 4 sample 全活 |
| **evidence_verify wiki_mode** | rich | rich | sparse | R3 wiki 目录不存在又退化 |
| **anti-corruption 是否拦截幻觉 ID** | n/a | n/a | **不拦截** (warn-only) | 设计缺陷 |

### 关键发现 1: R3 schema_registry **检测但不拦截幻觉 ID**

R3 logs 出现 26 条 `规则越界` warning:
```
07:52:09 [pecker.parallel] WARNING: [技术编辑] 规则越界: AC-01 不在 ai_coding checklist 中
... (AC-01..10 + DQ-01..06)
```

但这些条目 **照样进 final json** (cross_boundary=True 标注 + confidence-0.3 降权, 但不 drop). schema_registry 检出率 100%, 拦截率 0%.

### 关键发现 2: R3 wiki 退回 sparse, evidence verification 完全空跑

R3 `wiki_mode=sparse, authority_distribution={}` 表示 wiki canonical 通道断开 (workspace-劳动仲裁/wiki 目录被 R2 完成时清掉了 + R3 启动前我手动 rm -rf .review_memory 把 wiki 也连带没了). 全部 28 条都被 `A_wiki_sparse_relaxed` 降权.

### 关键发现 3: schema_registry zombie 防御稳定生效

3 轮 logs 均看到:
```
[pecker.schema_registry] WARNING: [anti-corruption] 老 workspace yaml 含 1 条 全局已 drop 的 rule_id, 不复活 (zombie 防御): ['RC-014']
```

RC-014 已废弃, schema_registry 阻止它从 workspace yaml 复活. 这部分 anti-corruption 工作正常.

## Verdict

**schema_registry 在真业务上未达成"1 处改 6 处 propagate"预期**, 关键证据:

1. **anti-corruption 设计为 warn-only 不 drop** (`review/worker.py` `# P1.3: 规则越界硬校验` 但只标 cross_boundary + 降权 0.3, 不 drop). 这是产品决策但 R3 暴露其在真业务上**完全无法兜底 worker 大规模幻觉**.

2. **3 轮 sampling noise 比预期更剧烈**:
   - N0 worker_raw range = 12 (24/23/35)
   - final range = 12 (19/18/30)
   - overlap on core (严格) = 0%, overlap on loose loc = 10.3% (低于 sampling_noise memory 14.5% baseline)
   - **未达成"schema_registry 缩 sampling noise"假设**

3. **FN- 新规则触发率 = 0/3/0**, 不稳定. R2 部分发挥作用 (FN-01/03/09 各一次), 但 R1/R3 工人完全不用. schema_registry 注入 prompt 后 worker 是否真用 FN- 是 sampling-noisy 的.

4. **但有部分胜利**:
   - zombie 防御 (RC-014) 3 轮稳定生效
   - 苍鹰 added 跨 3 轮稳定 = 2 (minority 保留正常)
   - DAR n_samples_succeeded 4/4 (3 轮全活, 比之前 sparse 场景跳过的好)

## 风险记录

- **R2 第一次 retry 4 次失败 (claude -p "对话太长")**: 第 5 次手动 `rm -rf workspace-劳动仲裁/output/.review_memory .sessions` 后通过. 推测 mem dir 残留致 system_prompt 涨大跨 argv 边界. 建议 worker 启动前清 mem cache.
- **R3 wiki_mode=sparse**: 因清理 .review_memory 也连带 wiki/, evidence verify 全部 fallback 到 A_wiki_sparse_relaxed. 影响 R3 的 verification_status 全 failed (29/30 failed + 1 verified). 反而 R1/R2 wiki_mode=rich (canonical:47) 是真信号.
- **R1 verification 全 failed (19/19)**: 不是因为 wiki sparse, 是因为 reason="B_missing_rule" + "A_wiki_page_not_found_weak". 验证逻辑认为这些 issue 没有对应 rule 或对应 wiki 页面, 跟 schema_registry 没关系.

## 数据文件

- `workspace-劳动仲裁/output/review_items_R1_2026_04_28.json` (19 items)
- `workspace-劳动仲裁/output/review_items_R2_2026_04_28.json` (18 items)
- `workspace-劳动仲裁/output/review_items_R3_2026_04_28.json` (30 items)
- `logs/calibration_multi_run_r1_2026_04_28.log` (R1 完整 log, 420 行)
- `logs/calibration_multi_run_r2_attempt5_2026_04_28.log` (R2 完整 log, 465 行)
- `logs/calibration_multi_run_r3_v2_2026_04_28.log` (R3 完整 log, 544 行)
- `workspace-劳动仲裁/output/sessions/rev_1777242419_ebc00984.jsonl` (R1 telemetry)
- `workspace-劳动仲裁/output/sessions/rev_1777245845_41d31240.jsonl` (R2 telemetry)
- `workspace-劳动仲裁/output/sessions/rev_1777247441_61af8924.jsonl` (R3 telemetry)
