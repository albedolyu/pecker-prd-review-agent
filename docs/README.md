# docs/ 文档入口

这个目录只放工程、部署、试用、评测和历史复盘文档。当前有效文档放在本页索引里，过期的 dated 文档按月份归到 `docs/archive/YYYY-MM/`。

## 当前生效

| 文档 | 用途 |
|---|---|
| [internal_network_deployment_request.md](internal_network_deployment_request.md) | 运维部署、内网路径、数据保留和 workspace 挂载要求 |
| [deployment.md](deployment.md) | 部署流程和预览环境说明 |
| [dev-setup.md](dev-setup.md) | 本地开发环境和常见问题 |
| [CI_SELF_HOSTED_RUNNER_SETUP.md](CI_SELF_HOSTED_RUNNER_SETUP.md) | 自托管 CI runner 配置 |
| [FEISHU_WEBHOOK_SETUP.md](FEISHU_WEBHOOK_SETUP.md) | 飞书 webhook 接入 |
| [pm-preview-guide.md](pm-preview-guide.md) | PM 试用入口和反馈流程 |
| [HARNESS_RULES.md](HARNESS_RULES.md) | 评审 agent 和 harness 约束 |
| [MIGRATION_v1_to_v2.md](MIGRATION_v1_to_v2.md) | v1 到 v2 的退役和迁移说明 |

## 本月工作

2026-05 的 sprint、自动化和 Beta 优化资料集中在：

- [optimization_plan_2026_05_11.md](optimization_plan_2026_05_11.md)
- [auto_dev_2026_05_09_6h_continuous.md](auto_dev_2026_05_09_6h_continuous.md)
- [auto_dev_2026_05_09_7h30_deep_optimization.md](auto_dev_2026_05_09_7h30_deep_optimization.md)
- [meetings/2026-05-07-team-beta-sync/](meetings/2026-05-07-team-beta-sync/)

后续新 sprint 文档优先放到 `docs/sprints/YYYY-MM/`；若只是会议包，也可以继续放在 `docs/meetings/YYYY-MM-DD-*/`。

## 历史归档

- `docs/archive/`: 已闭环诊断、历史迭代产出和上月 dated 文档。
- `docs/research/`: 已沉淀到代码或决策里的研究笔记。

归档规则：

- 文件名包含日期且日期早于当前月份，建议移动到 `docs/archive/YYYY-MM/`。
- 文件名不含日期但 30 天无 commit 修改，只输出 warn，人工确认后再移动。
- 脚本只做建议，不移动文件：`python scripts/docs_archive_sweep.py --dry-run`。

## 治理命令

```bash
python scripts/docs_archive_sweep.py --dry-run --format text
python scripts/docs_archive_sweep.py --dry-run --format json
```

每次新增大型诊断或复盘文档后，先判断它属于“当前生效”“本月工作”还是“历史归档”。不确定时先留在本月工作，等下月用 dry-run 清单统一处理。
