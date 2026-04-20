# docs/ — 工程文档目录

本目录保存开发期间产出的深度分析、规划、诊断文档。和根目录的轻量文档（README、CHANGELOG、DEV.md、产品介绍等）区分开。

## 目录

| 文档 | 类型 | 描述 |
|---|---|---|
| **[ACTION_PLAN.md](ACTION_PLAN.md)** | **主行动计划** | **13 轮审计汇总,按 P0/P1/P2 排序的全部待办 + 长期机制 + 执行顺序建议** ⭐ |
| [STABILITY_DIAGNOSIS.md](STABILITY_DIAGNOSIS.md) | 诊断 | 2026-04-16 定位的 3 个 P0 稳定性漏洞（全员失败不 abort + JSON 解析静默吞 + 审计链路断），含 event_store 数据、根因链、补丁方案 |
| [STABILITY_REGRESSION_TESTS.md](STABILITY_REGRESSION_TESTS.md) | 测试规划 | 针对 STABILITY_DIAGNOSIS 的 6 个回归 test + CI 集成 + 验收 checklist + 长期监控脚本设计 |
| [RULE_PERF_CLEANUP.md](RULE_PERF_CLEANUP.md) | 数据清洗 | workspace-对外投资 的 rule_performance_history 15 条规则诊断,7 条疑似污染的清洗脚本规格 + 防污染机制 |
| [SPLIT_PLAN.md](SPLIT_PLAN.md) | 重构规划（✅ 2026-04-19 已实施） | `parallel_review.py`（1223 → 78 行 facade）按职责拆 6 模块完成：`review/{dimensions,prompting,worker,orchestration,evidence_verify,aggregation}.py`，对外 import 零改动 |
| [research/](research/) | 研究归档 | Claude Code v2.1.107 源码逆向的 3 轮研究报告（已落地到代码） |

## 工作流约定

- **主代码改动前先读对应诊断/规划**：改 `review/` 子包（worker/prompting/orchestration）前读 `ARCHITECTURE.md` File Mapping 定位；改 worker 错误处理前读 `STABILITY_DIAGNOSIS.md`
- **诊断文档不能让它"烂"**：定位的根因修掉后，诊断文档要补 "✅ 已修复 commit XXX"，否则下次又会被误读成仍存在的问题
- **归档到 research/ 的触发条件**：研究笔记对应的代码改动入库后，顺手移到 `research/` 并在 `research/README.md` 登记
- **诊断文档的生命周期**: 发现 → 写诊断 → 修复 → 标注已修复 → 保留 1-2 版本后移入 research/
