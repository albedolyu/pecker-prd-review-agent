# 啄木鸟项目状态 — 自动生成

> 生成时间: 2026-04-22 14:17
> 来源: git log + pytest + workspace-*/output/sessions
> 本文件由 `scripts/generate_status.py` 生成,请勿手工编辑。

## 代码规模

- 根目录 Python 文件: 49 个
- 根目录总行数: 16,062

## 测试状态

- 单测总数: **490**

## 最近 14 天开发活动

- commit 数: **74**

最近 10 条提交:

| SHA | 日期 | 主题 |
|-----|------|------|
| `d73b204` | 2026-04-22 | docs(harness): 从 73 commits 沉淀 harness 工程规则集 (Top 10 + 36 规则) |
| `4047a46` | 2026-04-22 | fix(web): Dockerfile 注入 API_BASE_URL build arg + gitignore 加 override |
| `556b597` | 2026-04-21 | fix(api): 4 个端点补登录 guard + workspace-sample 目录 (内测前 P0) |
| `7fc4603` | 2026-04-21 | fix(web): SSE / precheck base 同源化 · 修 Tunnel 内测阻塞 |
| `3540788` | 2026-04-21 | fix(stability): timeout 二次抢救 + SPLIT_PLAN guard + 历史噪音归档 |
| `5c8cd99` | 2026-04-19 | refactor(review): split parallel_review.py 1223 → 78 行 facade |
| `63ba300` | 2026-04-18 | docs(preview): 紧急回退补注 · ?v=7 要先登录再加 |
| `e63edd5` | 2026-04-18 | docs(preview): Cloudflare Tunnel 搭建 + PM 试用指南 + 3 份 sample PRD |
| `353a935` | 2026-04-18 | ci(web): publish Docker image to GHCR + prod compose override |
| `54ea2aa` | 2026-04-18 | chore(deploy): Vercel + Docker Compose 部署配置 + Web CI |

## 真实运行指标 (evidence-based)

- 累计 session: **5**

Session 分类 (分层统计,避免 ops 噪声污染):

| 类别 | 计数 | 占比 | 含义 |
|------|------|------|------|
| productive | 4 | 80% | 所有 worker 都出 items,健康 |
| partial_silent | 0 | 0% | 部分 worker 静默,harness bug |
| empty_bug | 0 | 0% | 所有 worker 都静默,严重 bug |
| quota_exhausted | 0 | 0% | CLI 配额耗尽,ops 问题非 bug |
| auth_expired | 0 | 0% | CLI OAuth 401,ops 并发挤占 |
| error_other | 1 | 20% | 其他混合错误 |

- **有效一致性** (productive / 非 ops 的,剔除 quota+auth): **80.0%**
- 配额耗尽占比: 0.0% (高 → 调整运行时段)
- 401 Auth 失效占比: 0.0% (高 → 避免多进程并发)
- items 中位数 (非 quota session): 6

### Flow 完整性 (session 走完整条 pipeline 的比例)

- 完成率 (review_completed): 40.0%
- checkpoint 率: 40.0%
- 苍鹰终审失败率 (final_reviewer_done with error): 0.0%

### Worker 静默率 (仅统计非 quota 成功调用)

| dimension | silent_rate |
|-----------|-------------|
| ai_coding | 0.0% |
| data_quality | 0.0% |
| quality | 0.0% |
| structure | 0.0% |

### 错误指纹 (归一化聚合,揪出重复 bug)

| 计数 | 指纹 (前 80 字) |
|------|----------------|
| 1 | `claude -p 退出码 1: Claude Code on Windows requires git-bash (https:/<path> If inst` |

### 苍鹰 verdict 分布 (Round 8)

- 已埋点 session: 1
- empty_retry 触发次数: 0

| verdict | 计数 | 含义 |
|---------|------|------|
| REVIEWED | 1 | 苍鹰有输出(误报/漏报/冲突 >= 1),正常工作 |

### 空提交重试分支 (Round 2)

- 已埋点 worker 调用数: 12
- 触发率: **0.0%** (应接近 data_quality/quality 静默率 ≈ 50%)
- 救回率 (触发后最终出了 items): **0.0%**
- 分解: triggered=0 rescued=0 kept_empty=0

> 救回率 < 40% → retry prompt 无效,考虑改进提示词;
> 救回率 > 70% → 修复有效;
> instrumented_workers = 0 → 新代码还没跑,需要 shadow_run 或线上 session。

## 稳定性门禁

- [PASS] 有效一致性 80.0% ≥ 60%

---

> 手写版本 (HARNESS_MATURITY.md / PRODUCTION_READINESS.md) 已废弃,
> 评估以本文件为准。如需新增维度,改 `scripts/generate_status.py`。
