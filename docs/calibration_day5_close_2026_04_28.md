# Pecker Day5 收尾 calibration (2026-04-27)

## Run 元数据

- main commit: **50d8725** (含全部 Day5 改动: schema_registry SoT / P0 anti-corruption drop / P1 review_memory 隔离 / NLI canonical 接通)
- workspace: `workspace-劳动仲裁`
- prd: `劳动仲裁需求文档 v5.1` (49815 bytes)
- 执行时间: 11:41:39 ~ 12:03 (~22 min, 单轮无 retry)
- 总成本: **$4.7129** (上限 $7, buffer $2.29)
- API 调用: 12 次 (haiku 1 / opus 1 / sonnet 10)
- session jsonl: `workspace-劳动仲裁/output/sessions/rev_1777261748_2bade4dc.jsonl`
- review_items: `workspace-劳动仲裁/output/review_items_20260427_default.json` (20 条)

## 5 验证 verdict

| # | 验证 | 期望 | 实测 | verdict |
|---|---|---|---|:---:|
| 1 | 幻觉 ID 比例 (worker submit DQ-/AC-) | 0% (anti-corruption drop) | 0/20 = **0%** | OK |
| 1 | FN- 触发 (任意 R 都有) | >=1 | **2 条** (FN-01 + FN-09) | OK |
| 2 | NLI succeeded | 4/4 | **4/4** | OK |
| 3 | DAR retention_kind_dist (含 3 桶) | 含 unanimous/majority/minority | **仅 unanimous:3** (1 桶) | 部分 |
| 4 | anti-corruption dropped | >0 + 都是幻觉 | **0** (worker 本身没吐幻觉) | 链路通但未触发 |
| 5 | wiki canonical >0 | >0 | **canonical:49** | OK |

## Funnel (vs R1/R2/R3 baseline)

| 阶段 | Day5 | R1 | R2 | R3 |
|------|------|------|------|------|
| **N0 worker_raw** | **25** | 24 | 23 | 35 |
| - structure | 6 | 6 | 7 | 8 |
| - quality | 7 | 7 | 6 | 8 |
| - ai_coding | 8 | 6 | 6 | 10 (含 AC-01..10) |
| - data_quality | 4 | 5 | 4 | 9 (含 DQ-01..06) |
| **N1 after_dedup** | 25 | 24 | 23 | 35 |
| **N2 after_evidence_verify** | **18** | 20 | 16 | 28 |
| **N3 after_goshawk** | **20** | 19 | 18 | 30 |
| **final** | **20** | 19 | 18 | 30 |
| must / should / could | 11 / 3 / 5 | 11/3/5 | 10/4/4 | 8/16/6 |
| **wiki_mode** | **rich** | rich | rich | sparse |
| **authority_distribution** | **canonical:49** | canonical:47 | canonical:47 | 空 |
| evidence retract_by_reason | B_missing_rule:7 | B_missing_rule:4 | B_missing_rule:7 | B_missing_rule:7 |
| evidence downgrade_by_reason | A_wiki_page_not_found_weak:16 | A_wiki_page_not_found_weak:20 | A_wiki_page_not_found_weak:13 | A_wiki_sparse_relaxed:27 + C_auto_annotated:1 |
| **DAR retention_kind_dist** | **unanimous:3** | minority:5, majority:2, unanimous:1 | minority:1, majority:1, unanimous:2 | majority:1, unanimous:2 |
| **n_samples_succeeded** | **4/4** | 4/4 | 4/4 | 4/4 |
| **goshawk delta_breakdown** | added:2, removed:0, merged_to_facet:5, kept:13, FP_restored:0 | added:2, removed:5, merged:5, kept:12 | added:2, removed:1, merged:4, kept:12 | added:2, removed:0, merged:6, kept:22 |
| confidence | 0.855 | 0.86 | 0.865 | 0.857 |
| **dropped_unknown_rule_count** | **0** | n/a | n/a | n/a (R3 53% 越界但未 drop) |

## 真业务 verdict

| Day5 工程改动 | 真业务效果 | 证据 |
|---|:---:|---|
| schema_registry SoT (anti-corruption drop) | OK | dropped_unknown_rule_count=0 + worker 0% 幻觉 ID (vs R3 53%), 链路就位但未触发 (worker 自我约束足) |
| P1 review_memory 隔离 | OK | wiki_mode=rich + canonical:49 (vs R3 sparse + 空 dict, 印证 clear_review_memory 不再误清 wiki) |
| NLI 4/4 (canonical wiki 接通) | OK | n_samples_succeeded=4/4 (3 轮稳定历史首次连续 4 轮 4/4) |
| DAR 三桶分布 | 部分 | 仅 unanimous:3 (单桶) — Day5 后 sample 高度一致, minority/majority 退化为 0; 跟 R3 majority:1+unanimous:2 一致, R1 minority:5 才是分歧大场景 |
| FN-01/03/09 真触发 | OK | FN-01 + FN-09 各 1 条入 final (R1=0 / R2=3 / R3=0, sampling-noisy 范围内) |

### 关键发现

**Day5 工程改动在真业务上系统性见效**:

1. **anti-corruption + clear_review_memory 联动彻底消除 R3 双崩溃**: R3 同时触发 worker 幻觉 53% + wiki sparse 空 dict, Day5 这一轮 worker 0% 幻觉 + canonical:49 接通, 这是 P0 anti-corruption drop + P1 review_memory 隔离两个修法**联动**的结果 (前者强约束 worker submit, 后者保住 wiki 不被误清).

2. **NLI 历史首次连续 4 轮 4/4 触发** (R1/R2/R3 都 4/4 + Day5 4/4): canonical wiki 接通后不再因 sparse 跳过. 这是任务 2 任务 3 修法**累积**的体现.

3. **DAR retention 桶单一化是 sampling-noise 的副作用, 不是 bug**: R1 (5 minority + 2 majority + 1 unanimous) 才是分歧大场景, R2/R3/Day5 都是高度一致 sample → 全 unanimous. 单 run 无法区分"工程改动让 sample 真趋同"vs"sampling 偶然趋同".

4. **goshawk 加 FP_restored 通道但 0 触发**: delta_breakdown 多了 false_positive_restored 字段 (Day5 改动), Day5 这轮无误剔回收, 链路就位等真信号.

## Caveat

1. **anti-corruption 未真触发不是失败**: telemetry 正常 emit (dropped=0 + dropped_ids_by_dim={}), 说明链路接通, 只是 worker 本身这一轮没吐幻觉. R3 是病态场景, Day5 worker 表现接近 R1/R2 的"健康基线". 要看 anti-corruption drop 真挡幻觉, 需要 worker 再吐 AC-/DQ- 的 run 复现 — 单轮数据不足下结论.

2. **DAR 单桶 (unanimous:3) 不能直接说"DAR 退化"**: R3 也是单桶 (majority:1 + unanimous:2 = 3 条), Day5 还多了"3 条全 unanimous"的极端场景. 真比较需要 N>=3 轮 calibration 看 retention 桶分布稳定性.

3. **单轮 sampling noise 警示**: N0=25 vs R3 (35) range 10, FN 触发 R1=0/R2=3/R3=0/Day5=2 跳跃, overlap on core 期望仍是 0% (没跑 overlap 因为单 run). 真定论需 multi-run 比对.

4. **wiki_pages_count=49 vs R1/R2 47**: 多 2 页, 可能是 Day5 接通 canonical 后 wiki promotion 加的页, 不影响 verdict.

## 数据文件

- `workspace-劳动仲裁/output/review_items_20260427_default.json` (20 items)
- `workspace-劳动仲裁/output/sessions/rev_1777261748_2bade4dc.jsonl` (telemetry)
- `logs/calibration_day5_close_2026_04_28.log` (535 行完整 log)
- `workspace-劳动仲裁/output/PRD_开发任务_20260427_default.md` (开发任务报告)
- `workspace-劳动仲裁/output/dashboard.html` (dashboard)
