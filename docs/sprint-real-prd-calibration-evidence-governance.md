# Real PRD Calibration + Evidence Governance Sprint

> **本阶段不是加功能,是回答一句话:**
> 啄木鸟在真实 PRD 上,哪些判断可信、哪些规则有效、哪些知识可作依据、哪条链路在吞结果?
>
> 做完这个 sprint,它从 "AI 评审工具" 升级为 "团队 PRD 质量系统"。

**Sprint 名称**: Real PRD Calibration + Evidence Governance
**立项日期**: 2026-04-24 (承接 P0-1 苍鹰 facet 保留 commit 213ca4c 之后)
**预估周期**: 3-4 周 (可裁,见执行顺序)
**owner**: albedolyu

---

## 一、Sprint 四主线 + 要解决的问题

| 主线 | 要解决的问题 | 判断通过的信号 |
|---|---|---|
| **A. 真实 PRD 校准** | 评审结果在真实业务文档上到底准不准 | 10-20 篇 PRD golden set,accept+edit≥30% / reject≤40% / 每篇 2-5 条有价值项 |
| **B. 知识库治理** | 哪些 wiki 能作权威依据,哪些只是线索 | 所有 wiki 有 authority 等级,`sources:0` 和 pecker 自生成不进强依据池 |
| **C. 规则瘦身** | 哪些规则该保留/改写/降级/废弃 | 每条规则有 status + precision_7d + reject_rate_7d + last_reviewed,每周 slim 一次 |
| **D. 漏斗观测** | worker / 去重 / 证据校验 / 苍鹰 / PM 决策 各吞多少 | 每次 run 能回答 5 层损耗率,对比上一轮差值 |

---

## 二、五条优先级 (细分 + 交付物)

### 优先级 1 (主线 A): 真实 PRD 校准集

**目标**: 10-20 篇真实 PRD,覆盖 7 种类型
- 数据字段型
- 前端交互型
- 后端接口型
- 模板残留型 ✓ (已有 侵权软件/未准入境模板)
- 新业务型
- 老业务迭代型
- 跨系统依赖型

**每篇 PRD 的 ground truth 结构**:
```json
{
  "prd_path": "workspace-xxx/prd/xxx.md",
  "prd_type": "数据字段型 | 前端交互型 | ...",
  "真实问题": [{"id": "GT-001", "location": "...", "issue": "...", "severity": "must", "rule_hit": "RC-xxx"}],
  "误报": [...],
  "漏报": [...],
  "pm_decisions": {"accept": [...], "edit": [...], "reject": [{"item_id": "...", "reason_category": "..."}]},
  "knowledge_refs": [{"wiki_page": "...", "authority": "canonical|trusted|contextual|generated"}],
  "final_value": "高/中/低",
  "multi_run_overlap_on_core": 0.XX
}
```

**成功标准** (sprint 结束):
- [ ] accept + edit ≥ 30%
- [ ] reject ≤ 40%
- [ ] 每篇至少 2-5 条 PM 认为有价值的问题
- [ ] 同一 PRD 多轮评审核心问题有明显重合 (overlap on core >= 50%)

**交付物**:
1. `eval/ground_truth/v3/` 目录,10+ 份 JSON
2. `scripts/calibration_runner.py` CLI — 跑一篇 / 跑全集 / 产出对比表
3. `docs/calibration-report-YYYY-MM-DD.md` 周报模板

---

### 优先级 2 (主线 B): 知识库治理 — 从资料库升级为证据系统

**目标**: 每个 wiki 页面带权威等级 + 来源 + 校对人 + 校对日

**Wiki frontmatter schema (v2)**:
```yaml
authority: canonical | trusted | contextual | generated
owner: albedolyu
sources: 2               # 外部权威来源数,必须 >=1 才能升 trusted,>=2 可升 canonical
last_verified: 2026-04-24
verified_by: PM | 研发 | 数据
```

**使用规则** (evidence_verify 读这 5 个字段):
| authority | 用途 | A 类强依据? |
|---|---|---|
| canonical | 业务真相 (来自官方文档/法规/DDL) | ✓ |
| trusted | 可支撑判断,需结合 PRD | ✓ (但 confidence × 0.85) |
| contextual | 仅帮助理解业务 | ✗ (只作 B 类) |
| generated | pecker 自生成 | ✗ (只作线索 C 类) |

**铁律保留**:
- `sources: 0` **永不**进强依据池
- pecker 自生成页面 **永不**进强依据池 (即使人工修过也要显式提升 authority)

**默认映射 (无需人工打标的冷启动规则)**:
- `sources: 0` → `authority: generated`
- `sources >= 1 && verified_by 为空` → `authority: contextual`
- `sources >= 1 && verified_by 有 && authority 未显式` → `authority: trusted`
- `authority: canonical` 必须显式设置且有 `last_verified`

**交付物**:
1. Wiki frontmatter v2 spec (docs/wiki-frontmatter-v2.md)
2. `scripts/wiki_lint.py` 校验 schema + 统计各 authority 分布
3. `review/evidence_verify.py` 改读 authority 字段 (替代现在的 `_is_pecker_generated`)
4. 迁移脚本: 按默认映射批量补 authority (不改业务内容)

---

### 优先级 3 (主线 D): 评审漏斗观测

**目标**: 每次 run 产出 5 层通过率

```
worker_raw_items         N0
├─ dedup_dropped         = N0 - N1   (去重吞了多少)
after_dedup_items        N1
├─ evidence_verify_dropped = N1 - N2 (证据验证误杀多少)
after_evidence_verify    N2
├─ goshawk_merged_to_facet = N2 -> (N3 + facets)  (苍鹰合并了多少成 facet)
├─ goshawk_removed       = 过滤的 REMOVED_BY_ADVISOR
after_goshawk_items      N3  (含 facet)
├─ pm_rejected           = N3 - N4
after_pm_decision        N4
```

**核心问题能回答**:
- worker 原始产出够不够? (N0 ≥ 基线 30-35 ?)
- 去重吞 facet 没? (dedup_dropped 的 location 分布 vs 保留条)
- Evidence verify 误杀率? (evidence_verify_dropped 的 severity 分布)
- 苍鹰合并过狠? (goshawk_merged_to_facet / N2)
- PM 到底接受了哪类? (N4 的 severity/rule 分布)

**交付物**:
1. 新 JSONL event types (在 `workspace-*/output/sessions/rev_*.jsonl` 追加):
   - `stage_worker_raw { count, by_dimension }`
   - `stage_after_dedup { count, dropped_ids }`
   - `stage_after_evidence_verify { count, dropped_ids, dropped_reasons }`
   - `stage_after_goshawk { count, merged_facet_count, removed_count, added_count }`
   - `stage_after_pm_decision { count, by_reason }` (来自 Phase 3 or 事后补录)
2. `scripts/funnel_report.py` — 聚合最近 N 个 session jsonl,产 markdown 表
3. (后续) dashboard 加"漏斗视图"tab

---

### 优先级 4 (主线 C): 规则生命周期

**目标**: 每条规则可观测 + 可 slim

**规则 schema v2** (加在 `review-dimensions.yaml` 每条规则 frontmatter):
```yaml
- rule_id: RC-009
  status: active | experimental | noisy | deprecated
  owner: albedolyu
  precision_7d: 0.62     # (accept + edit) / (accept + edit + reject)
  reject_rate_7d: 0.38
  last_reviewed: 2026-04-24
  description: ...
  checklist: [...]
```

**每周 rule slimming 决策矩阵**:
| 命中率 | reject_rate | 动作 |
|---|---|---|
| 高 | 高 | 改写或降级到 experimental |
| 高 | 低 | keep (active) |
| 低 | 高 | 降级或合并 |
| 低 | 低 | deprecated |
| (多规则命中同一 item) | — | 合并 |
| (抽象描述无 checklist) | — | 改成可判定 checklist |

**交付物**:
1. 规则 schema v2 迁移 (review-dimensions.yaml 加 status/precision/reject_rate/last_reviewed)
2. `scripts/rule_lifecycle.py` — 每周跑:
   - 从 rule_perf_store 读每条规则过去 7 天 precision/reject_rate
   - 写回 review-dimensions.yaml 对应字段
   - 输出 "本周建议瘦身" markdown 报告
3. `docs/rule-slimming-YYYY-WW.md` 周报模板

---

### 优先级 5 (主线 C+A 交叉): PM 反馈分类

**目标**: reject 不只是负反馈,是**能告诉你该修规则/修知识库/修模型链路**的信号

**7 种 reject reason 枚举**:
```python
class RejectReason(str, Enum):
    GOOD_ISSUE = "good_issue"           # 实际是好问题 (手滑点错)
    FALSE_POSITIVE = "false_positive"   # 误报
    KNOWN_TRADEOFF = "known_tradeoff"   # 已知取舍,不改
    WIKI_MISSING = "wiki_missing"       # 知识库缺失导致评审没上下文
    RULE_TOO_STRICT = "rule_too_strict" # 规则太严
    IMPL_DETAIL = "impl_detail"         # 实现细节,不该 PRD 管
    MODEL_NOISE = "model_noise"         # 模型噪音,无业务意义
```

**每种 reason 对应的修法**:
| reason | 对谁的信号 |
|---|---|
| false_positive | rule precision ↓,考虑降级 |
| wiki_missing | 知识库补 canonical 页,补 owner |
| rule_too_strict | 规则改写 / 改 checklist / 加白名单 |
| impl_detail | 规则 scope 收窄 (仅 PRD 级) |
| model_noise | 模型/prompt 调优 |
| known_tradeoff | 加 PRD 级 pin 或项目级 ignore |
| good_issue | (用户体验,忽略) |

**交付物**:
1. 后端:`models.py` 的 PMDecision 加 `reject_reason` 字段 + 枚举 / `api/routes/phase3.py` (或类似) 写入
2. 前端: Phase 3 reject 按钮 → 弹 7 选 1 dropdown (后做)
3. 聚合: `scripts/reject_reason_report.py` 产周报

---

## 三、输出层收敛 — 三层报告

**当前报告**: 按章节分组,每条 `[必须] / [建议] / [补充·Rxxx]` (P0-1 刚加了 [补充])

**目标报告**: 三层清晰给 PM

```
必须修    — 影响开发/验收/数据一致性 (severity=must)
建议补    — 提升清晰度和可实现性 (severity=should)
待确认    — 知识不足 / 规则不确定 / 同源 facet (severity=could || confidence<0.6)
```

**交付物**:
1. `report_builder.py` 输出三 section,每 section 内再按章节分组
2. 自动化分桶逻辑: severity could → 待确认, confidence<阈值 → 待确认

---

## 四、执行顺序 (推荐)

按投入/收益权衡,执行顺序与优先级编号不完全一致:

| # | 动作 | 工作量 | 解锁 | 依赖 |
|---|---|---|---|---|
| 1 | Wiki frontmatter v2 schema + 默认映射迁移 | 0.5d | 主线 B 冷启动,不改代码也能算 authority | 无 |
| 2 | 漏斗 JSONL event types + funnel_report.py | 1d | 主线 D 全套,单日出数据 | 无 |
| 3 | 建第 1 篇真实 PRD ground truth (已有侵权软件模板,用它先打通 pipeline) | 0.5d | 主线 A pipeline 验证 | 无 |
| 4 | PM reject reason 后端字段 + 枚举 | 0.3d | 主线 C 信号源 | 无 (UI 后做) |
| 5 | evidence_verify 读 authority 字段 (替换 _is_pecker_generated) | 0.5d | 主线 B 落地 | 1 完成 |
| 6 | 规则 schema v2 迁移 + rule_lifecycle.py | 1d | 主线 C 周度 slim | 无 |
| 7 | 真实 PRD 扩到 5 篇 (数据字段/前端交互/后端接口/新业务 各 1) | 2-3d | 主线 A 置信度 | 3 完成 |
| 8 | 三层报告重构 (必须修/建议补/待确认) | 0.3d | 主线 A 收敛 | P0-1 的 could facet 已经在 |
| 9 | 报告联动 wiki authority (引用 canonical/generated 时 badge 不同) | 0.5d | 主线 B x 主线 A | 5 + 8 |
| 10 | 第一次周度 rule slim + 周报 | 0.5d | 主线 C 闭环 | 6 完成 |

**第一周目标**: 做完 1-6,基础设施就位,数据可算
**第二周目标**: 做完 7-10,校准集扩量 + 闭环跑通
**第三周目标**: 校准集扩到 10 篇 + 第一次正式周报 + 指标落地

---

## 五、Sprint 健康度检查 (每周末自问)

- [ ] 本周产出的新 ground truth 数 >= 2
- [ ] 新增 accept/edit 样本数 >= 20
- [ ] 至少 1 条规则被 slim (改/降/废)
- [ ] 至少 1 条 wiki 被升级 authority 或补 sources
- [ ] 漏斗表每次 run 都能出
- [ ] 本周有"reject_reason 聚类"明显指向某 rule 或 wiki 问题

任一连续 2 周不达标 → sprint scope 需裁

---

## 六、非目标 (本 sprint 不做)

- 新的 agent / worker / model 切换
- 新的评审维度 (dimension)
- Web UI 大重构 (只加 reject dropdown 和 funnel tab,不重排布局)
- workspace 从 repo 剥离 (见 `memory/pecker_workspace_tracking_defer.md`,触发条件不变)

---

## 七、首批 5 个可落地任务 (第一周)

> 按 投入/收益/依赖 排序。全部向后兼容,单测覆盖,失败不阻塞评审流程。
> 5 个任务 **T0 0.3d + T1-T5 2.5d = 2.8d** (T0 合后 T3 从 1.5d 降回 1d),第一周收尾。
>
> **audit 探针派出后未产出** (task runner 异常,0 字节文件 35min 无动静, `TaskStop` 返回 no task) → 以现场 grep 定稿。行号基于 2026-04-24 main HEAD commit `3e040c6`。
>
> **第二版自检发现 + 第三版 T0 解决**:
> - ~~API flow 和 CLI flow pipeline 不同~~ → **T0 (commit 8f57f46) 已统一**, API flow 现在也跑 full `verify_evidence`, T3 funnel 退回统一 5 层, 工量 1.5d → 1d
> - T1 IOError 默认原本 `False` (保留进 wiki_index),不能改成 `generated` (会剔掉文件),改为 `contextual` 保持 index 存在性。
> - T5 ground truth 路径实际平铺在 `eval/ground_truth/`,无 v2 子目录。
> - T2 `decision` dict 在 `api/routes/review.py:549` for 循环内作用域中 ✓ 可直接访问。

---

### T0. API flow 接入 `verify_evidence` (pre-sprint blocker)

**优先级**: P0 blocker (必须先做完才能跑 T1-T5)
**工量**: 0.3 天
**依赖**: 无
**动机**:

第二版自检发现 API flow 跳过 full `verify_evidence`,只有 CLI + 飞书跑。这让:
- Web 用户享受不到 2026-04-23 `e3ea5c3` 的 evidence_verify 降权改进
- T1 `_wiki_authority_tier` 改进只利好 CLI,API 侧无感
- T3 funnel 被迫分两条 flow (1d → 1.5d)

修完后 API 和 CLI pipeline 统一,T3 退回 1d,T1 收益全覆盖。

**修改文件**:
- `api/routes/review.py:371` 之后 (在 `items = result.get("merged_items", [])` 之后,Pattern 21 checkpoint 之前) 插入:

```python
# 2026-04-24 P0 blocker: API flow 统一走 verify_evidence,与 CLI run_session.py:276 对齐
# 之前只靠 goshawk `_verify_wiki_evidence` 侧查代替,少了:
# (1) B 类 rule_id 在 review-rules/ 的硬查; (2) A 类 caveat + confidence × 0.7 降权; (3) sparse/rich 模式切换
try:
    from review.evidence_verify import verify_evidence, summarize_verification
    verified = verify_evidence(items, ws_abs_path)
    items = [i for i in verified if i.get("status") != "RETRACTED"]
    v_sum = summarize_verification(verified)
    evt.append("evidence_verify_done", {
        "total": v_sum.get("total", 0),
        "verified": v_sum.get("verified", 0),
        "caveat": v_sum.get("caveat", 0),
        "retracted": v_sum.get("retracted", 0),
        "reliability": v_sum.get("reliability", 0.0),
    })
    emitter.emit("evidence_verify_done", data={
        "retracted": v_sum.get("retracted", 0),
        "caveat": v_sum.get("caveat", 0),
    })
except Exception as e:
    log.warning(f"[evidence_verify] 失败回退到跳过模式: {e}")
    # 失败不阻塞: items 不变,行为等同于本次修复前
```

**不动的**:
- `goshawk_advisor.py:785-796` 的 `_verify_wiki_evidence` 侧查 **保留** (defense in depth,二次 wiki 标题校验仍有价值)
- CLI flow 不动 (已经有 verify_evidence)

**验证命令**:
```bash
# 单测: evidence_verify 失败不阻塞 API
pytest tests/test_review_api_evidence_verify.py -v                     # 新增

# 回归: 现有测试不破
pytest 2>&1 | tail -5                                                  # 期望 627 passed

# 真 pecker run (CLI path, 行为不变)
python run_session.py 未准入境需求文档-v1.0 --workspace workspace-侵权软件 \
    --non-interactive --auto-decide accept-all                         # 期望最终 items >= 10 (与 P0-1 一致)

# API path smoke (如果 web 服务在跑)
# curl 一个 review 请求, grep jsonl "evidence_verify_done"
```

**潜在风险 & 对策**:
| 风险 | 对策 |
|---|---|
| API 响应多 100-200ms | verify_evidence 主要是 glob + frontmatter 读, 典型 workspace (<50 wiki 文件) 跑时 ~50-100ms, 可接受 |
| 原本的 verified items 被 retract 导致 Web 产出变少 | sparse mode + 2026-04-24 降权改进已让 retract 最小化, 模板 PRD 回归测能兜底 |
| goshawk `_verify_wiki_evidence` 重复计算 | 保留,二次校验仍有价值 (后续考虑整合) |
| 现有 test_e2e / test_api_auth 是否依赖原行为 | 无 `verify_evidence` 的直接断言, 不破 |

---

### T1. Wiki frontmatter v2 — `_wiki_authority_tier` 替换 binary 筛选

**优先级**: P0
**工量**: 0.5 天
**依赖**: 无 (向后兼容)
**参考 spec**: `docs/wiki-frontmatter-v2.md`

**修改文件**:
- `review/evidence_verify.py:34-58` → 重写 `_is_pecker_generated`,内部走 `_wiki_authority_tier(path) == "generated"`
- `review/evidence_verify.py` → 新增 `_parse_wiki_frontmatter` + `_wiki_authority_tier` (spec 第五节 draft 直接用)

**不用改的调用点** (保留 binary 接口):
- `review/evidence_verify.py:88` (`_is_wiki_sparse` 里的 `and not _is_pecker_generated(f)`)
- `review/evidence_verify.py:104` (`_build_wiki_index` 里的 `if _is_pecker_generated(wiki_file): continue`)
- `tests/test_evidence_verify_wiki_sparse.py` 引用点

**关键修正** (第二版):
- IOError 时 `_wiki_authority_tier` 返回 `"contextual"` (不是 `"generated"`) — 保留老 `_is_pecker_generated` 的 `return False` 语义: 读失败的文件仍进 wiki_index,只是不作强依据

**验证命令**:
```bash
pytest tests/test_evidence_verify_wiki_sparse.py -v                    # 现有 test 不破
pytest tests/test_wiki_authority_tier.py -v                            # 新增单测 (4 tier × 冷启动 5 条件)
python run_session.py 未准入境需求文档-v1.0 --workspace workspace-侵权软件 \
    --non-interactive --auto-decide accept-all                         # 回归 P0-1 run
# 期望最终 items >= 10 (与 commit 213ca4c 的 baseline 一致)
```

---

### T2. PM reject reason 7-enum + rule_perf delta 分档

**优先级**: P0
**工量**: 0.5 天
**依赖**: 无 (向后兼容)
**参考 spec**: `docs/pm-reject-reason-schema.md`

**修改文件**:
- `models.py:22` 之后 → 新增 `class RejectReason(str, Enum)` + `@dataclass PMDecision`
- `api/routes/review.py:557` 之后 → 抽 `reason_category = decision.get("reason_category", "model_noise")` (此时 `decision` 已在 scope, L549 for 循环内)
- `api/routes/review.py:576` 之后 → `reject` 分支追加 `entry["stats"].setdefault("reject_by_reason", {})[reason_category] += 1`
- `api/routes/review.py:591-594` → `reject` delta 按 `reason_category` 分档:
  ```python
  elif action == "reject":
      delta_by_reason = {
          "false_positive": -0.5, "rule_too_strict": -0.5,
          "model_noise": -0.3, "impl_detail": -0.3,
          "wiki_missing": -0.1, "known_tradeoff": -0.1,
          "good_issue": 0.3,
      }
      delta = delta_by_reason.get(reason_category, -0.3)
  ```
- `api/routes/review.py:641-648` → `_save_eval_ground_truth` 每条加 `reason_category` + `reason_note[:200]`

**向后兼容**:
- 老 payload `{"action": "reject", "reason": "自由文本"}` → 读取时 `reason_note = reason`,`reason_category = "model_noise"` 默认
- 前端不改,模型任意 reason_category 缺失都走默认值,`_save_eval_ground_truth` 写空字符串

**验证命令**:
```bash
pytest tests/test_rule_perf_reject_reason.py -v                        # 新增: 7 reason × delta + 分桶
pytest tests/test_core.py -v -k "decision"                             # 现有决策 test 不破
# 手动: curl /api/review/confirm 发 7 种 reason_category,grep eval/ground_truth/*.json 确认字段落地
```

---

### T3. Funnel 6 个 stage event — 统一 5 层 (API + CLI)

**优先级**: P1
**工量**: 1 天 (T0 合入后 pipeline 统一, 从 1.5d 降回 1d)
**依赖**: T0 完成 ✓ (commit 8f57f46)
**参考 spec**: `docs/review-funnel-schema.md`

**T0 合入后 pipeline 统一**, API + CLI 都是 5 层: raw → dedup → evidence_verify → goshawk → PM (仅 API 有 Phase 3)

**修改文件 (API flow)** — 6 处 emit 全部就位:
- `api/routes/review.py:371` 之后 → `funnel_stage_worker_raw` (从 `worker_done` 事件累加 + `by_dimension`)
- `api/routes/review.py:371` 之后 → `funnel_stage_after_dedup` (`len(merged_items)`)
- `api/routes/review.py` 的 T0 evidence_verify 块 (已有 `evidence_verify_done` event) → 改名/扩为 `funnel_stage_after_evidence_verify` + 加 `retracted_by_reason` / `downgraded_by_reason` / `wiki_mode` / `authority_distribution` 字段
  - `review/evidence_verify.py summarize_verification` 返回值扩展 telemetry
- `api/routes/review.py:411` 之后 → `funnel_stage_after_goshawk` + `delta_breakdown` + `facet_links`
  - `goshawk_advisor.py apply_advisor_result` 返回 items 时附加 `_funnel_telemetry` 字段 (附第一 item 上或改签名返元组)
- `api/routes/review.py:696` 附近 (confirm_review) → `funnel_stage_after_pm_decision` + `rejected_by_reason`
- `api/routes/review.py:490` 之前 → `funnel_summary` + `stage_retention` + `suspicious_flags`

**修改文件 (CLI flow)** — 同样 5 层, 但 PM 环节是可选 (CLI 不走 Phase 3):
- `run_session.py:276` 前后 → `funnel_stage_worker_raw` + `funnel_stage_after_dedup` + `funnel_stage_after_evidence_verify`
- `run_session.py` goshawk 调用点之后 → `funnel_stage_after_goshawk`
- `run_session.py` 结束前 → `funnel_summary` (CLI 下 PM 层缺失, `funnel_summary` 体现为 N4 = N3)

**验证命令**:
```bash
python run_session.py 未准入境需求文档-v1.0 --workspace workspace-侵权软件 \
    --non-interactive --auto-decide accept-all
grep -c "funnel_stage_\|funnel_summary" workspace-侵权软件/output/sessions/rev_*.jsonl  # 期望 >= 5
# 手动 API 侧: 走一遍 web 流 + Phase 3 confirm, grep "funnel_stage_after_pm_decision" jsonl
pytest tests/test_funnel_emit_resilience.py -v                                          # 新增: mock emit 抛异常不阻断
```

---

### T4. Wiki lint warn-only + 首次 migrate dry-run

**优先级**: P1
**工量**: 0.3 天
**依赖**: T1 完成
**参考 spec**: `docs/wiki-frontmatter-v2.md` 第四 + 第六节

**新建文件**:
- `scripts/wiki_lint.py` — 扫描 `workspace-*/wiki/*.md`:
  - 必填字段缺失 (title/authority/owner/sources) → warn
  - `authority: canonical/trusted` 时 `sources` 不足或 `last_verified` 过期 → warn
  - YAML frontmatter 解析失败 → warn
  - 输出: workspace × authority tier 分布统计表 (markdown)
- `scripts/wiki_migrate_v2.py` — **只支持 --dry-run** (第一周不开 --apply):
  - 对每页按冷启动映射算推导 authority (调用 T1 的 `_wiki_authority_tier`)
  - 输出 "本轮会改 X 个文件,新分布 canonical=0 trusted=2 contextual=Y generated=Z" 统计表
  - `--apply` 留参数但本周跑会 error out "第一周只允许 dry-run"

**包注册** (per memory `feedback_verify_call_sites` Rule 4b):
- `scripts/` 已在 `pyproject.toml` `[tool.setuptools] packages` 里,新增 .py 无需声明

**验证命令**:
```bash
python scripts/wiki_lint.py                                             # 不 crash,贴统计表
python scripts/wiki_migrate_v2.py --dry-run                             # 不改文件,贴分布表
python scripts/wiki_migrate_v2.py --apply                               # 期望 exit 1 + "第一周只允许 dry-run"
```

---

### T5. 第一篇真实 PRD 校准 pipeline 打通 (侵权软件作载体)

**优先级**: P1
**工量**: 0.5 天
**依赖**: 无 (T2 为 **nice-to-have**,让 report 能切 reject 分布;不阻塞 pipeline 本身)
**参考 spec**: `docs/sprint-real-prd-calibration-evidence-governance.md` 主线 A

**关键修正** (第二版):
- ground truth 路径是 **`eval/ground_truth/`** (平铺),不是 `v2/` 子目录

**新建文件**:
- `scripts/calibration_runner.py` — CLI:
  ```bash
  python scripts/calibration_runner.py \
      --workspace workspace-侵权软件 \
      --prd 未准入境需求文档-v1.0 \
      --ground-truth eval/ground_truth/infringement_software_template_albedolyu_1777011594.json \
      --runs 3
  ```
  - 内部调 `eval/consistency_eval.py` 跑 N 轮
  - 对比现有 ground truth 计算: precision / recall / accept+edit rate / multi-run overlap on core items
  - 若 T2 已合入,按 `reason_category` 切 reject 分布 (否则显示 "(T2 未合入)")
  - 输出: `docs/calibration-report-2026-04-24.md` 模板

**复用函数**:
- `eval/consistency_eval.py` (已有,返回每轮 worker 输出)
- `eval/metrics/*` (如有,否则脚本内置)

**验证命令**:
```bash
python scripts/calibration_runner.py --workspace workspace-侵权软件 \
    --prd 未准入境需求文档-v1.0 --runs 3
ls docs/calibration-report-*.md                                         # 新文件
# 手工对账 1-2 个指标: 如 "precision 计算公式是否正确" (分母对不对)
```

---

### 执行顺序 (强依赖图)

```
T1 (wiki tier) ────→ T4 (lint + migrate dry-run)
T2 (reject reason) ─→ T5 (可选,报告更完整)
T3 (funnel emit) — 完全独立,可并行

T5 独立可跑: T2 未合入时 reason 分布那栏占位
```

**推荐节奏** (第二版修订):
- **Day 1**: T1 + T2 并行 (各 0.5d,无依赖)
- **Day 2-3 上午**: T3 (1.5d,分 API + CLI 两条 flow)
- **Day 3 下午**: T4 (0.3d,依赖 T1)
- **Day 4 上午**: T5 (0.5d,独立,可选依赖 T2)

**共 3.0 天**,第一周 (5 工作日) 收尾。余出 Day 4 下午 + Day 5 做:
- PR 拆分 / review / 合并
- 跑一次完整端到端回归 (CLI + Web)
- 第一次跑 T5 calibration report + 人工对账

第二周可以开始:
- 真 apply migrate (`wiki_migrate_v2.py --apply`)
- Funnel 聚合脚本 (`scripts/funnel_report.py` — 在 spec 里但未放 T3)
- 2-3 篇新 PRD ground truth (扩主线 A 覆盖)
- 第一次 rule_lifecycle 周度 slim

---

## 八、关联资产

- P0-1 苍鹰 facet 保留: commit `213ca4c`
- Evidence verify 降权改造: commit `e3ea5c3`
- 修复诊断记忆: `memory/pecker_template_prd_sampling_noise_2026_04_24.md`
- 上线 gate: `memory/pecker_prelaunch_gates_2026_04_23.md`
- 自我审查 4 Rule: `memory/feedback_verify_call_sites.md`
- Workspace 剥离延后: `memory/pecker_workspace_tracking_defer.md`

---

**一句话定调**:
> 不要再证明啄木鸟"会评审",而是证明它"知道哪些依据可信、哪些规则有效、哪些输出值得 PM 采纳"。
