# NLI / DAR Wiring 诊断 + 修法 PR 草案 (2026-04-26)

> 调研背景: main HEAD 校准 (commit `8bbdefc`, `docs/calibration_main_head_2026_04_26.md`) 显示 Sprint #6 NLI + Sprint A DAR 在 production run 上**完全没有触发**。本文做调用链解剖, 定位 short-circuit 分支, 给 3 个修法 + 推荐落地顺序。

---

## 1. 关键结论 (TL;DR)

| 项 | 结论 | 证据 |
|---|---|---|
| **NLI sparse short-circuit** | 在 `verify_evidence` line 638-647, A 类 + sparse 直接走宽松降级, **完全跳过** line 670-683 的 `_llm_nli_score` 调用 | `review/evidence_verify.py:639` `if wiki_sparse:` → `:647 v_details["reason_code"] = "A_wiki_sparse_relaxed"` |
| **DAR 死代码** | `_aggregate_advisor_results` (DAR 实现) 仅在 `advisor_review_with_resampling` 内被调用, 而该 wrapper **被零个 production caller 调用**, 全部 production 路径直接调 `advisor_review` | `goshawk_advisor.py:621 if n_samples <= 1: return advisor_review(...)` + production 调用点 `run_session.py:367` / `api/routes/review.py:461` 都不传 `n_samples` |
| **env flag opt-in** | 不存在。代码中 `os.getenv("PECKER_NLI_*")` / `os.getenv("PECKER_GOSHAWK_RESAMPLE")` 全部 **0 处** | `Grep "PECKER_NLI_\|PECKER_GOSHAWK_RESAMPLE" *.py` 返回 0 命中 |
| **历史 jsonl 反查** | 7 个业务 workspace 的所有 session jsonl 中 `"nli_score"` / `"verdict_distribution"` / `"retention_kind"` 出现次数 = **0** | `Grep "nli_score\|retention_kind\|verdict_distribution" workspace-*/output/sessions/**/*.jsonl` 返回 0 命中 |

**两个 sprint commit 进 main 后, 在所有真实业务 PRD run 上从未生效。**

---

## 2. NLI 调用链 (起点 → 终点)

```
[起点] run_session.py:291        verify_evidence(..., client=client, wiki_pages=wiki_pages)
                                                    ↓
       api/routes/review.py:404  verify_evidence (await asyncio.to_thread)
                                                    ↓
       review/evidence_verify.py:581  verify_evidence(items, workspace, client, wiki_pages, prd_content)
                                                    ↓
                                  :619 wiki_sparse = _is_wiki_sparse(wiki_dir)
                                                    ↓
                                  :628 for item in items:
                                                    ↓
                                  :638 if ev_type == "A":
                                            ┌─────────────────────────────────┐
                                            │   wiki_sparse 分叉              │
                                            └─────────────────────────────────┘
                                                    ↓                   ↓
                                       sparse=True                sparse=False (rich)
                                            :639-647                   :648-683
                                            ↓                          ↓
                                  ╔═══════════════════════╗  ┌──────────────────────────┐
                                  ║ short-circuit:         ║  │ :651 _find_wiki_page_   │
                                  ║ verified_with_caveat   ║  │      with_signal(...)   │
                                  ║ reason_code=           ║  │ ↓                        │
                                  ║   A_wiki_sparse_       ║  │ :667 if _found:         │
                                  ║   relaxed              ║  │   :672 if client + pages│
                                  ║ NLI 永远不触发 ❌      ║  │     :674 _llm_nli_      │
                                  ╚═══════════════════════╝  │          score(...)     │
                                                              │ ↓                        │
                                                              │ :678 if contradict>     │
                                                              │      entail:            │
                                                              │   confidence × 0.7      │
                                                              └──────────────────────────┘
```

**关键 short-circuit (file:line)**:
- `review/evidence_verify.py:639` — `if wiki_sparse:` 进入 sparse 分支
- `review/evidence_verify.py:647` — 分支内只写 `reason_code = "A_wiki_sparse_relaxed"` 后直接 fall-through, 不进 line 670-683 的 NLI 块
- 实际命中条件: `_is_wiki_sparse` (line 133-162) 判定 wiki_dir 中**真实业务 md** (非 META + 非 pecker_generated) 数 < 3

**为什么所有真业务 workspace 都触发 sparse**:
- `pecker_sprint_day3_plus_dual_wiki_2026_04_26` memory 记录: 7 个业务 workspace 的 99 个 wiki **0 个 canonical/trusted**, 全部 `authority=generated` → 全部被 `_is_pecker_generated` 过滤掉 → business_files < 3 → sparse=True
- 本次 calibration log 直接证实: `wiki_pages_count=11` 但 `authority_distribution.generated=11`

---

## 3. DAR 调用链 (起点 → 终点)

```
                       [production 调用点]
                       ─────────────────────
       run_session.py:367   advisor_review(client, prd_content, items, wiki_pages)
                                       ↓
       api/routes/review.py:461   advisor_review_async(client, prd, items, wiki_pages, ...)
                                       ↓
       goshawk_advisor.py:386   advisor_review_async (asyncio.wait_for wrapper)
                                       ↓
                                  :403 advisor_review(...)   <─ 单轮, 无 resample
                                       ↓
       goshawk_advisor.py:224   advisor_review (主体, single-shot)
                                       ↓
                                  返回 {flagged_as_false_positive, additional_findings,
                                        conflict_resolutions, ...}
                                       ✓ 无 verdict_distribution
                                       ✓ 无 retention_kind
                                       ✗ 没经过 _aggregate_advisor_results

       ─────────────────────────────────────────────────────────────────────
                   [DAR wrapper 调用链 — production 零调用]
       ─────────────────────────────────────────────────────────────────────

       goshawk_advisor.py:600   advisor_review_with_resampling(...)   <─ ★ 死代码
                                       ↓
                                  :621 if n_samples <= 1:
                                       ↓ (默认 n_samples=1)
                                  :622 return advisor_review(...)   <─ 默认还是回到单轮
                                       ↓ (仅当 caller 显式传 n_samples >= 2 才进下面)
                                  :625-637 ThreadPoolExecutor N 次并行 advisor_review
                                       ↓
                                  :644 _aggregate_advisor_results(results, n_samples)
                                       ↓
       goshawk_advisor.py:493   _aggregate_advisor_results
                                       ↓ (DAR 核心)
                                  :532 _retention_kind(count, n_samples)
                                       ↓
                                  返回 unanimous / majority / minority / filtered
                                  写入每条 finding 的 verdict_distribution 字段
```

**死代码确认 (file:line + 调用方画像)**:

| caller | 文件 : 行 | 是否 production | 是否调 DAR |
|---|---|---|---|
| `advisor_review` (单轮) | `goshawk_advisor.py:224` | ✓ 是 | ✗ 否 |
| `advisor_review_async` (wrapper) | `goshawk_advisor.py:386` | ✓ 是 | ✗ 否 (内部仍调单轮 :403) |
| `advisor_review_with_resampling` | `goshawk_advisor.py:600` | ✗ 否 | ✓ 是 (但 n_samples 默认 1, 一行 fallback) |
| `run_session.py:367` | CLI 入口 | ✓ 是 | ✗ 调 `advisor_review` |
| `api/routes/review.py:461` | Web API 入口 | ✓ 是 | ✗ 调 `advisor_review_async` |
| `legacy/app.py:891` | legacy | ✗ 否 (废弃) | ✗ |
| `tests/test_goshawk_resampling.py` (×10 处) | 测试 | ✗ 否 | ✓ |

**Grep 计数**:
```
$ grep -c 'advisor_review_with_resampling' *.py
goshawk_advisor.py: 4    (定义 + 文档 + 内部 fallback)
tests/test_goshawk_resampling.py: 10
其他 production 文件: 0
```

只有 test 文件调 wrapper, 所以 `_aggregate_advisor_results` + `_retention_kind` (DAR 实现) 在 production 上属于纯死代码。

---

## 4. 默认路径 vs 期望路径 vs 修法对比

| 路径 | 现状 (default) | 期望 (Sprint 改动设想) | Gap |
|---|---|---|---|
| **NLI** A 类引用验证 | sparse=True 走宽松, NLI 跳过 (100% workspace 触发, 因为 wiki 全 generated) | A 类引用拿到 wiki 内容后用 LLM 判 entail/contradict, 给连续 confidence 信号 | sparse 分支没有 NLI 入口; 即使加 client + wiki_pages 也走不到 |
| **DAR** 苍鹰多采样保留少数派 | 单轮 advisor_review, 0 次重采样 | 苍鹰跑 N=4 次, 频次聚合, minority 留低置信度信号 | 默认 caller 全部调单轮版本, wrapper 是孤岛 |
| **Sprint #2 verifier wrapper** | 同上 | 同上 | 同上 (N=1 触发 fallback line 622) |

---

## 5. 三个修法 (代码 diff 草图, 不真改)

### 修法 A — NLI sparse_relaxed 也跑 (env opt-in)

**修哪**: `review/evidence_verify.py:639-647`

**思路**: sparse 分支默认还是降级, 但加 env opt-in `PECKER_NLI_FORCE` 时仍跑 NLI, 给 PM 一个开关在 sparse workspace 也能拿到 entail/contradict 信号。

```python
# review/evidence_verify.py:638-684 (修法 A 草图)
        if ev_type == "A":
-           if wiki_sparse:
+           # sparse 默认降级, 但 PECKER_NLI_FORCE 时仍尝试跑 NLI 兜底
+           nli_force = os.getenv("PECKER_NLI_FORCE", "").lower() in ("1", "true", "yes")
+           if wiki_sparse and not nli_force:
                # 宽松模式: 无 wiki 上下文 workspace 不对 A 类硬撤回
                v_status = "verified_with_caveat"
                v_reason = ...
                v_details["found"] = None
                v_details["reason_code"] = "A_wiki_sparse_relaxed"
+           elif wiki_sparse and nli_force:
+               # sparse + opt-in: 用 wiki_pages 的全集 (而非 [[ref]] 命中页) 跑 NLI 兜底
+               # 因为 sparse 场景没有 wiki_index 命中, 没法走 _find_wiki_page_with_signal
+               v_status = "verified_with_caveat"
+               v_details["reason_code"] = "A_sparse_nli_attempt"
+               if client is not None and wiki_pages:
+                   try:
+                       nli = _llm_nli_score(client, item, wiki_pages, n_samples=2)  # 限频 2 次防 token
+                       v_details["nli_score"] = nli
+                       if nli["n_samples_succeeded"] > 0:
+                           v_details["reason_code"] = "A_sparse_nli_signal"
+                           if nli["contradict_score"] > nli["entail_score"]:
+                               item["confidence_score"] = round(item.get("confidence_score", 0.85) * 0.7, 2)
+                   except Exception as _nli_err:
+                       log.warning(f"[verify] sparse NLI 失败 skip: {_nli_err}")
            else:
                # rich 路径不变 (line 648-684 原样)
                ...
```

| 维度 | 估算 |
|---|---|
| cost Δ | 7 业务 workspace, 每 PRD 假设 5 条 A 类 → 5 × 2 sample × haiku-4-5 ($0.001/call) = ~$0.01/run |
| 时间 Δ | 串行 5 × 2 × 1.2s = 12s; 并行化可压到 3s |
| 兼容性 | 默认行为不变 (env 不开 = 老路径), 老 caller 0 影响 |
| 风险 | sparse 场景 wiki_pages 全是 pecker 自生成 → NLI 拿到的是 "pecker 自己写的 wiki" 验证 "pecker 自己提的 item" → 有 autoregressive bias 风险 (memory 已记录) |
| 收益 | 给 PM 一个观察窗口判断 sparse 场景下 NLI 信号是否有用; 不解决根本问题 (wiki 治理) |

### 修法 B — DAR 移到默认 advisor_review (单轮也保留)

**修哪**: `goshawk_advisor.py` 增加 single-sample 适配, 让 DAR 给 single-sample 也产出 retention_kind, 把 wrapper 的 verdict_distribution 字段下移到 advisor_review 的返回。

```python
# goshawk_advisor.py:280-380 (修法 B 草图, advisor_review 主体内插入)
def advisor_review(client, prd_content, worker_results, ...):
    ...
    result = _extract_advisor_result(response)

+   # DAR 对 single-sample 退化: 全部标 unanimous (n=1 时 count=1=n_samples), 让前端 schema 统一
+   # 真正的 minority 保留要靠多轮 (修法 C), 这里只是把字段补齐
+   for fp in result.get("flagged_as_false_positive", []) or []:
+       if "verdict_distribution" not in fp:
+           fp["verdict_distribution"] = {
+               "appearances": 1, "frequency": 1.0, "n_samples": 1,
+               "retention_kind": "unanimous",
+           }
+   for cr in result.get("conflict_resolutions", []) or []:
+       if "verdict_distribution" not in cr:
+           cr["verdict_distribution"] = {
+               "appearances": 1, "frequency": 1.0, "n_samples": 1,
+               "retention_kind": "unanimous",
+           }
    return result
```

| 维度 | 估算 |
|---|---|
| cost Δ | $0 (没多 LLM 调用) |
| 时间 Δ | ~0 (纯字段补齐) |
| 兼容性 | 现有 caller / test 不受影响 |
| 风险 | **DAR 单轮全是 unanimous, 实际**没有**保留任何 minority** — 改动后看着触发了实际还是死代码逻辑 |
| 收益 | **几乎为零** — DAR 算法本质需要多次采样, 没多轮就没 minority |

**结论**: 修法 B 是糖纸修法, 不解决根本问题, 不推荐。

### 修法 C — 默认切到 advisor_review_with_resampling (n_samples=4)

**修哪**: `run_session.py:367` + `api/routes/review.py:461`

```python
# run_session.py:367 (修法 C 草图)
- from goshawk_advisor import advisor_review, apply_advisor_result, format_advisor_report
+ from goshawk_advisor import advisor_review_with_resampling, apply_advisor_result, format_advisor_report
  ...
- goshawk_result = advisor_review(
-     client, prd_content, parallel_result["items"], wiki_pages,
- )
+ # 2026-04-26: 默认走 N=4 重采样 + DAR 频次聚合 (env 调整)
+ n_samples = int(os.getenv("PECKER_GOSHAWK_RESAMPLE", "4"))
+ goshawk_result = advisor_review_with_resampling(
+     client, prd_content, parallel_result["items"], wiki_pages,
+     n_samples=n_samples,
+ )
```

```python
# api/routes/review.py:461 (修法 C 草图)
- from goshawk_advisor import advisor_review_async
+ # 需要新增 advisor_review_with_resampling_async (或 to_thread 包同步版本)
+ from goshawk_advisor import advisor_review_with_resampling
  ...
- goshawk_result = await advisor_review_async(
-     client, enhanced_prd, items, req.wiki_pages, on_tool_call=_on_tool_call,
- )
+ n_samples = int(os.getenv("PECKER_GOSHAWK_RESAMPLE", "4"))
+ goshawk_result = await asyncio.to_thread(
+     advisor_review_with_resampling,
+     client, enhanced_prd, items, req.wiki_pages, None, n_samples,
+     None, _on_tool_call,
+ )
```

| 维度 | 估算 |
|---|---|
| cost Δ | n_samples=4, 每 PRD 苍鹰段 234s × 4 = 936s wallclock (并行 max_workers=4 → ~234s); cost 4 × $0.5 (sonnet) = ~$2 / run, 单次校准 $2.66 → $4.5+ |
| 时间 Δ | 苍鹰段 wallclock 不变 (并行), 但 retry/部分失败时退化 |
| 兼容性 | wrapper 已 designed-for-replacement, 但 `apply_advisor_result` 等下游消费 `verdict_distribution` 的代码需要补全; api 层还得新加 async wrapper |
| 风险 | (1) cost 翻倍 (2) Anthropic API rate limit 易触 (3) 苍鹰本身已观察到 sampling noise 大 (`pecker_sprint_day3_2026_04_26` memory 实测 merged_to_facet 4→9 浮动 125%) — 多次重采样后频次聚合是否真稳定? 不确定 |
| 收益 | DAR + verifier 都真触发, minority 信号开始进 PM 视野, recall 有望从 0.133 拉回 0.267 baseline |

---

## 6. 推荐 + 落地顺序

### 主修法: **修法 C** (默认切到 resample, n_samples=4)

**理由**:
1. NLI 的根因是 wiki 治理 (99 个 wiki 全 generated), 修法 A 是绕开问题的兜底; 即便修法 A 跑通, 用 pecker 自己生成的 wiki 验证 pecker 自己提的 item 是 autoregressive 自回归 bias, 信号质量低。
2. DAR 的根因是 wrapper 没接上 production caller, 修法 C 是直接接通 — 一个 commit 就能让 DAR + verifier 两个 sprint 改动**真正生效**。
3. 修法 C 的 cost / 时间代价虽然翻倍, 但 (a) 一次校准 $4.5 在 sprint 阶段可承受, (b) 多轮采样本来就是 `pecker_sprint_day3` 实证 sampling noise 极大的对策。

### 落地顺序

**Step 1 (修法 C 主体, 1-2h)**:
- 改 `run_session.py:344` import + `:367` 调用点
- 改 `api/routes/review.py:284, 461` 调用点 (+ 新增 wrapper async 版本或 asyncio.to_thread 包)
- 加 env flag `PECKER_GOSHAWK_RESAMPLE` (默认 4, opt-out 设 1)

**Step 2 (apply_advisor_result 适配, 30min)**:
- 检查 `apply_advisor_result` 是否消费 `verdict_distribution.retention_kind`
- 如未消费, 加 minority 标注 (PM 报告里显示 "低置信度提醒")

**Step 3 (cuckoo_eval / shrike 等下游 metric 适配, 30min)**:
- `cuckoo_eval.py` 是否需要按 retention_kind 分桶统计
- `summarize_verification` 是否需要 minority 占比指标

**Step 4 (Follow-up: 修法 A NLI sparse opt-in, 30min)**:
- 不强推, 留作 PM 观察窗口
- 默认关闭 (`PECKER_NLI_FORCE` 默认空), 等 wiki 治理改善 (memory `pecker_sprint_day3_plus_dual_wiki` 已用 wiki_promotion.py 工具) 后再开

### 下次校准建议

**不再用** `workspace-侵权软件` (模板 PRD, sampling noise 14.5% overlap, 已知 calibration 不可信)

**推荐用** 三 PRD baseline:
- `workspace-劳动仲裁` (历史 baseline 77.6% B)
- `workspace-points-payment` (积分抵扣支付, 83.6% A)
- `workspace-fengniao-诉前调解` (76.2% B)

跑法:
```bash
PECKER_GOSHAWK_RESAMPLE=4 python run_session.py --workspace=workspace-劳动仲裁 ...
```

每个 PRD 跑 3 轮 consistency, 看:
- DAR `retention_kind=minority` 实际占比
- recall / F1 是否回到 baseline
- 单次 cost 实测 (估算 $4.5 / run, 12 个 run = ~$54 总预算)

### 测试覆盖建议

**已有 test 不动**:
- `tests/test_goshawk_resampling.py` (10 个 test 已覆盖 wrapper + DAR 算法)
- `tests/test_evidence_verify_llm_nli.py` (6 个 test 已覆盖 `_llm_nli_score`)

**新加 test**:
- `tests/test_run_session_goshawk_default_path.py` — 验证 `run_session.py` 默认走 wrapper (mock 看 n_samples 传入 = 4)
- `tests/test_review_api_goshawk_default_path.py` — 同上对 API 路径
- `tests/test_apply_advisor_result_minority.py` — 验证 minority retention_kind 在 PM 报告里显示

---

## 7. 附录 — 历史 jsonl 反查证据

```
$ grep -c '"nli_score"\|"verdict_distribution"\|"retention_kind"' \
    workspace-*/output/sessions/**/*.jsonl
0  # 7 业务 workspace 全部 session 0 命中
```

```
$ grep -n 'PECKER_NLI\|PECKER_GOSHAWK_RESAMPLE\|getenv.*RESAMPLE' *.py
(无输出)   # 0 个 env opt-in
```

```
$ grep -c 'advisor_review_with_resampling' *.py
goshawk_advisor.py: 4    (定义 + 文档 + fallback, 自调用)
tests/test_goshawk_resampling.py: 10  (测试)
其他 production: 0
```

3 项独立证据互相印证: **NLI 在 main HEAD 上从未触发, DAR 在 main HEAD 上从未触发, 没有任何 env flag 可绕开**。
