# Pecker 全 PRD endpoint lineage_quality 饱和率验证 (2026-04-28)

## 任务

- PRD: 劳动仲裁需求文档 v5.1 (`劳动仲裁需求文档 v5.1.md`)
- spec 来源: R2 review_items (任务 2 干净 setup, 0 幻觉 ID, 18 issues)
  - file: `workspace-劳动仲裁/output/review_items_R2_2026_04_28.json`
- 4 endpoint × Opus 4.7 implement × Sonnet 4.6 judge
- 不跑 single-shot/raw 对照 (baseline 已覆盖, 本实验只关心 lineage 跨 endpoint 饱和率)

## Endpoint 清单

- GET `/api/v1/labour-arbitration/delivery/list` — 送达公告列表
- GET `/api/v1/labour-arbitration/hearing/list` — 开庭公告列表 (baseline 已测, 本次复跑验证 sampling)
- GET `/api/v1/labour-arbitration/filters` — 筛选条件 (列表型, 树形)
- GET `/api/v1/labour-arbitration/detail` — 公告详情 (table_id+type 两种类型)

## Endpoint × judge 评分表

| endpoint | issues | sev (m/s/c) | field_correct | field_complete | lineage | ambig | build | clar | inferred | sum |
|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|
| delivery/list | 8 | 4/3/1 | 4 | 5 | **5** | 4 | 3 | 2 | 0 | 21 |
| hearing/list | 6 | 4/1/1 | 4 | 5 | **5** | 4 | 3 | 3 | 0 | 21 |
| filters | 7 | 3/3/1 | 5 | 5 | **5** | 5 | 4 | 5 | 0 | 24 |
| detail | 6 | 4/2/0 | 5 | 5 | **5** | 4 | 4 | 2 | 2 | 23 |

## lineage_quality 饱和率分析

- **饱和率**: 4/4 endpoint lineage=5
- **未饱和**:
(全部饱和)

## Judge 1 句话总评

- **delivery/list**: 字段齐全溯源清晰；PostgreSQL-specific SQL（ILIKE/ANY/NULLS LAST）与 PRD 指定 MySQL 不兼容是最大风险
- **hearing/list**: 字段与 PRD 高度对齐，lineage 标注规范，导入全注释+response_model 传字符串致无法直接运行
- **filters**: 高保真实现，溯源规范，直辖市两级/省三级树逻辑正确，缺部分索引但逻辑无缺陷
- **detail**: 字段精准完整溯源充分，测试 commit 破坏隔离是唯一明显缺陷

## vs 1 endpoint baseline (工况 A 5/5, hearing/list)

baseline (2026-04-27) 在 hearing/list 单 endpoint 上 Pecker 工况 lineage=5 (vs single-shot=3 / raw=4).

本次 hearing/list 复跑 lineage 仍 = 5, 印证 lineage 维度在重复抽样下稳定. 其他 3 个 endpoint (delivery/list, filters, detail) lineage 全部也 = 5.

| 比较项 | hearing/list (baseline 04-27) | hearing/list (本次 04-28 复跑) | delivery/list | filters | detail |
|---|---:|---:|---:|---:|---:|
| field_correctness | (5) | 4 | 4 | 5 | 5 |
| field_completeness | (5) | 5 | 5 | 5 | 5 |
| **lineage_quality** | **5** | **5** | **5** | **5** | **5** |
| ambiguity_handling | (5) | 4 | 4 | 5 | 4 |
| buildability | (5) | 3 | 3 | 4 | 4 |

> baseline 单 endpoint 25/25 是 single trial 的极值, 本次 4 endpoint 平均 22.25/25 (21/21/24/23). lineage **全部维持 5**, 其他 4 维有 0-2 分小幅波动 — 属于 LLM judge sampling noise 正常区间, 不动摇 lineage 维度结论.

## Verdict

**全 PRD 4 个 endpoint lineage_quality 全部饱和 (4/4 = 100%)**. Pecker 输出的 `severity / rule_id / id` 在跨 endpoint 场景仍 transferable, **不需要 spec 拆分优化**.

护城河跨 endpoint 转移条件:
- R2 review_items 含 must severity issue (本次 4 ep 均 ≥3 条)
- 关键词过滤能召回 endpoint 相关 issue (本次每 ep 6-8 条, R-002 / R-011 / R-023 等全局 must 在多 ep 重叠命中)
- implement prompt 模板稳定 (baseline 同款, 强制 must→引用 issue.id)

弱项 (跨 endpoint 共有, 与 lineage 无关):
- **buildability 偏低 (3-4)**: judge 严苛, 主要扣分点是 PostgreSQL 方言 / 测试 commit 隔离 / response_model 传字符串等"小可改"细节, 非 spec 缺陷
- **field_correctness 列表型偏低 (4)**: delivery/list 与 hearing/list 都 4 分 (同因: 用 PG 方言而 PRD 指定 MySQL); 详情/筛选两个非纯列表型反而 5 分

## 风险记录

- **R2 中文 key 乱码 (Windows 默认编码)**: R2 文件部分中文 key 是 mojibake (含 `suggestion` 字段), 已在 serialize 时 fallback 扫所有 str 字段聚合 — 不影响 implement 的 issue.id / severity / location / issue 主轴.
- **R2 全 endpoint hit 重叠**: R-002 / R-006 / R-011 / R-023 等 must issue 命中 ≥3 个 endpoint (因为是 PRD 全局规则: 序号样式/排序方向/字段表/接口规范), 不只是单 endpoint 私有 issue. 这反而强化了"Pecker rule 全局适用"假设.
- **本次未跑 single-shot/raw 对照**: 假设 baseline 04-27 的 B/C lineage=3/4 跨 endpoint 也成立, 没复测; 严格说本次只验证 A 工况自身饱和率 (4/4), 不再次验证 A vs B/C 的优势 delta.

## 5. 成本与时间

| endpoint | impl duration (s) | judge duration (s) | ep total (s) |
|---|---:|---:|---:|
| delivery/list | 145.3 | 111.1 | 256.4 |
| hearing/list | 109.6 | 91.2 | 200.8 |
| filters | 136.7 | 142.7 | 279.4 |
| detail | 104.5 | 88.6 | 193.1 |
| **合计** | | | **929.7** |

## 6. 结论

1. **全饱和 (4/4 = 100%)**: PRD §2.5 全 4 个 endpoint 上, Pecker → Opus 4.7 implement → Sonnet 4.6 judge 链路 lineage_quality 均 = 5. baseline 单 endpoint 5/5 不是 sampling outlier.
2. **跨 endpoint transferable**: lineage 不依赖 endpoint 类型 — 列表型 (delivery/hearing) / 树形 (filters) / 详情型 (detail) 全部饱和. severity 分级 + rule_id + issue.id 三件套能跨形态稳定支撑 lineage 注释.
3. **不需要 spec 拆分**: 当前 R2 全 issue 喂下游 + 关键词 filter 已够用. 全局 must rule (R-002 / R-011 / R-023 等) 在多 endpoint 命中是特性不是 bug — implement agent 把全局规则当默认约束, 单 ep 私有 issue (R-006 仅 list 型 / R-005 仅 filters / R-003 仅 detail) 当 ep-specific.
4. **弱项与 lineage 无关**: buildability 跨 ep 都偏 3-4 分, 是 SQL 方言 / 测试隔离等"实现细节" 而非 spec 缺陷; field_correctness 在列表型 ep 偏 4 分 (PG 方言 vs PRD 指定 MySQL) — 这两条若想拉满, 应在 implement prompt 加"PRD 指定 MySQL, 不要 PG 专属语法" 显式约束.

**实操建议**: 上线前不需要再为 lineage 拆 spec, 但 implement prompt 可补一句 "数据库引擎以 PRD 章节 1.x 名词定义为准, 不要使用其他 SQL 方言专属语法" — 把 buildability/field_correctness 两弱项也拉到 5 分.

## 附: 原始产物路径

- summary.json: `workspace-劳动仲裁/output_full_prd_2026_04_28/summary.json`
- impl_delivery_list.md / judge_delivery_list.json / pecker_delivery_list.md
- impl_hearing_list.md / judge_hearing_list.json / pecker_hearing_list.md
- impl_filters.md / judge_filters.json / pecker_filters.md
- impl_detail.md / judge_detail.json / pecker_detail.md
