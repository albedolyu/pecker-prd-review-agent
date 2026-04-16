# Changelog

所有重要变更记录。格式遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)。

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
