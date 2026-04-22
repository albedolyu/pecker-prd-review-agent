# 啄木鸟 — 综合行动计划（2026-04-16 全盘审计后）

> **快照注记 (2026-04-22)**: 本计划为 04-16 排序，P0 四项已全部代码级落地 (commits 784df10 / 99a8424 / b478df6 / 3540788)。当前稳定性现状请参见 [../STATUS.md](../STATUS.md)。
>
> 这是 13 轮自主迭代审计的汇总行动清单，对跨散落的 5 份诊断/规划文档做聚合排序。
> 每一项标注：紧迫度、工作量、依赖关系、落地文件。
> 按此顺序执行能最小化来回改、最大化增量验证价值。

---

## 一、P0 紧急（本周做完，共 ~1.6 天）

这 4 项修完,系统从"看起来能用"真正变成"能用"。

### P0-1 「全员失败 abort」规则（漏洞 A）
- **工作量**: 0.3 天
- **改动**: `api/routes/review.py` Phase 2 完成后检查 worker 失败数,全失败发 `review_failed` SSE,Web UI 监听 `review_failed` 不自动跳 Phase 3
- **依赖**: 无
- **验证**: STABILITY_REGRESSION_TESTS.md Test 1

### P0-2 CLI JSON 解析失败抛 APIError（漏洞 B）
- **工作量**: 0.2 天
- **改动**: `api_adapter.py:594` 从"返回空壳"改为 `raise APIError`
- **依赖**: 无
- **验证**: STABILITY_REGRESSION_TESTS.md Test 3

### P0-3 QuotaExhaustedError 专用异常类型（漏洞 A UX）
- **工作量**: 0.3 天
- **改动**: `exceptions.py` 加 `QuotaExhaustedError`,`api_adapter.py:558` 分类抛错,Web UI 显示友好提示
- **依赖**: P0-1 完成（走同一上报链路）
- **验证**: STABILITY_REGRESSION_TESTS.md Test 4

### P0-4 审计链路接通（漏洞 C）
- **工作量**: 0.5 天
- **改动**: 4 个前端 Phase 组件加 `auditApi.log()` 调用:
  - Phase0Upload 上传后 → `review_started`
  - Phase3Confirm 确认后 → `review_confirmed`
  - Phase4Report 三出口 → `saved_to_wiki` / `pushed_feishu` / `downloaded_report`
- **依赖**: 无
- **验证**: STABILITY_REGRESSION_TESTS.md Test 5 + 手动跑一遍 Web 流程后 grep logs/user_actions.jsonl

### P0-5 `.env.example` 已补（本轮已做）
- ✅ 完成。补全 `PECKER_SIGNATURE_SECRET` / `PECKER_JWT_SECRET` / `PECKER_WEB_PASSWORD` 等 15 个必需/可选变量

---

## 二、P1 高优（两周内,共 ~4 天）

P0 修完后稳定性真正好转,再做这批。

### P1-1 rule_performance_history 污染清洗
- **工作量**: 0.5 天
- **改动**: 按 `docs/RULE_PERF_CLEANUP.md` 方案,写 `scripts/cleanup_rule_perf.py`
- **依赖**: P0-1 P0-2 完成后,先跑 dry-run 确认,再 --confirm
- **对象**: workspace-对外投资 的 15 条规则中 7 条疑似污染

### P1-2 扩充测试用例到 5 个跨领域
- **工作量**: 2 天
- **改动**: 用 `cuckoo_eval.py --generate-test-case` 生成 SaaS/电商/金融/企业信息/教育 各 1 个
- **依赖**: 需要你收集 5 份真实 PRD
- **收益**: Eval 置信度从 6 → 8

### P1-3 event_store 补 telemetry 字段
- **工作量**: 0.2 天
- **改动**: `api/routes/review.py:237-241` 的 `evt.append("worker_done", {...})` 补充 `telemetry` 字段（duration_ms / tokens / cost / model）
- **依赖**: 无
- **收益**: 可做成本分析 + 性能回归

### P1-4 CI stability_gate job
- **工作量**: 0.3 天
- **改动**: `.github/workflows/eval.yml` 加 stability_gate job 跑 `test_worker_failure_handling.py`
- **依赖**: P0-1 P0-2 P0-3 完成后 test 才有意义
- **收益**: 稳定性护栏通电

### P1-5 重跑劳动仲裁 3 次 consistency 验证
- **工作量**: 0.3 天(等 Claude 跑)
- **改动**: 配额重置后 `python eval/consistency_eval.py --prd workspace-劳动仲裁/... --rounds 3`
- **依赖**: P0 全部完成
- **验收阈值**: 整体一致性分 ≥ 50%,零 items run ≤ 10%

### P1-6 review_memory / review_fixer 单测
- **工作量**: 0.5 天
- **改动**: `tests/test_review_memory.py` + `tests/test_review_fixer.py`
- **依赖**: 无

### P1-7 `_update_rule_perf_from_decisions` 单测
- **工作量**: 0.2 天
- **改动**: 扩展 `tests/test_api_auth.py` 或新建 `tests/test_review_confirm.py`
- **依赖**: 无
- **收益**: 保障反馈闭环核心逻辑不回归

---

## 三、P2 中长期（一个月内,共 ~8 天）

### P2-1 parallel_review.py 拆分 ✅ 已完成（2026-04-19）
- **实际工作量**: 1 次会话（<1 天），含测试迁移 + 文档同步
- **落地**: `parallel_review.py` 1223 → 78 行 facade，按 Cluster A/B/C/D/E/F 拆到 `review/{dimensions,prompting,worker,orchestration,evidence_verify,aggregation}.py`
- **验证**: pytest 490 passed 零回归，对外 import 零改动
- **收益已兑现**: 单文件最大 482 行（worker.py），远低于 1900 软触发线；test_split_plan_trigger 永久保持绿色

### P2-2 register_repo 集成到 Web UI
- **工作量**: 1 天
- **改动**: Phase 4 报告导出后，新增"关联下游仓库"弹窗,让用户贴仓库路径,自动调 register_repo 加到 `.pecker_registry.json`
- **依赖**: P0-4 审计链路接通（事件顺便记录）
- **收益**: feedback.py scan 模式有数据源

### P2-3 AI Coding 返工率终极指标（P2.3 from MATURITY）
- **工作量**: 2 天
- **依赖**: P2-2 完成 + 至少 5-10 个注册仓库积累 1 个月
- **落点**: `feedback.py` scan 模式输出返工率 + `workspace*/output/rework_metrics.json`
- **收益**: 从 MATURITY 的 11 维度终于能回答"这个系统有用吗"

### P2-4 app.py 退役标记
- **工作量**: 0.2 天
- **改动**: `app.py` 文件头加大字号警告"本文件为 Streamlit 旧版,新功能去 api + web/",或移动到 `legacy/`
- **依赖**: 无
- **收益**: 根目录观感清爽

### P2-5 HARNESS 冲 90 分的 5 项加分项
- confidence=0.0 降级兜底 (0.3 天)
- 越界反哺 Worker prompt (0.5 天)
- Eval 回归告警 (0.5 天)
- A 类模糊匹配收紧 (0.3 天)
- 新规则冷启动先验 (0.3 天)

合计 1.9 天,可分散插入其他工作间隙。

---

## 四、长期机制（防止再踩坑）

### 机制-1 文档漂移防护
- 每次 commit 涉及核心架构/模块变更时，同步检查并更新：
  - CHANGELOG.md
  - HARNESS_MATURITY.md（如分数有变化）
  - PRODUCTION_READINESS.md（如 blocker 状态变化）
  - 啄木鸟_产品介绍.md（如核心概念变化）
  - `.env.example`（如新加 env var）
- 或加 pre-commit hook: 改了 review/ 子包 / goshawk_advisor.py 等核心文件时提醒同步文档

### 机制-2 rule_perf 防污染
见 `RULE_PERF_CLEANUP.md` 第五节:
- 快照 + rollback
- 异常决策延迟写入（reject_rate > 0.9 的 confirm 要二次确认）
- EMA 衰减窗口（近 90 天）

### 机制-3 稳定性日常监控
见 `STABILITY_REGRESSION_TESTS.md` 第五节:
- `scripts/stability_daily.py` 每天跑:
  - 24h 内 worker_done 的 zero-items 占比 > 10% 告警
  - quota_exhausted error 次数 > 5/天 告警
  - review_failed / review_completed 比 > 15% 告警

---

## 五、已完成的记录（2026-04-16 审计结论）

| # | 事项 | 落点 |
|---|---|---|
| ✅ | 三份状态文档更新（CHANGELOG / MATURITY / PRODUCTION_READINESS） | 根目录 |
| ✅ | 产品介绍 + 使用指南过时条目修正 | `啄木鸟_产品介绍.md` `啄木鸟_使用指南.md` |
| ✅ | 3 份 CC 研究笔记归档 | `docs/research/` |
| ✅ | parallel_review 拆分蓝图 | `docs/SPLIT_PLAN.md` |
| ✅ | 稳定性诊断（3 漏洞根因定位） | `docs/STABILITY_DIAGNOSIS.md` |
| ✅ | 6 个回归 test 方案 | `docs/STABILITY_REGRESSION_TESTS.md` |
| ✅ | rule_perf 清洗方案 | `docs/RULE_PERF_CLEANUP.md` |
| ✅ | `.env.example` 补全 | `.env.example` |
| ✅ | `.gitignore` 补 3 项 CC 本地产物 | `.gitignore` |
| ✅ | 5 条关键 memory 沉淀 | `~/.claude/.../memory/` |
| ✅ | docs/ 索引 | `docs/README.md` |

---

## 六、执行顺序建议（冲 90 分路径）

```
本周:   P0-1 → P0-2 → P0-3 → P0-4（1.6 天,配额 bug 修复 + 审计接通）
下周一: P1-5 验证 consistency 从 17% → 50%+（0.3 天）
下周:   P1-1 清洗污染 → P1-3 telemetry → P1-4 CI gate → P1-7 新单测（1.5 天）
再下周: P1-2 扩充测试用例 → P1-6 两个模块单测（2.5 天）
未来一个月: P2-2 register_repo 集成 → P2-4 app.py 退役 → P2-5 加分项（3 天）
一个月后: P2-3 返工率指标（2 天,需要累积数据）
```

总工作量约 13-15 天（不含 P2-1 parallel_review 拆分的 3-4 天）。

完成后 HARNESS_MATURITY 预期 84 → 92+。
