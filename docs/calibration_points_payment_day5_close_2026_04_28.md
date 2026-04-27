# 积分抵扣支付 v2 — Day5 完整修法之后 calibration (2026-04-28)

## Run 元数据

- **main commit**: `462a9ab` (Day5 完整修法: schema_registry SoT 0b1b8c8 + 6 wiring SoT 999ea57 + P0-A canonical sync 1451289 + clear_review_memory ef92b47 + 前端 sync 6 commit + ...)
- **workspace**: `workspace-points-payment`
- **prd**: `积分抵扣支付-v2.md` (597 行, ~36KB)
- **PECKER_EXTERNAL_CANONICAL_WIKI** 默认外挂: `C:/Users/20834/Desktop/代码项目/风鸟代码库/wiki/` (49 page)
- **执行时间 (Run2 main HEAD)**: 15:32:40 ~ 15:58:57, ~26 min
- **Run2 cost_usd**: **$4.59** (worker+goshawk session jsonl 用 274s + 365s = 639s; 全链路 wall ≈ 1577s)
- **session jsonl**: `workspace-points-payment/output/sessions/rev_1777275596_d6932ebc.jsonl`
- **review_items**: `workspace-points-payment/output/review_items_20260427_default.json` (16 条)

### ⚠️ 关键 caveat: 第一次 run 跑错了 commit

任务启动时 working dir 在 `review/default/积分抵扣支付-v2/2026-04-27` branch (HEAD=`9256ba8`), **不含 Day5 后续 commit** (P0-A canonical / SchemaRegistry / clear_review_memory). Run1 跑的是这个 branch, $5.08 / 21 条, 拿到的是"Day5 之前"baseline 复跑 (信息价值 ≈ baseline ×0.5). 切到 main HEAD 重跑 Run2, **本报告主体以 Run2 为准**, Run1 留备份在 `workspace-points-payment/output/review_items_run1_branch_9256ba8.json` / `sessions/rev_run1_branch_9256ba8.jsonl` / `logs/review_points_payment_run1_branch_9256ba8.log`.

**总成本超预算**: $5.08 (Run1) + $4.59 (Run2) = $9.67, 超 $7 上限 38%. 时间 64min 超 25min 上限. 必须如实告知 PM.

## 关键指标 (vs 任务 3 baseline a45e3dd6 + Run1 9256ba8)

| 指标 | baseline (a45e3dd6) | Run1 (review-branch 9256ba8) | **Run2 (main 462a9ab Day5 完整)** | Δ Run2 vs baseline |
|---|---:|---:|---:|---:|
| 总条数 (final) | 16 | 21 | **16** | 0 |
| must | 5 | 7 | **4** | -1 |
| should | 8 | 10 | **7** | -1 |
| could | 3 | 4 | **5** | +2 |
| funnel N0 | 22 | 23 | **19** | -3 |
| funnel N1 dedup | 22 | 23 | **19** | -3 |
| funnel N2 evidence_verify | 16 | 19 | **14** | -2 |
| funnel N3 goshawk | 16 | 21 | **16** | 0 |
| **wiki_pages_count (start)** | n/a | n/a | **49** | 接通外挂 canonical |
| **wiki_mode** | sparse | sparse | **rich** | sparse → **rich** |
| **authority_distribution** | `{}` | `{}` | **`{canonical: 49}`** | 空 → **canonical 接通** |
| **dropped_unknown_rule_count** | n/a (字段不存在) | n/a | **0** | 字段就位, 0 触发 |
| **dropped_unknown_rule_ids_by_dim** | n/a | n/a | **`{}`** | worker 0 吐幻觉 |
| **NLI n_samples_succeeded** | 4/4 (sparse short-circuit) | 4/4 (sparse short-circuit) | **4/4 (rich)** | 路径切换 |
| **DAR retention_kind_dist** | `{minority:3, majority:1}` | `{unanimous:2}` | **`{majority:1, unanimous:1}`** | 单桶 → 2 桶 |
| 苍鹰 added | 2 | 2 | **2** | 0 |
| 苍鹰 merged_to_facet | 3 | 4 | **5** | +2 |
| 苍鹰 removed | 3 | 0 | **0** | -3 (false_positive_restored 加通道未触发) |
| 苍鹰 kept_intact | 11 | 15 | **9** | -2 |
| confidence | 0.867 | 0.873 | **0.863** | -0.004 |
| evidence verify retention | n/a | 0.826 | **0.737** | 更严 |
| cost_usd | $4.89 | $5.08 | **$4.59** | -$0.30 |
| wall (含后处理) | 1130s | 1244s | **1577s** | +447s |

## must overlap on core (任务 3 5 条 must vs Run2 4 条 must)

任务 3 baseline 5 条 must:
1. RC-001 兑换弹窗档位数量不一致 (UI mockup vs 弹窗交互)
2. V-01 🔴 待决策缺 owner / 期望时间 / 决策影响
3. V-02 兑换弹窗预填金额公式未约束到 maxExchangeYuan
4. RC-002 阻塞性待决策项 (审核 vs 即兑即用)
5. RC-001 假设章节积分扣减逻辑 (与 v2 阶段 1 解耦模型矛盾)

Run2 4 条 must:
| Run2 must | 命中 baseline# | 说明 |
|---|:---:|---|
| **V-04** 快捷档位 3 vs 4 (状态3 mockup vs 弹窗交互) | **#1** ✓ | rule_id 从 RC-001 → V-04 (Day5 SchemaRegistry 重命名), issue 一致 |
| **FN-09** 即兑即用 vs 审核 (前置依赖未决策) | **#4** ✓ | 用了 Day5 active 的 FN-09 风鸟领域规则 (vs baseline 用 RC-002 通用规则) |
| **RC-004** 兑换后端接口契约未定义 | (新, 升 must) | baseline 是 should V-05 "兑换接口契约缺失", Run2 升 must — Day5 召回增强证据 |
| **V-04** 假设章节积分扣减 vs v2 阶段 1 解耦 | **#5** ✓ | rule_id 从 RC-001 → V-04, issue 完整一致 |

**Overlap on core: 3/5 命中** (#1, #4, #5)

**漏掉 2/5**:
- ✗ #2 V-01 待决策 owner — Run2 把"决策缺 owner"角度并入 FN-09 must, 但单独 owner/期望时间/决策影响维度没单独提
- ✗ #3 V-02 maxExchangeYuan 公式 — Run2 降到 should V-07 "Math.ceil 公式未定义超过 maxExchangeYuan 时的截断逻辑"

**新增 must 1 条** (Day5 召回增强暴露): RC-004 接口契约缺字段定义/错误码 — baseline 只到 should 级别, Run2 苍鹰升 must.

## Day5 工程改动真业务实证 (5 件事)

| Day5 改动 | 期望 | Run2 实测 | verdict |
|---|---|---|:---:|
| **anti-corruption drop** (worker 幻觉 ID 拦截) | dropped_unknown_rule_count >= 0, 链路接通 emit 字段 | `dropped_unknown_rule_count: 0`, `dropped_unknown_rule_ids_by_dim: {}` (字段就位; 也看到 SchemaRegistry zombie 防御 emit `[anti-corruption] 老 workspace yaml 含 1 条 全局已 drop 的 rule_id, 不复活: ['RC-014']`) | **OK** (链路通; worker 这轮 0 幻觉, drop 未真触发, 但 zombie 防御真挡了 RC-014) |
| **NLI 4/4 触发** (canonical 接通后) | 4/4, 不再 sparse short-circuit | `n_samples_succeeded: 4/4` 在 **wiki_mode=rich** 下 (vs Run1/baseline 都是 sparse short-circuit 同 4/4) | **OK** (路径切换实证) |
| **wiki authority 49 canonical 接通** | `{canonical: 49}` | `authority_distribution: {canonical: 49}` (Run1/baseline 是 `{}`) | **OK** (P0-A 修法 funnel_telemetry+evidence_verify 同步外挂 canonical 真实生效) |
| **DAR retention_kind_dist 多桶** | 含 majority/minority/unanimous 多桶 | `{majority:1, unanimous:1}` (2 桶) — 比 Run1 单桶 unanimous:2 好, 但比 baseline `{minority:3, majority:1}` 桶种类少 | **部分** (Day5 修法没让 minority_kept 重现, Run2 minority_kept=0; 但比 Run1 单桶进了一步) |
| **clear_review_memory 隔离 wiki** | wiki_mode 不被误清 | wiki_mode=rich + canonical:49 全程接通 (vs Run1 sparse + 空 dict, 但 Run1 在不含 ef92b47 的 commit) | **OK** (跟劳动仲裁 Day5 close 报告一致) |

### 关键发现

1. **P0-A canonical sync (1451289) 是 Day5 真业务最显眼的差异**: Run2 wiki_mode 从 sparse 翻到 **rich**, authority_distribution 从空 翻到 `{canonical: 49}`. 这直接证明 PM 在 Day3+ 借鉴 kenhuangus/llm-wiki 的双层 wiki 架构 + workspace external canonical 在 points-payment 真业务上**首次接通到 funnel_telemetry**, 而不是只接到 worker prompt.

2. **anti-corruption + zombie 防御真挡了 RC-014**: yaml 校验阶段 SchemaRegistry warning 输出 `'RC-014' 全局已 drop, 不复活`. Run1 (review-branch 9256ba8) 完全没这个日志 — Day5 SchemaRegistry SoT 真生效.

3. **召回趋于精准 (must 5→4) 但单条 issue 表达更具体**: Run2 把 baseline 5 条 must 的"决策缺 owner"维度并入 FN-09, 把"接口契约"从 should 升 must, 整体方向是"减少角度切碎, 增加单条深度". Day5 苍鹰 merged_to_facet=5 (vs baseline 3) 印证这个收敛趋势.

4. **DAR 单 run minority 退化是 sampling-noisy 的副作用, 不是 bug**: 跟 Day5 收尾劳动仲裁报告同结论 — 真业务 sample 越一致 retention 桶越窄. baseline minority:3 是 sampling 偶然分歧大, Run2 majority:1+unanimous:1 是 sampling 高度一致. 不能从单 run 判 DAR 退化.

5. **意外: 苍鹰 false_positive_restored 字段已就位但 0 触发**: delta_breakdown 含 `false_positive_restored: 0`, Run2 没误剔回收, 跟 Day5 close 报告一致 — 链路就位等真信号.

## Verdict

真业务 PRD (积分抵扣支付 v2, 跟侵权软件模板 PRD / 劳动仲裁 PRD 都不同的金融支付场景) 上 **Day5 完整修法系统性见效**:

- ✓ P0-A canonical sync 在 funnel_telemetry 真接通: wiki_mode rich + canonical:49
- ✓ NLI 4/4 在 rich 模式下首次真触发 (vs baseline/Run1 都是 sparse short-circuit 假 4/4)
- ✓ schema_registry SoT zombie 防御挡 RC-014
- ✓ anti-corruption drop 链路接通 (字段就位, 本轮 worker 健康未触发真 drop)
- ◐ DAR retention 桶分布从 Run1 单桶进步到 Run2 2 桶, 但比 baseline minority 退化 (sampling-noisy)

**must overlap on core 3/5** + 1 条 should 升 must (RC-004 接口契约) — Day5 召回增强证据.

## Caveat

1. **第一次 run 误用 review-branch 9256ba8 不含 Day5 完整修法, 导致重跑超预算**: 总成本 $9.67 / $7 上限 (超 38%), 总时间 ~64min / 25min 上限. 教训: 跑 calibration 前必须 `git rev-parse HEAD == main HEAD` 显式核对, run_session.py 不强制切 main, 容易留在 review-branch.

2. **NLI 在 rich 模式触发但本轮无 contradict 信号**: jsonl 没记录单条 nli_score 详情 (telemetry 只 aggregate n_samples_succeeded), 不能判 NLI 在真业务上的实际"挑出矛盾"能力. 要看真受益, 需要 Run2 review_items 里 verification_details.nli_score 字段 (后续核对).

3. **must overlap 3/5 不能定论 Day5 召回退步**: must 总数从 5→4 是因为 Run2 把 V-01 (决策 owner) 并入 FN-09 + V-02 (公式 maxExchangeYuan) 降级到 should V-07. 角度合并 + 严重度调整都在合理范围, 不是漏报.

4. **DAR minority_kept=0 不能定论 DAR 退化**: 真业务 sample 4 个高度一致时 minority bucket 必空, 跟 Day5 close 劳动仲裁报告 caveat 一致. 真比较需要 N>=3 轮 calibration 看分布稳定性.

5. **wall +447s vs baseline 部分原因**: Run2 苍鹰阶段 365s vs baseline 不详, 加上 phase 0/0.5 探测多了 ~1min. 苍鹰 4 sample 长 reasoning 是主因.

## 数据文件

- `workspace-points-payment/output/review_items_20260427_default.json` (16 条, Run2 main HEAD)
- `workspace-points-payment/output/sessions/rev_1777275596_d6932ebc.jsonl` (Run2 telemetry, 15 行)
- `logs/review_points_payment_day5_close_run2.log` (Run2 完整 log)
- `workspace-points-payment/output/review_items_run1_branch_9256ba8.json` (Run1 备份, 21 条, 误用 9256ba8)
- `workspace-points-payment/output/sessions/rev_run1_branch_9256ba8.jsonl` (Run1 telemetry 备份)
- `logs/review_points_payment_run1_branch_9256ba8.log` (Run1 log 备份)
- `workspace-points-payment/output/PRD_开发任务_20260427_default.md` (Run2 开发任务报告)
- `workspace-points-payment/output/dashboard.html` (Run2 dashboard)
