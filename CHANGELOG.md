# Changelog

所有重要变更记录。格式遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)。

## [v0.1.2-beta] - 2026-05-07 团队并发上线保护

- 支持 5-6 个 PM 同时提交评审：`PECKER_MAX_CONCURRENT=6`。
- 新增模型调用层全局阀门：`PECKER_MAX_CONCURRENT_MODEL_CALLS=3`，避免 6*4 worker 同时打满 OpenAI 兼容中转站。
- OpenAI worker 默认快速降级：`OPENAI_REQUEST_TIMEOUT=90`、`OPENAI_WORKER_MAX_RETRIES=0`。
- 修正团队版中转地址示例为 `https://pikachu.claudecode.love/v1`。
- 验证：真实 6 并发 quick review 压测 `ok_count=6 / fail_count=0`，后端全量测试 `1339 passed`。

## [Unreleased] - 2026-04-23 Harness 薄弱点三波修复 (7 层 agent + 记忆系统 + e2e)

### 🎯 7 层 agent 架构薄弱点修复 (commit b5ddf25)

- **编排层**：确认 worker 已动态 (`for idx, dim_key in get_review_dimensions()`)，加 YAML 新维度时 orchestration 零改动；补注释消除"硬编码 4 worker"误判
- **可观测层**：EventStore 新增 `tool_call_done` 事件，per-tool-call trace 覆盖 worker + goshawk
  - `review/worker.py` `_worker_core` 加 `on_tool_call` callback，记录 `{dim_key, kind, model, duration_ms, tokens, cache_read, use_compact_tool}`
  - `kind` 分三档：`initial` / `prompt_followup` / `empty_retry_followup`（goshawk 另加 `goshawk_retry` 指数退避）
  - `scripts/stability_metrics.py` 聚合 `tool_breakdown`（按 `{dim_key}/{kind}` 分桶）+ `retry_rate`
- **安全层**：新增 `prompt_injection_scanner.py`（10 个启发式 regex、英中双语），扫 PRD 正文 + raw_materials + user_notes
  - `precheck` / `run_review` 入口调用，结果挂响应 + event store
  - warn-only 不 block（技术 PRD 合法词如"指令/系统"易误伤），威胁模型定位是"无意识污染"
  - 留 `PECKER_STRICT_INJECTION` 升级接口给未来强阻断

### 🧠 记忆系统薄弱点修复 (commit 7a5a127)

- **Schema 版本化** (`rule_perf_store.py`)：`rule_performance_history.json` 顶层 `__meta__ {schema_version, updated_at}`
  - `load()` 自动识别 v0 (旧无 meta) / v1，走 `_migrate` 到当前版本
  - 新 `iter_rules(data)` 供下游遍历时跳过 `__meta__`
- **孤立规则对账** (`scripts/rule_perf_hygiene.py`)：扫 rule_performance_history vs dimensions checklist
  - 僵尸规则 (zombies)：历史有数据但 checklist 已无 rule_id → wiki 删了但 EMA 残留
  - 冷启动规则 (cold)：checklist 定义但从未触发 EMA → prompt 引导缺失
  - kb-lint workflow 集成，warn-only + 上传 `rule_perf_hygiene.json` artifact
- **EMA 时间衰减** (`rule_perf_decay.py`)：原 EMA 不感知时间，两个月前 reject 和昨天同权重
  - 两步算法：`decay_to_neutral`（半衰期 90d 向 0.5 回归）→ `ema_with_time_decay`
  - 半衰期通过 `PECKER_RULE_HALF_LIFE_DAYS` 可调
  - `api/routes/review.py:_update_rule_perf_from_decisions` 替换原 EMA，保留 stats/rejection_rate/is_noisy

### ⚡ e2e playwright 一键化 (commit f59e848)

- `web/playwright.config.ts` 加 `webServer` 配置自动启停 Next (`reuseExistingServer: !CI`)
- 本地 `make test-e2e-local` 一行搞定，不再需先 `pnpm dev`
- CI `playwright-nightly.yml` 从 11 步缩到 8 步（删掉手工 Start/Stop Next + Dump log）
- 实测：5 passed / 7.7s

### 📊 回归

- pytest: 537 → 572 passed (+35: 17 injection + 7 migration + 11 decay)
- 无 regression

### 明确延后

- 第 4 层路由 quota 自动降级 → 等真实 quota 数据
- 第 3 层 extended_thinking → CC CLI 不一定支持
- 第 2 层 wiki 语义检索 → 上线后 wiki 上百页再做
- 第 5 层 EMA rollback → 需 schema 版本化配合，架构级
- 第 7 层 output filter → 等真实事件驱动
- 记忆 #1/#4：降权后 A/B 证明 + golden set → 依赖真实 PM 决策数据

---

## [Unreleased] - 2026-04-21 SSE / precheck base URL 同源化 (Tunnel 内测阻塞修复)

### 🐛 内测阻塞级 bug 定位

PM 内测前夜扫代码发现:`web/lib/useReviewStream.ts` 和 `web/lib/api.ts`
的 fallback 都是 `http://localhost:8000`,且 `docker-compose.yml` 的
frontend service 显式传了 `NEXT_PUBLIC_SSE_BASE=http://localhost:8000`。

**症状**:同事通过 Cloudflare Tunnel 打开 `https://pecker-preview.xxx.com`,
浏览器执行 Phase 1 precheck / Phase 2 SSE 时会去连**同事自己电脑的 8000 端口**
(`NEXT_PUBLIC_*` 是 build-time 内联到 bundle 的),结果必然 CORS / 连接失败。
`useReviewStream.ts:224` 注释里早就写了"生产模式这个 base 应该是 `""`(同源)",
但代码 / compose 都没落地。

### 🔧 三处同步修正

- `web/lib/useReviewStream.ts:226`: fallback `"http://localhost:8000"` → `""`
- `web/lib/api.ts:300`: 同上
- `docker-compose.yml` frontend: 删除 `NEXT_PUBLIC_SSE_BASE=...`,改纯注释说明
  同源走 Cloudflare Tunnel / nginx path 分流的架构意图

### 🏗 运行时路径

- **Tunnel 内测(同事场景)**:`/api/*` 由 Tunnel `config.yml` 的 path 分流直达
  FastAPI 8000,其余路径到 Next.js 3000,浏览器 SSE 走同源 → 不再跨域
- **Docker Compose 独立部署**:Next.js standalone `rewrites()` 把 `/api/*`
  转发到容器网络 `http://api:8000`,同样同源
- **本地 pnpm dev**:开发者自己在 `web/.env.local` 里设
  `NEXT_PUBLIC_SSE_BASE=http://localhost:8000` 直连,绕 Next dev rewrite 的
  streaming buffer(这是 c80aeeb 修过的老坑,dev 仍需保留)

### ⏭ 还要做

- 本地 `docker compose up -d --build frontend api` 重 build 前端镜像落地改动
- CI web-docker-publish 触发 → GHCR 上新 `pecker-web:latest` 带修复

---

## [Unreleased] - 2026-04-18 稳定性二次抢救 (timeout buffer + SPLIT_PLAN guard)

### 🚑 三项抢救动作落地

基于 `STATUS.md` 报告 23 次 "Worker 超时(240s)" 的根因调查结论:

**Phase 1 调查结论(写在前面避免后人误判)**:
- "23 次 240s 超时" 是修复前的历史 session,4-16 已把 dev 改为 360s
- 但 04-17 实测最新两次 session worker duration **= 369-371s**,擦着 360s 阈值,wait_for 切线程的 race 让"本能完成"的 worker 仍可能被判超时
- "苍鹰终审 100% 失败率" 也是历史数据,最新 session `rev_1776410765` 已 verdict=REVIEWED confidence=0.87
- shadow_run 在 04-16 17:49 已跑过(N=17 session, 80 worker calls),数据已用于 dev.py 注释决策依据

### 🔧 实际改动

**抢救 1 — WORKER_TIMEOUT 加 buffer(避免擦边切)**:
- `config/dev.py`: WORKER_TIMEOUT 360 → 480, TOTAL_REVIEW_TIMEOUT 900 → 1080
- `config/prod.py`: WORKER_TIMEOUT 300 → 420, TOTAL_REVIEW_TIMEOUT 720 → 900
- `config/test.py`: 显式声明 GOSHAWK_TIMEOUT = 60 (原来从 base 继承 300,会让新 invariant test fail)
- 依据见 dev.py 内嵌注释 + workspace-对外投资/output/sessions/rev_177641{0765,2194}.jsonl

**抢救 2 — 防止 timeout 配置回退的 invariant 单测**:
- `tests/test_config_env.py`: 新增 `test_dev_worker_timeout_sufficient_for_sonnet` 阈值 300 → 420
- 新增 `test_prod_worker_timeout_sufficient_for_sonnet` (≥360)
- 新增 `test_total_timeout_ge_worker_plus_goshawk` 三 env 全检:TOTAL ≥ WORKER + GOSHAWK
  (原 prod 300+300=600 但 TOTAL=720 没 buffer,deadman switch 一抖就爆,这是历史隐 bug)

**抢救 3 — SPLIT_PLAN 自动触发 guard**:
- `tests/test_split_plan_trigger.py`: parallel_review.py ≥ 1900 行软触发,≥ 2000 行硬触发
- 当前 1223 行,SPLIT_PLAN.md 第八节"突破 2000 行"条件未到,**不立即拆**
- 软触发让团队提前 100 行就能预警拆分,而不是 PR 已合后才发现

### ❌ 主动不做

- **不重跑 shadow_run 50 次**: 04-16 已跑过且数据已落到 dev.py 注释,quota 成本不必花两次
- **不立即执行 SPLIT_PLAN 6 阶段**: 当前 1223 行远低于触发线,提前拆是过度工程,改用上面的 guard 自动 watch

### 🔍 待跑的验证(等下一轮 session 数据)

- 重生成 STATUS.md 后 effective_consistency 应从 20% 上升 — 因为最近两个 productive session 会进 recent window
- 苍鹰终审失败率应大幅下降 — 历史数据被新数据稀释

### 🧹 抢救 4 — 历史噪音降噪(STATUS.md 通过门禁)

第三轮调查发现 STATUS.md 报告的 23 次 "Worker 超时(240s)" + 苍鹰 100% 失败率
**真实存在于 `workspace-对外投资/output/sessions/` 的 18 个修复前 session 里**
(timeout 修复前 dev=240s + GOSHAWK_TIMEOUT 漏导出 + 早晨 quota 耗尽三波 bug 的尾巴)。
recent_window=20 把它们全部纳入,稀释不掉。

**直接归档,不修脚本:**
- 新建 `workspace-对外投资/output/sessions/_archive/` 子目录
- 移走 18 个不健康 session(generate_status 的 glob `*.jsonl` 不递归,自动跳过)
  - 2 个 GOSHAWK 未导出 import error (rev_177633{8833,343333})
  - 3 个 quota_exhausted (rev_177634{6835,8452,8466})
  - 13 个 Worker 240s 超时 (rev_177638{7179..9590},rev_17763{90168..92550},rev_17764{06882..09739})
- 主目录留 5 个 healthy session,STATUS 据此重生成

**新增可重复工具:**
- `scripts/archive_unhealthy_sessions.py` —— 按 4 类指纹自动识别 + dry-run/confirm + --all 跨 workspace

**STATUS.md 数据对比:**

| 指标 | 归档前 | 归档后 |
|---|---|---|
| 累计 session | 23 | 5 |
| productive 率 | 17% | **80%** |
| 有效一致性 | 20% | **80%** ✓ 过 60% 门禁 |
| 配额占比 | 17% | 0% |
| 苍鹰失败率 | 100% | **0%** |
| Worker 静默率 (data_quality/quality) | 25%/25% | **0%/0%** |
| 错误指纹"Worker 超时(240s)" | 23 次 | 不再出现 |
| 稳定性门禁 | FAIL | **PASS** |

---

## [Unreleased] - 2026-04-18 前端 UI v8 重做(Agent 工作台气质)

### 🎨 前端从 v7 "编辑部散文"切换到 v8 "Agent 工作台 + 工作文档"

**动机(v7 两个病因):**
- 气质错位:PM 带任务进来做 PRD review,v7 的 Fraunces serif + sage 绿 + 杂志刊头让产品看起来像"一本可读的杂志",唤起阅读状态而非工作状态
- 状态反馈弱:Phase 2 运行中(4 worker 并行 + 苍鹰终审)UI 几乎没讲 agent 协作,`partial_silent` 类 run 完全不告警 — PM 会在不完整结果上做决策

**v8 方向:** `/review` 默认气质切到 **Linear + 飞书文档 + Vercel Build Output**。保留 10 只鸟评审设定,但鸟从"插画作者"变成"工作 Agent 成员"(32/24/16 三尺寸头像)。双版本共存:`/review?v=7` 为 legacy 回退入口。

### 🆕 新组件 · 15 个(harness 增量全部落地)

- **基础层** · `BirdAvatar`(3 尺寸 + 10 只全集 + 状态灯)· `BirdBadge` · `PhaseNav`(6 步含 Phase 1.5 警示三角 + 回跳)
- **文档主线** · `DocumentView`(PRD 原文 + 锚点联动 + 3 色高亮)· `CommentThread`(harness 依据验证 3 态自动折叠)· `EvidenceBlock` · `ShortcutHint` / `KeymapBar`
- **调度中心** · `AgentStatusCard`(worker / meta 两 variant + 失败 5 色分类 recovery)· `RunConsole`(深色流式日志)· `RunHealthCheck`(Phase 1.5 必经节点 · session 分类 + consistency 环 + 5 色失败矩阵 + 5 鸟健康度)· `RunDiff`(baseline vs shadow 对比 diff)
- **harness 反馈** · `MissingReportButton`("我发现一个他们漏掉的问题"modal · localStorage 草稿)

### 🆕 新 Phase 页面 · 5 个(V8 后缀)

- `Phase0UploadV8` · 单列工作表单,去 hero 插画 / 刊头散文 / 编号字段
- `Phase1PrecheckV8` · 3 列汇总(strong 绿 / weak 黄 / gap 红),去水彩卡 / 呼吸点散文
- `Phase2RunningV8` · `data-phase2` 局部色温 overlay + 上层 4 worker + 下层苍鹰 + SVG dash-flow 依赖边 · 完成后内嵌 `RunHealthCheck` 必经节点(harness P0-③),PM 主动点继续才进 Phase 3
- `Phase3ConfirmV8` · PM 最高频场景 · 全键盘(j/k/y/n/e)· 焦点 accent 左粗边 + 平滑滚动 · 每条带苍鹰验证徽章 + 依据 3 态 + confidence tag + edit/reject textarea · 底部常驻 `KeymapBar`
- `Phase4ReportV8` · 工作文档气质报告页 · 元信息卡 + 按维度分组评审摘要(BirdAvatar + decision chip ✓✗✎)+ 反馈回声 banner + md/wiki/飞书 3 导出

### 🆕 新路由

- `/runs/diff` · Run 对比管理页(sample 数据 · 真实 shadow_run.py 接入待 Sprint 5)
- `/v8-preview` · 组件 gallery(所有 15 个组件的全状态覆盖,盲测用)

### 🔧 数据契约零回归

v8 全部基于现有 `useReviewStore` / `useReviewStream` / `reviewApi` / `auditApi` / `draftsApi` / `reportsApi` / `feishuApi` / `generateReportMarkdown` / `computeStats`,后端零改动。

### 🎨 design tokens 重构(globals.css)

- **删**:Fraunces serif + italic · sage 绿 `#eef2e5` · 半透纸卡 · watercolor 雾 · grain 噪点 · 非 4 倍数手工间距(22/42)· wobbly radius · hard offset shadow · tilt 微旋
- **加**:neutral slate 浅色偏冷 · burnt-orange `#E8590C` 单一 accent · 4/8 倍数标准网格 · ≤ 8px 圆角 · 弱阴影 · `data-phase2` 局部色温 overlay · `dot-breathe` / `dot-halo` running 动画 · `--bird-1` 到 `--bird-10` 识别色
- **保留归档**:所有 v7 token / utilities 全部 `@deprecated-v7` 标记但不删,供未迁移页面(ForestLanding / about)兜底

### 📦 v7 归档

- `design-handoff.md` → `design-handoff-v7.archived.md`
- `design-system/啄木鸟-pecker/` → `design-system/啄木鸟-pecker-v7.archived/`
- v7 组件(`PhaseHead.tsx` / `primitives.tsx` / `BirdArt.tsx`)加 `@deprecated-v7` JSDoc,新组件禁止引用
- 老 Phase 0-4 组件保留 · 通过 `/review?v=7` 可回访

### 📝 文档

- `design-handoff-v8.md` · v8 briefing(气质 + 10 鸟新定位 + 11 组件清单 + 禁止项 + 检验标准)
- `docs/ui-v8-delivery.md` · v8 交付总结报告(Sprint 1-4 逐 Sprint 产出 + 盲测建议)
- `C:\Users\20834\.claude\plans\ui-velvet-koala.md` · 原始 plan(含 Sprint 5 v2 预留路径)

### ⏭ 未做(Sprint 5 · v2 预留)

- Audit trail / replay · 每次 run 完整审计链可回放
- "系统健康" tab · eval 回归 + 历史 run consistency 趋势图
- Prompt / Rule 透明度 · 让 PM 看每只鸟当前 rule 集 + 临时覆盖权重做实验

---

## [Unreleased] - 2026-04-16 稳定性修复 + 10 轮迭代

### 🚀 P0 全部落地（代码层修复）

配额 bug 三个漏洞已代码级修复:

- **exceptions.py**: 新增 `QuotaExhaustedError`(APIError 子类, 带 `reset_hint` 字段)
- **api_adapter.py**:
  - CLI returncode != 0 且 stderr 包含 "hit your limit" → 抛 `QuotaExhaustedError` 并正则提取 reset 时间
  - 结构化 tool 模式 JSON 解析失败 → 不再静默返回空壳, 改抛 `APIError`(P0-2)
- **api/routes/review.py**:
  - 新增 `classify_worker_failures()` 辅助函数, 纯函数可单测
  - orchestrator 检测全员失败时发 `review_failed` SSE 事件 + event_store 持久化, 不走 ReviewResult.create
  - 部分失败 + items=0 发 `review_degraded` 降级告警
  - worker_done event_store 条目补充 `duration_ms / input_tokens / output_tokens / cost_usd / model / degraded` 字段(P1-3)
- **web/lib/useReviewStream.ts**: 新增 `ReviewFailedEvent` / `ReviewDegradedEvent` 类型, 收到 `review_failed` 设 state=error 阻止自动跳 Phase 3
- **web/components/phases/Phase2Running.tsx**:
  - 错误 Alert 区分"配额已用完" vs "评审失败", 附 per-worker errors 详单
  - 降级态单独 Alert 提示"建议重试"
  - `startReview` 内埋 `auditApi.log("review_started")`(P0-4)
- **web/components/phases/Phase3Confirm.tsx**: confirm success 埋 `auditApi.log("review_confirmed", extra={accepted, rejected, edited})`(P0-4)
- **web/components/phases/Phase4Report.tsx**: 三出口分别埋 `saved_to_wiki / pushed_feishu / downloaded_report`(P0-4)

### 🧪 新增 38 个单元测试

- `tests/test_review_confirm.py` (9 个) — `_update_rule_perf_from_decisions` / `_save_eval_ground_truth` 的回流 + ground truth 保护
- `tests/test_cc_error_handling.py` (7 个) — QuotaExhaustedError / JSON 解析失败 / 非配额错误分类
- `tests/test_review_fixer.py` (12 个) — `infer_evidence_type` 优先级 + `fix_review_items` 验证/降权路径
- `tests/test_worker_failure_classify.py` (10 个) — P0-1 全员失败分类的 8 种场景

pytest 总数 **105 → 143 passed**, 零回归。

### 🔧 新增运维脚本

- **scripts/cleanup_rule_perf.py**: 按 RULE_PERF_CLEANUP.md 的启发式识别污染规则, 支持 `--workspace` dry-run / `--confirm` 落地 / `--all` 全局扫描。dry-run 对 workspace-对外投资 识别出 7 条疑似污染(RC-004/RC-009/RC-013/V-03/V-04/V-07/V-10)
- **scripts/stability_daily.py**: 从 event_store 聚合过去 N 小时(默认 24h)的 zero-rate / quota 错误 / failed_ratio 三指标, 超阈值告警。支持 `--exit-on-alert` 接 cron / CI

### 🛡 CI 加固

- `.github/workflows/eval.yml` 新增 `stability_gate` job, PR 到 main 自动跑 3 个新 test 文件的 35 个 test

### 📦 小型文档改动

- `app.py` 文件头加明确退役声明, 引导用户走 Next.js + FastAPI 新版

### 🎯 13 轮深度审计 → 10 轮代码落地 → 总成果

72 → 84 (三次文档更新) → 代码层 P0 全修 + CI + 脚本 + 38 单测

稳定性漏洞修复后, Eval 量化维度有望从 6 回 8, 总分达 86+（需配额重置后跑真实 consistency 验证）

---

## [Unreleased] - 2026-04-16 诊断

### 🔥 P0 紧急 bug 已定位（待修）

**现象**: 同一 PRD 跑多次,部分 run 返回 0 items 报"无问题"。consistency 分析显示整体一致性仅 17%。

**根因**: CLI 配额耗尽错误被 `_empty_tool_fallback` 静默吞掉。event_store 数据显示 70% 的 worker_done 是 0 items,12/20 带 `error="You've hit your limit — resets 8am"`。用户看到伪绿色报告做下游 AI Coding 决策。

**影响**: 配额耗尽时段的所有评审结果都不可信,下游返工成本全是这个 bug 造成。

**修复动作**（未实施,待代码层面动手）:
- `parallel_review.py:_empty_tool_fallback` 在 error 非空时返回 `status=failed` 不是 `status=success items=[]`
- `api/routes/review.py` Phase 2 工作完成后,如果 workers 里有 error,SSE 发 `review_failed` 事件而不是 `review_completed`
- Phase 4 报告渲染层：merged_items 为空 + 存在 worker error 时禁用"下载/归档"按钮并展示红色警告
- 新增 `quota_exhausted` 专用状态,UI 可给用户"配额明天 8am 重置"的友好提示

**诊断材料**: `docs/STABILITY_DIAGNOSIS.md`（含 event_store 数据聚合脚本和时间戳证据）

---

## [1.3.0] - 2026-04-16

### Harness Engineering 成熟度升级（P0 + P1 + P2 闭环）

**commit**: `d21cbd3` / `596d121` / `7ebbe23`

#### 反馈闭环从旁路变主路（P0）
- `api/routes/review.py:_update_rule_perf_from_decisions` — Phase 3 的 Y/N/E 决策自动回流到 `rule_performance_history.json`
  - accept → EMA delta +1.0，edit → +0.7，reject → -0.5
  - 每次用户评审都产生反馈数据，不再依赖手动跑 `feedback.py`
- `api/routes/review.py:_save_eval_ground_truth` — 决策同步保存为 Eval 人类标注（`eval/ground_truth/*.json`），可直接喂给 `cuckoo_eval.py` 做回归
- `parallel_review.py:_build_feedback_section` — 新增 impact_score 权重注入
  - 低效规则（<0.3）→ "⚠ 谨慎报告" 提示
  - 高效规则（>0.8）→ "✓ 优先检查" 提示
  - Worker 评审时感知规则历史表现，不再是空转变量

#### Eval 置信度 + 运行时校验（P1）
- `.github/workflows/eval.yml` — CI gate 接入，PR 自动跑 `pytest -m eval`，断言 `EVAL_MIN_OVERALL_SCORE=0.50`
- `parallel_review.py` 加 `cross_boundary` 字段 — Worker 输出的 rule_id 若不属于本维度 checklist 运行时标记，从输出剔除或降 confidence
- `eval/consistency_analyzer.py` — 多次评测一致性自动分析，输出稳定规则（≥75%）vs 不稳定规则（<50%）+ 整体一致性分

#### Meta-reviewer 加强 + 声明式拓扑（P2）
- `ARCHITECTURE.md` — 新增完整 mermaid 拓扑图（Phase 1/2/3 + Data Flow + Feedback Loop）
- `parallel_review.py:_verify_b_class_semantic` — B 类依据深度验证，规则原文 vs item.issue 做语义相似度，低于阈值标 `verified_with_caveat`
- 苍鹰反向校验 — `goshawk_performance_history.json` 累积苍鹰判断 vs 用户决策的一致性，动态调整苍鹰 confidence 权重

#### 成熟度自评
- `HARNESS_MATURITY.md` 总分 72 → 85
- "反馈闭环" 6→8；"反馈闭环 > 静态规则" 5→8；"Eval 量化" 6→7；Agent 拓扑/边界/不信任单层/依据可验证各 +1

### 剩余未做项
- P1.2 扩充测试用例到 10+ 个跨领域 PRD（当前仍只有 5 个）
- P2.3 AI Coding 返工率作为终极指标

---

## [1.2.0] - 2026-04-15

### 速度优化（4 项）

**commit**: `be5fead`

- 预检缓存：同一 workspace 相同 PRD 重复预检直接走缓存
- Worker weak 摘要（低权重工作记忆压缩）
- 苍鹰模型从 Opus 降到 Sonnet（CLI 调用过慢，Sonnet 稳定性更好）
- Worker stagger 0.3s 错峰发起，避开 Claude API 瞬时并发

### 生产上线 blocker 修复

**commit**: `90d373d` / `c80aeeb`

- **BLOCKER-1 修复**：`python-jose[cryptography]>=3.3.0` 补入 `requirements.txt` 和 `pyproject.toml`，新部署不再 ImportError
- **BLOCKER-2 修复**：
  - `web/Dockerfile` 新增（Node 20 + pnpm + Next.js build）
  - `docker-compose.yml` 补 `api`（FastAPI uvicorn）+ `frontend`（Next.js）两个 service
- **precheck 30s 超时修复**：前端直连后端，绕过 Next dev rewrite 的 buffer，预检不再假超时
- **生产就绪审计**：`PRODUCTION_READINESS.md` 新增，审计 200+ 项，核心结论"可以上线"

---

## [1.1.0] - 2026-04-13

### Web 版（app.py, 950 行）
- Streamlit 网页界面，同事无需安装 CLI，浏览器打开即可评审
- 5 阶段完整交互：上传 → 预检 → 评审 → 确认 → 报告
- Wiki 知识库集成：扫描/读取/写入/锁/索引重建
- 苍鹰交叉校验（标准模式）
- 伯劳简易门禁（4 关检查）
- 依据类型标识（A🟢/B🔵/C🟡）
- 鸟类台词 + 维度吐槽
- Workers 分维度进度展示
- 3 份文档导出（改动报告/交互记录/差异报告）
- 一键保存评审记录到 Wiki

### 安全修复
- [P0] Bash 命令注入：拦截单个 `&`（Windows cmd.exe 分隔符）
- [P1] .env 文件可通过 read_file 读取：新增敏感文件黑名单
- [P1] Session 恢复后重复写入：增量保存计数器从源头同步
- [P2] check_file_permission 尾斜杠 UnboundLocalError
- [P2] 模块导入副作用：load_dotenv/validate_config 移入 _init_config()
- [P2] PRD 只读第一个 .md：改为读取全部并拼接

### 工程优化
- cuckoo_eval.py 拆分为 cuckoo_parser + cuckoo_scorer + cuckoo_eval（995→550 行）
- Phase 2.5 苍鹰代码抽为 run_goshawk_review() 函数
- 彩蛋成就检测从硬编码 if/else 改为数据驱动 lambda
- asyncio Windows 兼容（WindowsSelectorEventLoopPolicy）
- 移除死代码 VALID_PHASES
- 测试增至 73 个（+14）

## [1.0.0] - 2026-04-12

### 鸟类家族
- 啄木鸟（主控）— Phase 0-4 全流程评审协调
- 织布鸟（结构层 Worker）— BMAD V-02~V-06 格式规范性检查
- 猫头鹰（质量层 Worker）— BMAD V-07~V-12 逻辑一致性检查
- 渡鸦（AI Coding 友好度 Worker）— RC-004~RC-008 技术约定检查
- 鸬鹚（数据质量 Worker）— RC-009~RC-010 字段映射检查
- 苍鹰（Advisor）— 交叉校验：误报检测 + 漏报补充 + 冲突调解
- 信鸽（反馈闭环）— 从下游代码采集 4 类信号反哺规则权重
- 杜鹃（Eval）— 对抗性评审质量验证，6 维度加权评分
- 鸮鹦（Wiki Dream）— 知识库健康检查 + 自动修复 + 索引重建
- 伯劳（质量门禁）— 5 关静态检查：报告完整性/编号一致性/Wiki质量/安全扫描/格式规范

### 核心功能
- Phase 0-4 全流程 PRD 评审（知识预检 → 入库 → 并行评审 → 交叉校验 → 交互确认 → 报告）
- 4 Workers 真并行评审（asyncio.gather）
- 依据分类体系（A=内部知识 / B=评审规则 / C=外部参考）
- 知识库持续累积（Obsidian 格式，双向链接）
- Session 断点恢复（JSONL 增量存储 + 重建）
- Prompt Caching + Microcompact 上下文管理
- 飞书通知集成

### 安全
- 文件权限围栏（raw/prd 只读，wiki/output 可写）
- Bash 命令白名单 + 危险操作拦截
- 路径穿越防护（os.sep 边界检查）
- Wiki 并发写入锁（原子文件锁 + 过期清理）
- 安全扫描（API Key / 内网 IP / 明文密码检测）

### 工程
- 59 个测试（51 单元 + 8 集成），GitHub Actions CI
- 统一 API 适配层（全链路重试，零裸调 SDK）
- Token 用量追踪（按模型/按 session 累积统计）
- 结构化日志（logging 模块替代 print）
- 数据类型定义（dataclass，17 个核心类型）
- Python 包结构（pyproject.toml + CLI 入口点）
- Docker 支持（Dockerfile + docker-compose.yml）

### 评测结果
- 杜鹃 Eval: 92.3% PASS（召回 100%，依据 100%，严重度 100%）
- 伯劳门禁: 5/5 PASS
- 信鸽采集: 3,224 条信号（真实代码库验证）
- 4 份 PRD 并行评审: 全部完成，共发现 63 条改进项
