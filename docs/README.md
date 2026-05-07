# docs/ — 工程文档目录

本目录保存开发期间产出的深度分析、规划、诊断文档。和根目录的轻量文档（README、CHANGELOG、DEV.md、产品介绍等）区分开。

## 最近变化 (2026-04-23)

- 代码层面 7 层 agent 架构三项薄弱修复 + 记忆系统三项薄弱修复 + e2e 一键化（见 [../CHANGELOG.md](../CHANGELOG.md) 顶部 04-23 条目）
- ARCHITECTURE.md 对应补了：Phase 1 的 injection scan、Feedback Loop 的 EMA + time decay、File Mapping 新模块、新增 Event Store Schema 小节

## 目录

### 主干（常读）

| 文档 | 类型 | 描述 |
|---|---|---|
| **[ACTION_PLAN.md](ACTION_PLAN.md)** | **主行动计划** | **13 轮审计汇总，按 P0/P1/P2 排序的全部待办 + 长期机制 + 执行顺序建议** ⭐ |
| [HARNESS_RULES.md](HARNESS_RULES.md) | Harness 工程规则集 | 从 73 commits 沉淀的 Top 10 原则 + 36 条细则，指导后续 agent 架构演化 |
| [../ARCHITECTURE.md](../ARCHITECTURE.md) | 系统架构 | 拓扑图 / Data Flow / Feedback Loop / Event Store Schema / File Mapping |

### 稳定性（P0 诊断链）

| 文档 | 类型 | 描述 |
|---|---|---|
| [STABILITY_DIAGNOSIS.md](STABILITY_DIAGNOSIS.md) | 诊断 | 2026-04-16 定位的 3 个 P0 稳定性漏洞（全员失败不 abort + JSON 解析静默吞 + 审计链路断），含 event_store 数据、根因链、补丁方案 |
| [STABILITY_REGRESSION_TESTS.md](STABILITY_REGRESSION_TESTS.md) | 测试规划 | 针对 STABILITY_DIAGNOSIS 的 6 个回归 test + CI 集成 + 验收 checklist + 长期监控脚本设计 |
| [RULE_PERF_CLEANUP.md](RULE_PERF_CLEANUP.md) | 数据清洗 | workspace-对外投资 的 rule_performance_history 15 条规则诊断，7 条疑似污染的清洗脚本规格 + 防污染机制 |
| [SPLIT_PLAN.md](SPLIT_PLAN.md) | 重构规划（✅ 2026-04-19 已实施） | `parallel_review.py`（1223 → 78 行 facade）按职责拆 6 模块完成：`review/{dimensions,prompting,worker,orchestration,evidence_verify,aggregation}.py`，对外 import 零改动 |

### 规则演进 · 实测留档

| 文档 | 类型 | 描述 |
|---|---|---|
| [RC-009_NEW_RULE_EFFECT.md](RC-009_NEW_RULE_EFFECT.md) | 规则升级 A/B 实测 | RC-009 从"字段映射一致性"扩到"物理表定义完整性"，风鸟诉前调解 PRD 实测命中 +70% / 0% 假阳性 |

### 交付 / 部署 / PM

| 文档 | 类型 | 描述 |
|---|---|---|
| [ui-v8-delivery.md](ui-v8-delivery.md) | 前端交付 | Web UI v8 设计交付（对应根目录 `design-handoff-v8.md`） |
| [dev-setup.md](dev-setup.md) | 开发环境指南 | make 启动 + 5 大常见坑（next proxy socket hang up / Windows Playwright spawn / 登录 401 / SSE 断连 / Claude CLI 未登录）+ 全链路 curl 验证 |
| [../DEPLOYMENT_CHECKLIST.md](../DEPLOYMENT_CHECKLIST.md) | 团队 Beta 上线清单 | OpenAI API key / 并发 / 预算 / 降级 / secret / on-call / 备份 |
| [deployment.md](deployment.md) | 旧版部署指南 | v8 预览期 Docker Compose / GHCR / Vercel 路径,已由团队上线清单接管 |
| [cloudflare-tunnel-setup.md](cloudflare-tunnel-setup.md) | Tunnel 配置 | `pecker-preview.*` 同源路径分流，PM 内测用 |
| [pm-preview-guide.md](pm-preview-guide.md) | PM 内测指南 | 给非工程 PM 的登录 / 跑 review / 反馈流程 |
| [feishu_integration.md](feishu_integration.md) | 飞书机器人接入 | 创建机器人 → URL 配置 → verify token → smoke test 全流程 |
| [v1_vs_v2_feedback_strategy.md](v1_vs_v2_feedback_strategy.md) | 反馈系统策略 | 信鸽 v1 (commit 隐式) vs v2 (PM 显式) 共存策略 + v1 退役 trigger |
| [../scripts/CI_self_hosted_setup.md](../scripts/CI_self_hosted_setup.md) | Self-hosted runner 操作手册 | 真实 worker P/R 回归 CI gate 部署 (Win + Linux) + fallback 模式 |

### Quickstart (新机器接入啄木鸟开发)

```bash
# 1. 装 pre-push hook (本地 P/R 回归兜底)
python scripts/install_git_hooks.py

# 2. 想跑 self-hosted runner CI? (可选)
bash scripts/setup_runner_linux.sh    # 或 Windows: powershell -File scripts\setup_runner_windows.ps1

# 3. 没装 runner 时, 提 PR 前手动跑一份报告
python scripts/manual_pre_pr_check.py --output pr_check_report.md
# 把内容贴到 PR description 作为 review 证据
```

### 归档

| 文档 | 类型 | 描述 |
|---|---|---|
| [archive/](archive/) | 已闭环诊断 | `ITERATION_REPORT_2026_04_16.md`、`SHADOW_*` 等 04-16 单日迭代产出，P0 修复已入主干 |
| [research/](research/) | 研究归档 | Claude Code v2.1.107 源码逆向的 3 轮研究报告（已落地到代码） |

## 工作流约定

- **主代码改动前先读对应诊断/规划**：改 `review/` 子包（worker/prompting/orchestration）前读 `ARCHITECTURE.md` File Mapping 定位；改 worker 错误处理前读 `STABILITY_DIAGNOSIS.md`
- **诊断文档不能让它"烂"**：定位的根因修掉后，诊断文档要补 "✅ 已修复 commit XXX"，否则下次又会被误读成仍存在的问题
- **归档到 research/ 或 archive/ 的触发条件**：研究笔记对应的代码改动入库后，顺手移到 `research/`（源码研究）或 `archive/`（单日诊断），并在对应 `README.md` 登记
- **诊断文档的生命周期**：发现 → 写诊断 → 修复 → 标注已修复 → 保留 1-2 版本后移入 archive/
- **docs 漂移预警**：每次有 `feat:` / `refactor:` commit 改到架构层（agent / 事件 / 记忆）都要回查 ARCHITECTURE / CHANGELOG / ACTION_PLAN 三件套是否需要同步
