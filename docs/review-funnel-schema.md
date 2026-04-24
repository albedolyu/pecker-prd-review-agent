# Review Funnel Schema v1

> **问题**: 最终报告只显示"10 条 items",看不到"worker 原始 28 条 → dedup 剩 15 → evidence verify 剩 11 → goshawk 合并剩 8(+2) → PM 接受 6",哪层吞掉的无从诊断
>
> **目标**: 每次 review run 的 5 层漏斗全部可观测,回答
> - worker 原始够不够?
> - 去重吞 facet 没?
> - Evidence verify 误杀率?
> - 苍鹰合并过狠?
> - PM 最后接受了哪类?

**立项日期**: 2026-04-24
**承接**: 现有 `workspace-*/output/sessions/rev_*.jsonl` 事件流,补 5 层 stage event
**Sprint 关联**: [sprint-real-prd-calibration-evidence-governance.md](sprint-real-prd-calibration-evidence-governance.md) 主线 D

---

## 一、5 层漏斗定义

```
┌─────────────────────────────────────────┐
│ N0: worker_raw_items                    │  4 worker 提交的原始条数总和
│                                          │  (含 submit_review_items 工具调用)
└─────────┬───────────────────────────────┘
          │ dedup_dropped = N0 - N1
          │  (merge_reviews 合并相似项)
          ▼
┌─────────────────────────────────────────┐
│ N1: after_dedup_items                   │  去重后进下游
└─────────┬───────────────────────────────┘
          │ evidence_verify_dropped = N1 - N2
          │  (wiki/rule 找不到 + A类降权 + retract)
          ▼
┌─────────────────────────────────────────┐
│ N2: after_evidence_verify_items         │  证据验证通过的
└─────────┬───────────────────────────────┘
          │ goshawk_removed   (REMOVED_BY_ADVISOR)
          │ goshawk_merged_to_facet (P0-1 后保留为 could)
          │ goshawk_added     (苍鹰补遗 R-xxx)
          ▼
┌─────────────────────────────────────────┐
│ N3: after_goshawk_items                 │  含 facet,不含 REMOVED
└─────────┬───────────────────────────────┘
          │ pm_rejected_by_reason[7 种]
          │ pm_edited
          │ pm_accepted
          ▼
┌─────────────────────────────────────────┐
│ N4: after_pm_decision                   │  accept + edit (真落地的)
└─────────────────────────────────────────┘
```

**每层必须能回答的 3 个问题**:
| 层 | 量(count) | 质(由谁/为何/分布) | 与上一层的 delta 原因 |
|---|---|---|---|
| N0 | worker 每个维度提交数 | by_dimension | — |
| N1 | 去重后 | merge 策略统计 | `dedup_dropped_ids` + `merge_reason` |
| N2 | 通过证据验证 | 撤回原因分布 | `retracted_by_reason` + `downgraded_by_reason` |
| N3 | 苍鹰后 | added/removed/merged_facet/kept | 对应 ID lists |
| N4 | PM 接受 | by_reject_reason + by_severity | 对应 ID + reason_category (见 pm-reject-reason spec) |

---

## 二、JSONL event schema

现有 event types (api/routes/review.py 已 emit):
- `review_started` (L300)
- `workers_started` (workers 开始)
- `worker_done` (L349)
- `checkpoint` (L373)
- `final_reviewer_started` (L404)
- `final_reviewer_done` (L421)
- `review_completed` (L490)

**新增 6 个 stage event** (插入到现有序列里):

### 2.1 `funnel_stage_worker_raw`

**emit 位置**: workers 全部 done 之后,merge_reviews 之前 (api/routes/review.py 约 L355-370 区间)

```json
{
  "ts": "2026-04-24T16:22:11Z",
  "type": "funnel_stage_worker_raw",
  "count": 28,
  "by_dimension": {
    "structure": 8,
    "quality": 7,
    "ai_coding": 6,
    "data_quality": 7
  },
  "empty_retry_dimensions": ["ai_coding"],    // 触发空提交重试的 worker
  "raw_item_ids": ["R-001", "R-002", ...]    // 可选,长则截断
}
```

### 2.2 `funnel_stage_after_dedup`

**emit 位置**: merge_reviews 之后 (L370 附近)

```json
{
  "ts": "...",
  "type": "funnel_stage_after_dedup",
  "count": 15,
  "dropped_count": 13,
  "merge_groups": [
    {"primary": "R-001", "merged": ["R-005", "R-009"], "reason": "location+rule_id 相同"}
  ]
}
```

### 2.3 `funnel_stage_after_evidence_verify`

**emit 位置** (注意 flow 不对称):
- **CLI** (`run_session.py:276`) 有 full `verify_evidence` → 在此后 emit
- **API** (`api/routes/review.py`) **不跑 full verify_evidence**,evidence 验证由 goshawk 内 `_verify_wiki_evidence` 侧查代替 → API 流跳过此 stage,直接从 `after_dedup` 接到 `after_goshawk`
- 飞书 (`feishu_bot.py:184`) 跑 verify_evidence,按 CLI 方式处理

**第一期落地**: CLI flow 先打通 full 5 层,API flow 4 层即可 (合规原因见 sprint T3 第二版修订说明)

```json
{
  "ts": "...",
  "type": "funnel_stage_after_evidence_verify",
  "count": 11,
  "retracted_count": 2,
  "downgraded_count": 3,
  "retracted_by_reason": {
    "A_wiki_page_not_found": 1,
    "B_rule_id_missing": 1
  },
  "downgraded_by_reason": {
    "A_wiki_page_not_found_weak": 3   // 2026-04-24 rich 模式降权而非 retract
  },
  "wiki_mode": "rich" | "sparse",
  "authority_distribution_in_wiki": {"canonical": 0, "trusted": 2, "contextual": 5, "generated": 11}
}
```

### 2.4 `funnel_stage_after_goshawk`

**emit 位置**: apply_advisor_result 返回后 (api/routes/review.py 约 L412,`items = apply_advisor_result(...)` 之后)

```json
{
  "ts": "...",
  "type": "funnel_stage_after_goshawk",
  "count": 10,
  "delta_breakdown": {
    "removed": 0,                              // REMOVED_BY_ADVISOR
    "merged_to_facet": 3,                      // P0-1 后作 could facet
    "added": 2,                                // 苍鹰补遗 (additional_findings)
    "false_positive_restored": 0,              // Haiku sanity check 复活
    "kept_intact": 5                           // 没被苍鹰动的
  },
  "facet_links": [
    {"facet": "R-003", "primary": "R-001"},
    {"facet": "R-004", "primary": "R-001"},
    {"facet": "R-007", "primary": "R-005"}
  ]
}
```

### 2.5 `funnel_stage_after_pm_decision`

**emit 位置**: `confirm_review` 里,`accepted/rejected/edited` 聚合之后 (api/routes/review.py L696 附近)

```json
{
  "ts": "...",
  "type": "funnel_stage_after_pm_decision",
  "total_items": 10,
  "accepted": 5,
  "edited": 1,
  "rejected": 4,
  "pending": 0,
  "rejected_by_reason": {
    "false_positive": 1,
    "wiki_missing": 2,
    "rule_too_strict": 1
  },
  "accepted_severity_distribution": {"must": 3, "should": 2, "could": 0}
}
```

### 2.6 `funnel_summary`

**emit 位置**: `review_completed` event 之前/之后 (L490)

```json
{
  "ts": "...",
  "type": "funnel_summary",
  "stages": {
    "N0_worker_raw": 28,
    "N1_after_dedup": 15,
    "N2_after_evidence_verify": 11,
    "N3_after_goshawk": 10,
    "N4_after_pm_decision": 6
  },
  "stage_retention": {
    "dedup_retention": 0.54,
    "evidence_verify_retention": 0.73,
    "goshawk_retention": 0.91,
    "pm_retention": 0.60
  },
  "suspicious_flags": [
    "dedup_retention_low_0.54"  // 低于 0.7 提示可能吞 facet
  ]
}
```

**可疑信号阈值**:
| 信号 | 阈值 | 含义 |
|---|---|---|
| `dedup_retention < 0.6` | 吞 facet 嫌疑 | merge 太激进 |
| `evidence_verify_retention < 0.6` | 证据验证误杀 | sparse mode 未触发 / authority 全 generated |
| `goshawk_retention < 0.7` 且 `merged_to_facet=0` | 苍鹰过滤太狠 | 老版 merge_to_advisor 过滤 (应 P0-1 后不会) |
| `pm_retention < 0.3` | PM 大面积驳回 | 看 reject_by_reason 细分 |

---

## 三、聚合脚本 (`scripts/funnel_report.py`)

**输入**: 最近 N 个 session jsonl (from `workspace-*/output/sessions/rev_*.jsonl`)

**输出**: markdown 表 + 异常标注

```bash
python scripts/funnel_report.py --last 10 --workspace workspace-侵权软件
```

**样式**:
```markdown
# Pecker 评审漏斗 · workspace-侵权软件 · 最近 10 次

| run | PRD | N0 worker | N1 dedup | N2 ev_verify | N3 goshawk | N4 PM | 异常 |
|---|---|---|---|---|---|---|---|
| 16:18 | 未准入境-v1.0 | 28 | 15 | 11 | 10 | 6* | pm_retention_low |
| 15:42 | 未准入境-v1.0 | 29 | 17 | 12 | 10 | — | pending |
| 14:43 | 侵权软件原版 | 31 | 18 | 14 | 12 | 8  | ok |
...

## 趋势观察

- dedup_retention 稳定在 0.52-0.58 之间,**建议排查 merge_reviews 是否吞 facet**
- evidence_verify_retention 从 0.56 (修前) → 0.73 (e3ea5c3 降权模式),显著改善
- goshawk_retention 从 0.55 (修前) → 0.91 (P0-1 facet 保留),符合预期
- pm_retention 最近 3 次 0.3-0.6,主因 reject_reason 分布:
  * rule_too_strict 45%  → 建议 review RC-009 / RC-011
  * wiki_missing 30%     → 建议补 canonical wiki
  * false_positive 15%
  * model_noise 10%
```

---

## 四、实现步骤

### Phase 1 — Emit 点 (1 天)

改动文件 + 位置:
1. `api/routes/review.py` L300-490 区间,追加 6 个 `evt.append(stage_name, data)` 调用
2. `review/evidence_verify.py` 返回结构加 `retracted_by_reason` / `downgraded_by_reason` / `wiki_mode` 字段 — 或 api/routes/review.py 从 evidence_verify 返回值提取
3. `goshawk_advisor.py` `apply_advisor_result` 在返回前附加 `_funnel_telemetry` dict,提供 delta_breakdown + facet_links

**每处 emit 失败不阻塞评审流程** — try/except + log.warning

### Phase 2 — 聚合脚本 (0.5 天)

- `scripts/funnel_report.py` 读 jsonl,按上述 table 格式输出
- 支持 `--last N` / `--workspace X` / `--reviewer Y`
- 异常阈值写死在脚本常量,后续可移 config

### Phase 3 — 单测 (0.3 天)

- 构造假的 jsonl,断言 funnel_report.py 的聚合正确
- 断言 emit 失败不中断 review flow (mock emit 抛异常)

### Phase 4 — (后做) Dashboard tab (不在本 sprint 阻塞)

- `web/` 前端加 "漏斗视图" tab,读 `/api/dashboard/funnel?workspace=X&last=N`
- 后端 `api/routes/dashboard.py` 加路由调用 funnel_report 逻辑 (复用脚本主函数)

---

## 五、向后兼容

- 现有 jsonl event types 全部保留不变
- 新增 event types 以 `funnel_stage_*` / `funnel_summary` 前缀,不与现有冲突
- 聚合脚本容忍缺失新 event — 老 session 漏斗图只显示 N0/N4 两端,中间层显示 `—`
- 旧 eval 脚本 (cuckoo_eval / consistency_eval) 不受影响

---

## 六、Open questions

1. **stage event 加到 SSE `emitter.emit` 还是只 jsonl?** 前端实时展示漏斗进度 vs 只做事后分析
   - 暂只写 jsonl,SSE 改动影响 streaming 测试面较大,放 Phase 4 dashboard
2. **raw_item_ids 长度上限?** 模板 PRD 可能 worker 吐 50+ 条,全列会让 jsonl 膨胀
   - 定上限 30,超过截断 + `truncated: true` 标志
3. **funnel_summary 的异常阈值**: 硬编码还是 per-workspace 配置?
   - 硬编码 v1,收集 1 个月数据后看是否需要 per-workspace 标定

---

## 七、首批落地 checklist

- [ ] `api/routes/review.py` 追加 6 个 emit (L300-490 区间)
- [ ] `review/evidence_verify.py` 返回值加 telemetry 字段
- [ ] `goshawk_advisor.py` apply_advisor_result 返回值加 `_funnel_telemetry`
- [ ] `scripts/funnel_report.py` 聚合脚本
- [ ] 单测: 构造假 jsonl 断言聚合 / emit 失败不阻塞
- [ ] 跑一次真 pecker run,验证 6 个新 event 都落到 jsonl
- [ ] 跑 `funnel_report.py --last 10` 产首张漏斗表,贴到 PR

---

**一句话**: 评审不再是黑箱,每层通过率 + 异常信号 + 驱动下游的哪种修法都可观测。
