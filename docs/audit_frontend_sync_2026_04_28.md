# Pecker 前端看板 sync 审计 (2026-04-28)

> 审计者: Reality Checker (默认 NEEDS WORK), 只读
> 范围: dashboard.py + web/ Next.js (Phase2RunningV8 / Phase3ConfirmV8 / Phase4ReportV8)
> 后端基线: main HEAD 3bc9e80 (Day5 8 commit, 含 schema_registry SoT / anti-corruption / P0-A canonical wiki / NLI 4/4 / DAR retention_kind)

---

## TL;DR

- **OK**: 0 处
- **NEEDS WORK**: 6 处
- **REJECT**: 2 处 (web 关键 sync 缺失, 严重)

**整体诊断**: 后端 Day5 改了大量结构 (schema_registry SoT / anti-corruption / 5 stage funnel / NLI / DAR retention 分布), **2 个看板 0 处对接** Day5 任何新字段. dashboard.py 仍读 raw `rule_performance_history.json` 含 zombie + 缺新规则; web/ SSE 流定义 8 个事件类型, 0 个 funnel/anti-corruption/NLI/authority. 看板与后端进入"两张皮"状态.

---

## dashboard.py (5 项)

### 1. rule_id zombie / 缺新规则 — REJECT

**证据**:
- `dashboard.py:67-68` `_load_rule_history`: 直接读 `rule_performance_history.json` 现 17 个 key → 用 `for rule_id, entry in data.items()` 落到 `rules` list (line 83-95).
- `dashboard.py:106-107` `rules.sort(...)` 取 top 10 直接展示 → `rule_labels = json.dumps([r["id"] for r in rule_data["top_rules"]])` (line 227)
- 实测 `workspace-sample/output/rule_performance_history.json` 17 keys 含 **`RC-014`** (line 7 输出验证), 但 `review-dimensions.yaml:223` 已 commit 注释 "2026-04-26 sprint Day3: 删 RC-014 (与 RC-008 内容重复)"
- yaml 现含 `EV-01/EV-04/FN-01/FN-03/FN-09` 5 条新规则 (`review-dimensions.yaml:115/120/268/343/348`), **history.json 全 0 出现**, dashboard 永远展示不出来
- `review/schema_registry.py:270` 提供 `all_rule_ids() -> frozenset`, `dashboard.py` **0 处 import** (`grep -n "schema_registry" dashboard.py` 空)

**verdict**: REJECT — 双向 sync 失败. 既展示 zombie (RC-014 在 yaml 已 deprecated) 又遗漏 5 条 active/experimental 新规则 (FN-01/03/09 + EV-01/04). 这就是"代码 SoT 已收敛, 看板还在读老数据库"的典型反模式.

**修法草案**:
1. `dashboard.py` 加 `from review.schema_registry import SchemaRegistry`
2. `_load_rule_history` 加白名单过滤: `reg = SchemaRegistry.get(workspace); known = reg.all_rule_ids(); rules = [r for r in rules if r["id"] in known]`
3. 加"新规则未触发"提示: `for rid in known - {r["id"] for r in rules}: rules.append({"id": rid, "total": 0, ...})` 让 PM 看到 EV-/FN- 缺数据
4. status 字段透传 (experimental 加角标)

---

### 2. NLI 触发率展示 — REJECT

**证据**:
- `dashboard.py` 全文 `grep -i "nli\|n_samples_succeeded"` **0 命中**
- 后端 `review/evidence_verify.py:454` 写出 `n_samples_succeeded` 字段, `:765-766` `v_details["nli_score"] = nli`
- Day5 sprint #6 NLI 历史首次 4/4 触发 (Sonnet+lineage prompt 路径), 没有任何看板能看到这成果
- `_load_rule_history` 只读 rule-level 数据, NLI 字段在 `review_items[].verification_details` 层, 当前 dashboard 完全不读 review_items

**verdict**: REJECT — Day5 关键里程碑 (NLI 4/4 触发) 在 dashboard 不可见, PM 无法验证 sprint #6 的成果是否生效.

**修法草案**: `_load_session_stats` 升级为 `_load_review_items_stats`, 扫描 jsonl 的 `evidence_verify_done` event payload + final result items 汇总 `nli_score 分布 / n_samples_succeeded 命中率`. 加图: "NLI 触发率 % 趋势 (4/4 / 3/4 / sparse 跳过)".

---

### 3. anti-corruption dropped 展示 — NEEDS WORK

**证据**:
- `dashboard.py` 全文 0 处 import / 读 `dropped_unknown_rule_count` 或 `dropped_unknown_rule_ids_by_dim`
- 后端 `review/funnel_telemetry.py:32-39` 已聚合到 `compute_worker_raw_stage` 输出, `:46-51` 从 worker telemetry 读 `tele.get("dropped_unknown_rule_count", 0)`
- `api/routes/review.py:382` `evt.append("funnel_stage_worker_raw", _worker_raw)` 写 jsonl, 数据**已落盘**但 dashboard 不读

**verdict**: NEEDS WORK — 数据已写, 看板未连. 后端把 worker 幻觉 ID drop 数 + 命中维度都聚合好了, dashboard 该加一张"幻觉 rule_id 分布"卡片让 PM 监控 anti-corruption 拦截效果.

**修法草案**: `_load_session_stats` 扫 jsonl 中 event=`funnel_stage_worker_raw` payload, 累加 `dropped_unknown_rule_count` + `dropped_unknown_rule_ids_by_dim`, 加新图"幻觉 rule_id drop 分布 (按维度)".

---

### 4. authority_distribution 展示 — NEEDS WORK

**证据**:
- `dashboard.py` 0 处 import / 读 `authority_distribution` / `wiki_mode`
- `review/funnel_telemetry.py:78` `compute_evidence_verify_stage` 输出 `"authority_distribution": wiki_telemetry.get("authority_distribution", {})`
- `:213-234` `get_wiki_telemetry()` 用 `_wiki_authority_tier()` 算 canonical / contextual 比例
- `api/routes/review.py:416` `evt.append("funnel_stage_after_evidence_verify", _after_ev)` 写出
- Day5 P0-A 接通的 canonical wiki 路径效果, 看板无法验证

**verdict**: NEEDS WORK — P0-A 修法 ROI 看不见. PM 不能从 dashboard 看出"接通外挂 canonical wiki 后, canonical / contextual 比例从 0/74 变成多少". 这是 P0-A 修法核心 KPI.

**修法草案**: 新增"wiki 权威性分布"环图, x 轴时间, 数据从 jsonl 扫 `funnel_stage_after_evidence_verify.authority_distribution`. 同时展示当前 wiki_mode (sparse/rich).

---

### 5. DAR retention_kind_dist 展示 — NEEDS WORK

**证据**:
- `dashboard.py` 0 处 import / 读 `retention_kind_dist` / `minority_kept`
- `goshawk_advisor.py:736-738` 设计示例: `{"unanimous": 2, "majority": 1, "minority": 1, "minority_kept": 1}`
- `goshawk_advisor.py:755-757` 实写 telemetry: `"retention_kind_dist": dict(dist), "minority_kept": dist.get("minority", 0)`
- 这数据在 `goshawk_summary` 字段或 worker telemetry 内, `_load_rule_history` 只读 rule-level history.json 永远拿不到
- DAR 设计意图是 PM 能看少数派保留分布 — 当前 dashboard 0 处接通

**verdict**: NEEDS WORK — DAR 少数派保留逻辑成果不可见, PM 无法判断"是不是被苍鹰一次性多数表决吃掉漏报".

**修法草案**: 加"苍鹰 DAR 保留分布"堆叠柱图 (unanimous / majority / minority / minority_kept), 数据扫 jsonl 中 `final_reviewer_done` event 的 `goshawk_summary.retention_kind_dist`.

---

## web/ Next.js (3 项)

### 6. Phase4Report cross_boundary 字段展示 — NEEDS WORK

**证据**:
- `web/components/phases/Phase4ReportV8.tsx` 全文 `grep "cross_boundary\|dropped_unknown"` **0 命中**
- `web/lib/api.ts:179-201` `ReviewItem` interface **未声明** `cross_boundary` 字段, 即使后端发了 ts 也不会展示 (用 `[key: string]: unknown` 兜底但 UI 不读)
- `Phase4ReportV8.tsx:613-660` `DimGroup` items 渲染只展示 `it.problem / it.suggestion / it.location / it.confidence`
- Day5 P1 anti-corruption drop 后, web 拿到的 items 已不含幻觉 ID, 但**合法跨维度 ID** (cross_boundary=true) 仍在 — 用户看不到这个标识
- `api/routes/review.py:736` 后端 `_save_eval_ground_truth` 含 `"reason_category": decision.get("reason_category", "")` 写出 — 但**前端反向**没有发送

**verdict**: NEEDS WORK — Phase4 报告无法区分"合法跨章节告警"(应该保留, 设计意图) vs "维度边界外告警"(应该拒绝, 噪声). PM 收到的报告少了关键决策维度.

**修法草案**: `web/lib/api.ts` 加 `cross_boundary?: boolean`, Phase4 `DimGroup` 加 chip 展示. 同时 stat row 加"cross_boundary 比例".

---

### 7. Phase2Running funnel 5 stage 展示 — REJECT

**证据**:
- `web/lib/useReviewStream.ts:42-124` 定义 8 个 event 类型 (Uploaded / WikiScanned / WorkersStarted / WorkerDone / FinalReviewerStarted / FinalReviewerDone / Result / Error / ReviewFailed / ReviewDegraded), **0 个 funnel_stage_*** 或 `funnel_summary`
- `Phase2RunningV8.tsx:651-779` `buildConsoleLines` switch 只分发 8 个 case + 2 个 review_failed/degraded, **funnel events 进不来**
- 后端 `api/routes/review.py:382/386/416/477/563/823` 6 处 `evt.append("funnel_stage_*"|"funnel_summary", ...)` — **全是 `evt.append`** 写 jsonl, **不是 `emitter.emit`** SSE 流
- `api/stream.py:30-39` `MILESTONES` dict 只列了 8 个 milestone, 不含任何 funnel stage
- 因此即使后端写了 funnel telemetry, **SSE 流根本没推过来**, 前端就算想接也没数据

**双重失败**:
1. 前端类型系统不认 funnel_stage 事件 (即使推过来也被 ts cast 失败丢弃)
2. 后端 funnel_stage 走 evt.append 不走 SSE, 推都没推

**verdict**: REJECT — Phase2 不能展示任何 5 stage funnel. **架构断裂**: 后端 funnel_telemetry 设计完整, 但 SSE 通道与 jsonl 通道分离, 前端永远拿不到 funnel 实时数据. PM 看不到"worker_raw 28 → dedup 21 → ev_verify 18 → goshawk 14 → PM (待决)".

**修法草案** (P0):
1. `api/stream.py:30-39` `MILESTONES` 加 `funnel_stage_worker_raw / funnel_stage_after_dedup / funnel_stage_after_evidence_verify / funnel_stage_after_goshawk / funnel_summary` 5 项
2. `api/routes/review.py:382/386/416/477/563` 6 处 `evt.append(...)` 改双轨 — 同时 `emitter.emit(event, data=stage)` 推 SSE
3. `web/lib/useReviewStream.ts` 加 5 个 FunnelStage event interface
4. `Phase2RunningV8.tsx` 加 5 step 漏斗组件 (worker_raw → dedup → ev_verify → goshawk → PM)

---

### 8. Phase3Confirm reject_reason 7 类下拉 — REJECT

**证据**:
- `web/components/phases/Phase3ConfirmV8.tsx:366-371` reject 仅传 `reason: v` 自由文本, **完全无 reason_category 字段**:
  ```ts
  onRejectReasonChange={(v) =>
    setDecision(item.id, {
      action: "reject",
      reason: v,    // <-- 只有自由文本, 没有 7 类下拉
    })
  }
  ```
- `web/lib/api.ts:273-277` `ItemDecision` interface 仅含 `action / reason? / edited_problem?`, **未声明 `reason_category` 字段**
- `Phase3ConfirmV8.tsx:716-722` reject textarea 是单行 placeholder="驳回原因(可选)" + textarea, 0 个下拉/radio
- 后端 `api/models.py:162-165` `_VALID_REJECT_REASONS = frozenset({"good_issue", "false_positive", "known_tradeoff", "wiki_missing", "rule_too_strict", "impl_detail", "model_noise"})` 7 类硬枚举校验
- `api/models.py:160` 注释: "当前 web/ 0 处使用此字段(前端尚未接 reason dropdown), 严校 zero risk" — 后端已自我承认前端没接
- 影响: `api/routes/review.py:638` 走默认 `reason_category = decision.get("reason_category", "model_noise")`, **所有 reject 都被归类成 "model_noise"** → rule_perf EMA 反馈失真 → feedback loop 失效

**verdict**: REJECT — 设计意图与实现彻底脱节. Day3 设计的 7 类区分本意是 "false_positive 比 wiki_missing 对 rule_perf 衰减权重不同", 现在前端不发就全归 model_noise, **整个 EMA 反馈闭环吃错信号**.

**修法草案** (P0):
1. `web/lib/api.ts` `ItemDecision` 加 `reason_category?: "good_issue" | "false_positive" | "known_tradeoff" | "wiki_missing" | "rule_too_strict" | "impl_detail" | "model_noise"`
2. `Phase3ConfirmV8.tsx` reject 区域 textarea 上方加 7 类 radio/select (优先 select, 节省垂直空间)
3. UX: PM 选 false_positive 自动标注 "建议升 noisy" 提示 (与 rule_lifecycle.py 联动)
4. accept 默认 reason_category="good_issue", reject 默认必选

---

## 修法优先级

### P0 (上线前必做, ~4-5 day)

| # | 项 | 工时估算 | 严重性 |
|---|----|---------|------|
| 7 | Phase2 funnel 5 stage 通道打通 (前后端 + SSE 双轨) | 1.5 day | REJECT, 架构断裂 |
| 8 | Phase3 reject_reason 7 类下拉 (闭环 EMA) | 1.0 day | REJECT, 反馈失真 |
| 1 | dashboard rule_id 接 schema_registry SoT | 0.5 day | REJECT, 数据脏 |

**P0 总工时**: ~3.0 day (含联调 0.5 day)

### P1 (一周内, ~2-3 day)

| # | 项 | 工时 |
|---|----|-----|
| 6 | Phase4 cross_boundary 字段透传展示 | 0.5 day |
| 3 | dashboard anti-corruption drop 监控图 | 0.5 day |
| 4 | dashboard wiki authority_distribution 图 | 0.5 day |
| 5 | dashboard DAR retention_kind 分布图 | 0.5 day |

**P1 总工时**: ~2.0 day

### P2 (长尾, 视情况)

| # | 项 | 工时 |
|---|----|-----|
| 2 | dashboard NLI 触发率展示 (要先扩 jsonl scan 到 review_items 层) | 1.0 day |

---

## 最严重 3 个不同步点

### 严重 1: SSE 通道根本没推 funnel 数据 (架构断裂)
- `api/routes/review.py:382/386/416/477/563/823` 6 处 funnel telemetry 全走 `evt.append(...)` jsonl, **0 处** `emitter.emit(...)` SSE
- `api/stream.py:30-39` `MILESTONES` 不含 funnel_*
- `web/lib/useReviewStream.ts:42-124` 8 个 event interface 0 个 funnel_*
- 影响: 后端再完善 funnel/NLI/anti-corruption telemetry, 前端永远看不见

### 严重 2: Phase3 reject 不发 reason_category (闭环失真)
- `web/components/phases/Phase3ConfirmV8.tsx:366-371` 只 `setDecision(item.id, {action: "reject", reason: v})`, 无 `reason_category`
- `api/models.py:160` 后端注释自己承认 "当前 web/ 0 处使用此字段"
- `api/routes/review.py:638` 全部 fallback "model_noise"
- 影响: 7 类 EMA 区分逻辑全失效, rule_lifecycle 衰减信号噪声 100%

### 严重 3: dashboard rule_id 直读 history.json 跳过 schema_registry
- `dashboard.py:67-68` 直接 `json.load(rule_performance_history.json)` 取 17 keys
- 实测含 zombie `RC-014` (yaml 已删 `:223`); 缺 `EV-01/EV-04/FN-01/FN-03/FN-09` 5 条 active/experimental
- `dashboard.py` 0 处 import `schema_registry`
- 影响: PM 看到的"已跟踪规则数 17"含 zombie + 缺新规则, 决策失误

---

## 不能下结论的项

无. 8 项均给出 file:line 证据 + verdict.

---

## 附: 看板与 Day5 后端的同步矩阵

| Day5 后端字段 | dashboard.py | web/Phase2 | web/Phase3 | web/Phase4 |
|--------------|--------------|------------|------------|------------|
| `schema_registry.all_rule_ids()` | ❌ | n/a | n/a | n/a |
| `dropped_unknown_rule_count` | ❌ | ❌ (SSE 没推) | n/a | ❌ |
| `dropped_unknown_rule_ids_by_dim` | ❌ | ❌ | n/a | ❌ |
| `authority_distribution` | ❌ | ❌ | n/a | ❌ |
| `wiki_mode` (sparse/rich) | ❌ | ❌ | n/a | ❌ |
| `funnel_stage_worker_raw` | ❌ | ❌ | n/a | n/a |
| `funnel_stage_after_dedup` | ❌ | ❌ | n/a | n/a |
| `funnel_stage_after_evidence_verify` | ❌ | ❌ | n/a | n/a |
| `funnel_stage_after_goshawk` | ❌ | ❌ | n/a | n/a |
| `funnel_summary` | ❌ | ❌ | n/a | n/a |
| `n_samples_succeeded` (NLI) | ❌ | ❌ | ❌ | ❌ |
| `nli_score` | ❌ | ❌ | ❌ | ❌ |
| `retention_kind_dist` (DAR) | ❌ | ❌ | n/a | ❌ |
| `minority_kept` (DAR) | ❌ | ❌ | n/a | ❌ |
| `cross_boundary` | n/a | n/a | ❌ | ❌ |
| `reject_reason_category` (7 类) | n/a | n/a | ❌ | ❌ |
| FN-01/03/09 active 新规则 | ❌ (history 没数据) | n/a | n/a | n/a |
| EV-01/04 experimental 新规则 | ❌ | n/a | n/a | n/a |

**同步覆盖率**: 0/18 (0%) — 看板与 Day5 完全脱节.
