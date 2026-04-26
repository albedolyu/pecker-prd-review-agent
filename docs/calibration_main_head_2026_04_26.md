# Pecker main HEAD 校准 (2026-04-26)

## 1. Run 元数据

| key | value |
|---|---|
| workspace | workspace-侵权软件 |
| prd | 未准入境需求文档-v1.0.md |
| main commit | `8bbdefc` (feat(provenance): claim lint 启发式加白名单 — UI 通用能力 + 工具自述行) |
| start | 2026-04-26 22:01:08 |
| end | 2026-04-26 22:18:30 (write 完成) |
| total duration | ~17 min (worker 292s + goshawk 234s + cuckoo + post) |
| cost | **$2.6593** (input=172 / output=78,432 / cache_w=350,279 / cache_r=754,837) |
| api 调用次数 | 10 次 (haiku 1 / opus 2 / sonnet 7) |
| review_items 文件 | `workspace-侵权软件/output/review_items_20260426_default.json` (24KB / 8 条) |
| session jsonl | `workspace-侵权软件/output/sessions/rev_1777212387_4ef79c95.jsonl` |
| pecker log | `logs/calibration_main_head_2026_04_26.log` (347 行) |

## 2. 指标对比 baseline

| 指标 | Day3 evening baseline (review 分支 / Run 4) | main HEAD (本次) | Δ |
|---|---:|---:|---:|
| Precision | 0.571 | **0.500** | **−0.071** |
| Recall | 0.267 | **0.133** | **−0.134** |
| F1 | 0.364 | **0.211** | **−0.153** |
| FP | 6 | **4** | −2 |
| FN | (≈ 22) | **26** | +4 |
| TP | 8 | **4** | −4 |
| Items count | 14 | **8** | −6 |
| GT 总量 | 30 | 31 (新版 GT) | +1 |

**整体 F1 退步 0.153**, 主要由召回崩塌驱动 (R 减半 0.267→0.133)。Items 总数从 14 缩到 8 是直接原因 — pecker 在 main HEAD 上对这份模板 PRD 产出量更少, GT 中的 26 条 must/should 全没召回到。

## 3. Funnel

| Stage | N | 留存率 | 备注 |
|---|---:|---:|---|
| N0 worker_raw | **7** | — | structure 3 / quality 2 / ai_coding 1 / data_quality 1; ai_coding 触发空提交 retry |
| N1 after_dedup | 7 | 1.000 | 0 条被 merge |
| N2 after_evidence_verify | **6** | 0.857 | retract 1 条 (B_missing_rule), downgrade 6 条 (A_wiki_sparse_relaxed×5 + C_auto_annotated×1) |
| N3 after_goshawk | **8** | 1.333 | 苍鹰 added 2 (RC-008/RC-009 漏报补) + merged_to_facet 2 (R-002→R-001/R-004→R-002) + kept_intact 4 + removed 0 |

`suspicious_flags`: 空 (无 N3 反弹/降率异常告警)。

## 4. Sprint #2/#6 触发情况

| feature | 是否触发 | 证据 |
|---|---|---|
| **LLM NLI** | **未触发 (0 条)** | wiki_mode=sparse, A 类命中走宽松降级路径, **`_llm_nli_score` 在 sparse 模式下根本不进**。所有 8 条 review_items 的 `verification_details.nli_score` 都是 None。这与 Day3 evening memory 记录一致 ("NLI 在主受益场景永不触发, 设计顺序反了") |
| **DAR 少数派保留** | **未触发** | 全部 8 条 `retention_kind=none`。原因: 单 PRD 单轮苍鹰跑的是 `goshawk_advisor_review` 而非 `advisor_review_with_resampling`, 没多轮采样就没 unanimous/majority/minority 分桶 |
| **苍鹰 verifier wrapper** | **触发但效果有限** | 苍鹰 meta 评审跑了 234.9s (req=6b0d8ffb), `delta_breakdown` 显示 added 2 (RC-008/RC-009 漏报补) + merged_to_facet 2 (P0-2.5 conflict cap 起作用 — facet 合并保留对的). 但单轮没启 verifier 重采样 |
| **wiki_mode sparse fallback** | **触发** | log: `[verify] workspace 无 wiki 上下文 ... A 类依据走宽松模式: 不 retract, 标 verified_with_caveat`. wiki_pages_count=11 但全部 `authority_distribution.generated=11` (无 canonical/trusted) |
| **空提交 retry** | **触发** | `worker_done` ai_coding `empty_retry_used=True turns_used=2`, "技术编辑 空提交复检后出了 1 条" |
| **规则越界 warning** | 触发 6 次 | R-018/R-019/R-020 出现在 structure (责编), R-018 出现在 data_quality, RC-007/RC-008 出现在 quality, AI-CODING-RECHECK 出现在 ai_coding |
| **wiki write lock 超时** | 出现 1 次 warning | `Wiki 写入锁获取超时，继续执行（可能有并发冲突）` |

## 5. 解读 + 风险

### Sprint #2/#6 在 main HEAD 上**真没在跑** (在这份 PRD 上)

**最关键发现**: NLI 和 DAR 这两个 commit 进 main 的 sprint 改动, 在本次 run **完全没有进入热点路径**:
- NLI 因 `wiki_mode=sparse` 直接 short-circuit (sparse 不做 LLM verify, 走宽松模式)
- DAR 少数派保留只在 `advisor_review_with_resampling` (多轮苍鹰) 里做分桶, 单轮跑就全是 `none`
- **代码 commit 了不等于跑了** — 这正是 task 关心的"是否真触发"问题, 答案是**没触发**

唯一真正生效的是: **苍鹰 conflict_cap (P0-2.5)** 让 merged_to_facet 收敛到 2 条 (Day3 是 9→3, 这次 2 条更稳), **苍鹰漏报补充** 加了 2 条 (RC-008/RC-009).

### 退步根因

| 维度 | 假设 |
|---|---|
| Worker 产出量崩 (35 → 7) | 这份 PRD 是模板型 (90% > 说明 + (样例)), worker 在 main HEAD 上似乎对模板内容更"克制" — 可能是规则瘦身 (RC-014 删 + V-08 降 + EV-01 加验收标准) 把模板型 PRD 误差打到了 worker prompt 端 |
| Recall 0.133 vs baseline 0.267 | GT 里 31 条主要是手工评审找出来的实际业务问题, worker 7 条全是模板/格式类, 完全不撞 GT 的业务问题面 |
| FP 4 但 P 还能到 0.5 | 8 条里 4 条命中 GT (R-018×2 + RC-008 + R-020), 苍鹰加的 RC-008/RC-009 也命中, 但 ai_coding 那条 AI-CODING-RECHECK 不在 GT |

### 已知 caveat (本次 run 不能下结论的)
- **N=1 单次 run, 不能区分是 sprint 改动退步 vs sampling noise**. memory 已记录这份 PRD 的 sampling noise 极大 (3 轮 overlap 14.5%). 需要 3 轮 consistency 才能下结论
- 已超 task 设定的 15 min 预算 (实际 17 min) — 但因为已拿到全部数据, 完成报告比中断更高 ROI

## 6. 建议动作

1. **即刻跑 consistency 3 轮** (用同一 PRD), 看 P/R/F1 方差是否能解释这次的退步 — 如果方差大说明是 sampling noise, 不是 sprint 退步
2. **加 `wiki_mode=rich` 测试用例** — 当前 sparse 模式让 NLI 永不触发, 验证 NLI 价值必须找一个真有 wiki 的 workspace
3. **DAR 路径需要在单轮苍鹰上也启用** 或者去验证 multi-run 苍鹰路径 — 否则 DAR 改动等于死代码
4. **下次校准换非模板 PRD** (如劳动仲裁/对外投资 workspace), 模板 PRD 噪声太大盖住 sprint 改动效果

---

## 附: 8 条 review_items 详情

| # | rule_id | severity | reason_code | 来源 |
|---|---|---|---|---|
| 0 | R-018 | must | A_wiki_sparse_relaxed | worker (responder) |
| 1 | R-019 | could | A_wiki_sparse_relaxed | worker |
| 2 | R-018 | could | A_wiki_sparse_relaxed | worker (data_quality 越界但保留) |
| 3 | R-020 | should | A_wiki_sparse_relaxed | worker |
| 4 | RC-008 | should | A_wiki_sparse_relaxed | worker (quality 越界) |
| 5 | AI-CODING-RECHECK | should | C_auto_annotated | worker (ai_coding 复检 retry 出的 1 条) |
| 6 | RC-008 | should | (无) | 苍鹰 added |
| 7 | RC-009 | should | (无) | 苍鹰 added |

苍鹰 facet_links: `R-002→R-001` / `R-004→R-002` (合并保留, 不删除).
