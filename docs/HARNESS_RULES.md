# Harness Engineering Ruleset

> 从啄木鸟 (Pecker) 项目 73 commits、13 轮深度审计、3 个真实 runtime bug、490 单测、6 类 session 分类框架中提炼。
> 每条规则带历史来源，可倒查 commit / 文件 / memory 条目。
> 用法：启动新 harness 先读 Top 10，遇到具体问题按 I-VII 查规则。

---

## 启动新 harness 必用 · Top 10

新建一个 agent 系统时，这 10 条是"骨架 + 观测 + 防线"的最小集。漏一条后期都要补双倍成本。

| # | 规则 | 为什么必备 |
|---|------|------------|
| 1 | **M1 看真实数据 > 猜** | 自评文档漂移是常态，session jsonl 和 STATUS 才是真相源 |
| 2 | **M2 harness ≠ prompt 问题** | 80% "模型表现差" 是系统设计问题 (静默吞异常/反馈未回流/边界未约束)，先查 harness 再调 prompt |
| 3 | **R1 单向拓扑** | orchestrator → workers 单向，禁止 worker 互调。聚合只在 orchestrator 或 meta |
| 4 | **R2 Meta-reviewer 交叉校验** | 单层输出不可信，必须有 meta 层做"误报/漏报/冲突"三类修订 |
| 5 | **R4 模型分工** | Pattern matching → Sonnet；深推理 → Opus；二元判定 → Haiku。别默认全 Opus |
| 6 | **R6 结构化输出 + 三级降级** | tool_choice=any → retry → 文本兜底 → APIError。禁止"静默返回空壳" |
| 7 | **R11 反馈闭环在主路** | 用户决策自动回流 EMA，不依赖手动脚本。旁路闭环等于没闭环 |
| 8 | **R15 STATUS 自动生成，删手写自评** | 手写 MATURITY/READINESS 必漂移；从 git+pytest+jsonl 自动生成 |
| 9 | **R16 指标分层，剔除 ops 噪声** | session 分 6 类 (productive/partial_silent/empty_bug/quota/auth/other)，混算会误判 |
| 10 | **R21 全员失败 abort，失败必须可见** | 别让 0 items 的"绿色报告"发给用户做决策，发 review_failed SSE 不走 completed |

---

## 元规则

**M1 · 看真实数据 > 猜**
每次判断前先看 `STATUS.md` + session jsonl，不看自评文档。

**M2 · Harness 问题 = 系统设计问题，不是 prompt 问题**
80% 的"模型表现差"其实是 harness 没接好（静默吞异常 / 反馈没回流 / 边界没约束）。先查 harness 再调 prompt。

**M3 · 每个抽象都有上限**
meta-reviewer 最多一层 / 漏报上限 N 条 / retry 上限 3 次 / feedback EMA alpha=0.15。没有无界的兜底。

**M4 · 新代码 + 新测试同 commit 落地**
P0 修复必须配套单测。143 → 490 单测是 13 轮迭代的副产品，不是额外工作。

---

## I. 拓扑与边界 · Agent 级设计

**R1 · 单向拓扑，禁止 worker 互调**
orchestrator → specialist workers。worker 之间不通信、不聚合、不互相依赖。聚合只在 orchestrator 或 meta-reviewer。
> 来源：v1.0.0 鸟类家族初始分工，`review/orchestration.py` / `goshawk_advisor.py`

**R2 · 不信任单层输出，必有交叉校验**
4 Worker 产出必须过 meta-reviewer（苍鹰）。meta 做"误报/漏报/冲突"三类修订，不做重审。
> 来源：v1.0.0，Phase G Wave 2，`goshawk_advisor.py:advisor_review`

**R3 · 约束 meta-reviewer 行为**
漏报补充设上限（最多 N 条）；不得重审 Worker 已出的 items；必须输出结构化 verdict（REVIEWED / EMPTY_APPROVAL / SILENT / TIMEOUT）。
> 来源：iteration round 3 修苍鹰空提交静默被接受

**R4 · 模型分工按任务类型，不按默认最强**
Pattern matching → Sonnet；深推理（pseudocode / traceability）→ Opus；二元判定（sanity check）→ Haiku。别给 worker 全配 Opus。
> 来源：ARCHITECTURE.md Model Assignment；be5fead 把苍鹰从 Opus 降到 Sonnet

**R5 · 工具上限 3-5 个 / worker**
Worker 配全部工具会让 tool_choice 判断不稳定。每个 worker 接收精简 tool set。
> 来源：CLAUDE.md + iteration 经验

---

## II. 输出契约 · 不信任单层

**R6 · 结构化输出强制 + 三级降级**
`tool_choice: {"type": "any"}` → 失败催促重试 → 文本兜底解析 → 仍失败抛 APIError。禁止"静默返回空壳"。
> 来源：04-16 P0 漏洞 B，`api_adapter.py:594` 历史 bug

**R7 · 空提交 = 半沉默，必须专门检测**
model 调了 tool 但 items=[] 是高发 failure mode（data_quality / quality 曾 50% 静默）。新增 `_is_empty_tool_submission` + retry 分支，retry prompt 要求"要么补齐，要么显式说无问题"。
> 来源：iteration round 3，`pecker_empty_submission_retry_landed.md`

**R8 · 依据必须可验证 · A/B/C 分层**
A=内部知识 / B=评审规则 / C=外部参考。每条 item 带 `evidence_type` + `evidence_content`。B 类做语义相似度核对（低于阈值标 `verified_with_caveat`），C 类做 Side Query 验证失败自动撤回。
> 来源：v1.0.0 + P2 `_verify_b_class_semantic`

**R9 · 越界 rule_id 运行时剔除**
Worker 若输出不属于本维度 checklist 的 rule_id，标 `cross_boundary` → 从输出剔除或降 confidence。不等 Eval 再发现。
> 来源：v1.3.0 P1 runtime 校验

**R10 · Opaque handle + 签名**
Phase 2 → Phase 3 跨边界的 `ReviewResult` 带 HMAC-SHA256 签名，Phase 3 confirm 前 `verify_signature`，防篡改。
> 来源：`api/models.py:compute_signature`

---

## III. 反馈闭环 · 从主路而非旁路

**R11 · 反馈闭环在 confirm 路径上，不在离线脚本**
Phase 3 的 Y/N/E 决策自动回流 `rule_performance_history.json`（EMA alpha=0.15：accept +1.0 / edit +0.7 / reject -0.5）。不依赖手动跑 feedback.py。
> 来源：v1.3.0 P0，`_update_rule_perf_from_decisions`

**R12 · 规则权重注入 Worker prompt**
`impact_score` 低（<0.3）→ "谨慎报告"；高（>0.8）→ "优先检查"。Worker 评审时感知历史表现。
> 来源：v1.3.0，`_build_feedback_section`

**R13 · 决策即 ground truth**
Phase 3 决策同步落 `eval/ground_truth/*.json`，可直接喂 cuckoo_eval 做回归。不需要另外标注。
> 来源：v1.3.0 P0，`_save_eval_ground_truth`

**R14 · Meta-reviewer 也要闭环**
`goshawk_performance_history.json` 累积苍鹰判断 vs 用户决策一致性，动态调整 meta 的 confidence 权重。
> 来源：v1.3.0 P2 苍鹰反向校验

---

## IV. Eval 与真相源

**R15 · 自评文档一律视作不可信，以自动生成的 STATUS.md 为准**
删除手写 HARNESS_MATURITY.md / PRODUCTION_READINESS.md，靠 `scripts/generate_status.py` 从 git log + pytest + session jsonl 生成。
> 来源：memory `pecker_docs_drift.md`；iteration round 0 删两份自评

**R16 · 指标必须分层，剥离 ops 噪声**
`session` 分 6 类：productive / partial_silent / empty_bug / quota_exhausted / auth_expired / error_other。`effective_consistency = productive / 非 ops 总数`。混算会误判系统崩坏。
> 来源：SHADOW_RUN_FINDINGS round 15 + STATUS.md

**R17 · Error fingerprint 归一化聚合**
所有错误归一化（打码路径 + 时间戳）后聚合 count。`count=2` 的重复错误直接暴露，比 raw error list 有效得多。
> 来源：iteration round 1

**R18 · "other / 兜底" 类别是地雷**
看到某兜底类占比 >30% 必须主动拆（shadow run 把 other=95% 拆出 auth_401=95%）。
> 来源：SHADOW_RUN_FINDINGS round 15

**R19 · telemetry 先加，数据后有**
新 field 和聚合代码先落代码，即使当下数据为 0。telemetry 持久化路径通比一时数据重要。
> 来源：iteration round 2 empty_retry_used

**R20 · pre-fix / post-fix cutoff 分口径**
修过 bug 后，历史数据按 `POST_FIX_CUTOFF_EPOCH` 划分，不让老 session 污染新指标。
> 来源：7fd3f2f

---

## V. 稳定性护栏 · 失败必须可见

**R21 · 全员失败 abort，不允许"绿色的 0 items 报告"**
orchestrator Phase 2 完成后，所有 worker 都 error 时发 `review_failed` SSE，不走 review_completed。部分失败 + items=0 发 `review_degraded`。
> 来源：04-16 P0-1 漏洞 A

**R22 · 配额耗尽是专用异常类型**
`QuotaExhaustedError(APIError)` 带 `reset_hint` 字段，UI 展示"明天 8am 重置"。不混入 generic 失败。
> 来源：04-16 P0-3

**R23 · Timeout 留 buffer，不允许擦边**
WORKER_TIMEOUT 至少 = 实测 p99 + 30%。`TOTAL_TIMEOUT ≥ WORKER_TIMEOUT + GOSHAWK_TIMEOUT`，加 invariant 单测防配置回退。
> 来源：04-18 抢救 1，`test_config_env.py`

**R24 · Stagger 错峰发起**
4 Worker 各间隔 0.3s 起飞，避开瞬时并发触发 CLI 限流。
> 来源：be5fead

**R25 · 跨进程不共享 OAuth**
CLI OAuth token 多进程共享会被挤占刷新。shadow_run / cron 跑批时单进程独占，或给每个进程独立 token pool。
> 来源：SHADOW_RUN_FINDINGS round 15，401 auth 占 95%

**R26 · Circuit breaker + Retry chain**
失败分类：可重试（timeout/429）vs 不可重试（schema/quota）。retry chain 带指数退避（base=2s, max=60s）+ max 3 次；熔断 5 次连续失败触发。
> 来源：Phase G CC patterns `b1e1ce0`

---

## VI. 演进与防漂移

**R27 · 文件超 1900 行软触发 SPLIT，2000 行硬触发**
核心模块（parallel_review / goshawk_advisor / feedback）行数 CI 监控，软触发预警、硬触发 block merge。拆分用 facade 模式保持对外 import 零改动。
> 来源：04-18 抢救 3 + 5c8cd99 拆 parallel_review 1223→78 行

**R28 · 跨 env 常量用 AST 扫描防漂移**
`from config.base import *` 会让"某 env 缺符号"到 runtime 才暴露。AST 扫实际被 import 的符号，三 env 参数化测试强制通过。
> 来源：iteration round 5，GOSHAWK_TIMEOUT bug 真实踩坑

**R29 · 原子写 + 容错读**
所有状态 JSON（rule_perf / eval_history / goshawk_perf）：`.tmp + os.replace` 原子写；读取用 `.get(k, default)` + 降级 schema 容忍。
> 来源：iteration round 4 eval_history KeyError

**R30 · 老版本归档保留 + `?v=N` 回退通道**
v7 组件加 `@deprecated-v7` JSDoc 但不删，`/review?v=7` 可回访；设计 token 标记 `@deprecated-v7`。新问题出现能秒回退。
> 来源：UI v8 重做 `05f3af6`

**R31 · 历史噪音周期归档**
recent_window 把历史 bug 尾巴纳入会稀释不掉新数据。不健康 session 按指纹移到 `_archive/`，STATUS 重算。
> 来源：04-18 抢救 4，18 session 归档后 effective_consistency 20%→80%

**R32 · CI 三道 gate**
eval_gate（`EVAL_MIN_OVERALL_SCORE=0.50`）+ stability_gate（zero_rate / quota / failed_ratio 阈值）+ split_gate（行数监控）。
> 来源：v1.3.0 P1 + 04-16 stability_gate

---

## VII. 运维与 ops 边界

**R33 · ops 问题 ≠ bug，独立统计**
quota_exhausted / auth_expired / network_timeout 是 ops 信号，分类剔除后再算 effective_consistency。修代码解决不了 ops。
> 来源：STATUS 分层框架

**R34 · 安全围栏分层**
文件权限围栏（raw/prd 只读，wiki/output 可写）+ Bash 白名单 + 路径穿越防护 + Wiki 并发写锁。每加一个写操作工具必先过围栏。
> 来源：v1.0.0 + v1.1.0 P0 修命令注入

**R35 · 4 个端点最低 guard 不能漏**
review / audit / wiki / report 所有写端点强制登录 guard。内测前 P0 扫一遍：`556b597`。
> 来源：04-21 内测前 P0

**R36 · 配置同源化**
生产环境 `NEXT_PUBLIC_*` 别硬编码 localhost:8000，走同源 nginx / Cloudflare Tunnel path 分流。dev 才保留直连。
> 来源：04-21 Tunnel 内测阻塞 `7fc4603`

---

## 附录 · 关键实现映射

| 规则 | 关键文件 / commit |
|------|--------------------|
| R1 R2 R3 | `api/routes/review.py` + `goshawk_advisor.py` + `review/orchestration.py` |
| R4 | `agent_config.py` → `config/` MODEL_TIERS |
| R6 R7 | `api_adapter.py` + `review/worker.py:_is_empty_tool_submission` |
| R8 R9 | `review/evidence_verify.py` + `_verify_b_class_semantic` |
| R10 | `api/models.py:compute_signature` |
| R11 R12 R13 | `api/routes/review.py:_update_rule_perf_from_decisions` + `review/prompting.py:_build_feedback_section` |
| R14 | `goshawk_performance_history.json` + 苍鹰反向校验 |
| R15 R16 R17 R18 | `scripts/generate_status.py` + `STATUS.md` 自动生成 |
| R19 R20 | `api/routes/review.py` worker_done telemetry + `POST_FIX_CUTOFF_EPOCH` |
| R21 R22 | `api/routes/review.py:classify_worker_failures` + `exceptions.py:QuotaExhaustedError` |
| R23 | `config/dev.py` + `config/prod.py` + `tests/test_config_env.py` |
| R24 R25 R26 | `review/orchestration.py:_staggered` + circuit breaker (Phase G) |
| R27 | `tests/test_split_plan_trigger.py` + `docs/SPLIT_PLAN.md` |
| R28 R29 | AST 跨 env import 扫描 + `_atomic_write_json` |
| R30 R31 | `/review?v=7` + `scripts/archive_unhealthy_sessions.py` |
| R32 | `.github/workflows/eval.yml` 三 job |
| R33 | session classification framework |
| R34 R35 | `security.py` + `api/routes/*` 登录 guard |
| R36 | `web/lib/useReviewStream.ts` + `docker-compose.yml` |

---

## 引用来源清单

本 ruleset 综合自以下一手材料（项目内可追查）：

- `CHANGELOG.md` — v1.0.0 → v1.3.0 → Unreleased (2026-04-18/21) 所有变更
- `ARCHITECTURE.md` — 拓扑图 / Data Flow / Feedback Loop / Model Assignment
- `ITERATION_REPORT_2026_04_16.md` — 13 轮自主迭代 + 3 个 runtime bug
- `SHADOW_RUN_FINDINGS_2026_04_16.md` — 真机 shadow 20 次 + auth_401 新发现
- `SHADOW_20RUN_FINAL_2026_04_16.md` — Round 15 分层分类落地
- `docs/STABILITY_DIAGNOSIS.md` — 配额静默吞 P0 根因链
- `docs/ACTION_PLAN.md` — P0/P1/P2 + 长期机制
- `docs/RULE_PERF_CLEANUP.md` — 规则性能污染清洗
- `docs/STABILITY_REGRESSION_TESTS.md` — 稳定性回归测试定义
- `docs/SPLIT_PLAN.md` — 拆分触发条件
- memory 条目：`pecker_*.md` 全系列
