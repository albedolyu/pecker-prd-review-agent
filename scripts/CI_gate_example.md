# Rule Regression Harness — CI Gate 完整指南 (步骤 5)

啄木鸟规则改动的回归保护体系是**两段式**:

| 段 | 跑在哪 | 跑什么 | 何时阻塞 |
|----|--------|--------|----------|
| (a) **Static gate** (CI) | GitHub Actions | yaml schema / baseline 同步 / token 预算 / learnings 健康 | PR 合并前 |
| (b) **真实 worker P/R** (本地/dev) | Git pre-commit + 手动 | `rule_regression.py` 调真实 worker, 算 P/R 对比 baseline | 本地 commit 前 |

为什么拆两段:
- 真实 worker 走 codex CLI (ChatGPT Pro OAuth) + DeepSeek API. CI 上没法装 codex CLI, 也不能放生产 OAuth token.
- Static gate 只跑文本检查, 任何 runner 都能跑, 50% 的回归风险可以在 CI 拦掉.
- 本地 hook 跑真实 P/R, 让单条规则在 commit 前就有反馈.

---

## 1. 接入步骤 (推荐顺序)

### 1.1 第一次跑 (建 baseline)

```bash
# 在 dev 机上 (有 codex CLI + DeepSeek API key)
python scripts/rule_regression.py \
    --rules-yaml workspace-sample/review-rules/review-checklist.yaml \
    --baseline scripts/fixtures/regression_baseline.json \
    --skip-nli   # 第一次先快跑, 后续可以去掉
# 自动 promote 当前结果为 baseline (首次跑时 baseline 不存在 → first-run 模式)

git add scripts/fixtures/regression_baseline.json
git commit -m "chore: bootstrap rule_regression baseline"
```

### 1.2 配 CI gate (Static)

`.github/workflows/rule_regression.yml` 已就位. trigger paths:
- `review-rules/**`
- `workspace-sample/review-rules/**`
- `workspace-sample/learnings/**`
- `review/prompting.py`, `review/worker.py`, `review/learnings_store.py`
- `review-dimensions.yaml`
- `scripts/rule_regression.py`, `scripts/static_rule_check.py`
- `scripts/fixtures/regression_baseline.json`

跑的命令 (CI 内部):
```bash
python scripts/static_rule_check.py \
  --workspace workspace-sample \
  --baseline scripts/fixtures/regression_baseline.json
```

退出码: 0 / 1 (errors > 0 即 fail).

### 1.3 配本地 pre-commit (真实 worker)

```bash
# 一次性, clone 后跑
cp scripts/pre-commit.sample .git/hooks/pre-commit
chmod +x .git/hooks/pre-commit
```

行为:
- 改了 `review-checklist.yaml` 中**单条**规则 → 本地跑该规则的 `rule_regression.py --rule-id`
- 改了**多条**规则 → 跳过 (建议提交后手动跑全量)
- 改了 prompting / worker / learnings_store → 提示手动跑全量

### 1.4 PR 合并工作流

```
1. 改 review-checklist.yaml 或 prompting.py
2. git add & git commit
   → pre-commit hook 跑 static + 单 rule regression
   → 失败时停留, 修了再 commit
3. git push & 开 PR
   → GH Actions 跑 static_rule_check
   → 通过后 merge
4. (可选) merge 后 dev 机上跑全量 regression, 如果 P/R 跌就回滚 + investigate
```

---

## 2. 命令速查

### 2.1 真实 worker 跑

```bash
# 全量
python scripts/rule_regression.py \
    --rules-yaml workspace-sample/review-rules/review-checklist.yaml \
    --baseline scripts/fixtures/regression_baseline.json \
    --tolerance 0.05

# 单条规则 (调试)
python scripts/rule_regression.py --rule-id RC-005

# 跳过 NLI 加速 (dev only)
python scripts/rule_regression.py --skip-nli

# Promote 当前结果为新 baseline (规则 prompt 改了, baseline 应更新)
python scripts/rule_regression.py --update-baseline
```

### 2.2 Static gate 跑 (CI 用)

```bash
python scripts/static_rule_check.py
python scripts/static_rule_check.py --strict   # warning 也当 fail
```

### 2.3 信鸽 v2 (PM 反馈)

```bash
# 添加 learning
python scripts/feedback_v2.py add \
    --workspace workspace-sample \
    --finding R-001 \
    --feedback "这条是误报, 分页字段已统一约定为 20" \
    --reviewer 潘驰 \
    --scope team_local \
    --rule-id RC-005

# 列出
python scripts/feedback_v2.py list --workspace workspace-sample
python scripts/feedback_v2.py list --workspace workspace-sample --scope team_local

# Dashboard
python scripts/learnings_dashboard.py --workspace workspace-sample
# → 写入 workspace-sample/learnings/dashboard.md
```

### 2.4 演示

```bash
python scripts/demo_learnings.py
# 创建 tmp workspace + 添加 3 条 learning + 验证注入 prompt + 渲染 dashboard
```

---

## 3. 故障排查

### 3.1 Static gate 失败 "baseline 中以下 rule_id 在 yaml 已找不到"

**原因**: 改 yaml 时把规则 rename 了, baseline 没同步.

**修复**:
```bash
# 选项 a: 重新 rename baseline 中的 key (保留历史 P/R)
# 选项 b: 直接 update baseline (会重新跑 worker, 但 baseline 重置)
python scripts/rule_regression.py --update-baseline
```

### 3.2 Static gate 警告 "yaml 中以下 rule_id 是新增"

**原因**: 加了新规则, baseline 里没有, CI 不阻塞但需要建 baseline.

**修复**:
```bash
# 在 dev 机上 (有 LLM access) 跑全量, 让新规则进 baseline
python scripts/rule_regression.py --update-baseline
git add scripts/fixtures/regression_baseline.json
git commit -m "chore: add baseline for new rules"
```

### 3.3 CI 报 "import codex / anthropic 失败"

CI 不应该 import `codex_cli_client.py` / Claude SDK. `static_rule_check.py` 不依赖这些.
如果发生, 是 `_build_examples_block` 的副作用 import 链有问题, 检查 `review/prompting.py`
顶部 import 是不是把 worker 拉进来.

### 3.4 pre-commit 太慢 (>2 min)

- 默认只跑单 rule 时调一次 worker (~10s)
- 多 rule 改动 hook 直接 skip, 不阻塞 commit
- 如果想全部 skip: `git commit --no-verify` (但要记得手动跑)

---

## 4. Trend 分析

CI artifact `regression_results.json` 留 90 天. 历史聚合:

```python
# scripts/regression_trend.py (示例)
import json, glob
results = []
for path in sorted(glob.glob("artifacts/*/regression_results.json")):
    with open(path) as f:
        r = json.load(f)
    for rid, m in r["rules"].items():
        results.append({"ts": r["timestamp"], "rule": rid,
                        "P": m["precision"], "R": m["recall"]})
# 按 rule 画折线
```

---

## 5. 与其他工具的关系

| 工具 | 定位 | 触发时机 |
|------|------|----------|
| `cuckoo_eval.py` | 端到端评审质量手卷 eval | 改大版本前 |
| `rule_regression.py` | 规则级 P/R 回归 | 改 yaml/prompt 后 |
| `static_rule_check.py` | 静态 schema/baseline 检查 | 每次 PR (CI) |
| `feedback.py` (v1 信鸽) | 看代码 commit 反推 finding 采纳 | AI Coding 完成后 |
| `feedback_v2.py` (v2 信鸽) | PM 显式自然语言反馈 → learning | 评审完每次, PM 觉得有问题就报 |
| `learnings_dashboard.py` | learning usage 统计 + stale 提示 | 每周看一次 |

---

## 6. Metrics 埋点 + Dashboard

啄木鸟 v2 在关键路径埋了 9 类生产事件, 写入 `workspace/metrics.db` (sqlite + WAL).
Dashboard 是纯静态 HTML (chart.js CDN), 不引外部监控服务, 可在本地 / dev 机直接打开.

### 6.1 已埋点的 event_type 矩阵

| 文件 | event_type | 触发时机 |
|------|-----------|----------|
| `review/worker.py::_worker_core` | `worker.started` | worker 入口, 准备 ctx 之前 |
| `review/worker.py::_worker_core` | `worker.completed` | worker 成功返回 (含 items_count / tokens / cost / empty_retry_used / degraded) |
| `review/worker.py::_worker_core` | `worker.failed` | _prepare_worker_context 或 initial _call 抛异常 |
| `review/worker.py::_run_worker_async` | `worker.failed` (status=timeout) | WORKER_TIMEOUT 触发 |
| `goshawk_advisor.py::advisor_review` | `goshawk.started` | 苍鹰 print art 之后, 构 user_msg 之前 |
| `goshawk_advisor.py::advisor_review` | `goshawk.completed` | 苍鹰返回 result 之前 (含 verdict / confidence / fp_count / additional_count / conflict_count) |
| `goshawk_advisor.py::advisor_review_async` | `goshawk.failed` (status=timeout) | GOSHAWK_TIMEOUT 触发 |
| `review/evidence_verify.py::verify_evidence` | `evidence_verify.completed` | 主入口 return 前 (含 input_count / retracted / downgraded / retracted_by_reason / wiki_sparse) |
| `review/evidence_verify.py::_llm_nli_score` | `nli.score` | LLM NLI 重采样结束, status 字段记 winning verdict (entail/contradict/neutral) |
| `clients/anthropic_native.py` | `llm.api_call` | create() 包装层成功/失败 |
| `clients/claude_cli.py` | `llm.api_call` | _create_once 包装层成功/失败 |
| `clients/deepseek_native.py` | `llm.api_call` | create() 包装层成功/失败 |
| `clients/codex_cli.py` | `llm.api_call` | create() 包装层成功/失败 |
| `api/routes/feedback.py::_record` | `feedback.received` | accept/reject/edit 三个 endpoint 共用 |

埋点风格:
- 全部 import `record_event` 用 `try/except → noop` 兜底, metrics_store 损坏不影响 review 主流程.
- record 失败 silent skip (`record_event` 内部已吞所有异常, 1 分钟内只 warn 一次).
- 字段命名 snake_case + 模块前缀 (`worker.*`, `goshawk.*`, `nli.*`...).

### 6.2 关闭埋点 (eval / unit test)

```bash
export METRICS_DISABLED=1
python -m pytest tests/   # 所有 record_event 变 no-op
```

### 6.3 跑 metrics 端到端验证

```bash
# 临时目录跑 (CI 用, 不污染 workspace)
python scripts/test_metrics_pipeline.py

# 把 metrics 写到指定 workspace + 保留 db / dashboard
python scripts/test_metrics_pipeline.py --workspace workspace-sample --keep-db

# 跳过 dashboard 渲染 (只要 db 验证)
python scripts/test_metrics_pipeline.py --skip-dashboard
```

退出码:
- `0` = 9 类 event_type 全部进库 + dashboard.html 成功生成
- `1` = 任一 event_type 缺失 / dashboard 渲染失败

### 6.4 看 dashboard

```bash
# 1. 真实跑过 review session 后, workspace/metrics.db 自动有数据
# 2. 渲染:
python scripts/render_metrics_dashboard.py \
    --db workspace-sample/metrics.db \
    --out workspace-sample/dashboard.html \
    --days 30

# 3. 浏览器打开 workspace-sample/dashboard.html
```

Dashboard 含: 顶部 KPI (review 数 / 错误数 / 累计 cost / 平均时长), 每日 review 趋势,
per-vendor 错误率 bar, per-model 调用 donut, 成本累计 area, 最近异常事件表.

### 6.5 90 天保留 + cron

```bash
# 每日跑一次, 把已完成日聚合到 daily_aggregate 表 + 删 90 天前 events
python scripts/setup_metrics_aggregation.py --workspace workspace-sample
```

### 6.6 故障排查 — dashboard 是空的

1. 检查 `metrics.db` 是否存在: `ls workspace-*/metrics.db`
2. 检查环境变量: `METRICS_DISABLED` 是否为 1 / `METRICS_DB_PATH` 是否覆盖到错误位置
3. 直接查 db: `sqlite3 workspace-sample/metrics.db 'SELECT event_type, COUNT(*) FROM events GROUP BY event_type'`
4. 验证埋点没坏: `python scripts/test_metrics_pipeline.py --workspace workspace-sample`
5. 跑 review pipeline 一次: 跑 review 后再看 metrics.db, 应该有 worker.* / llm.api_call 写入

---

## 7. v1 → v2 迁移 (信鸽)

v1 (`feedback.py`) 和 v2 (`feedback_v2.py`) 共存, 不强制迁移. 但 v2 数据更结构化, 长期推荐 v2.

平滑过渡建议:
- 老 v1 信号源 (rule_perf_history.json) 仍然由 `_build_feedback_section` 注入到 worker prompt
- 新 v2 learning 由新增的 `_build_learnings_section` 注入, 二者互补不冲突
- 当 v2 的 learning 数量 > 50 条时, 可以考虑停掉 v1 的 commit 扫描 (省一个手动步骤)
- 历史 v1 高 rejection_rate 规则可以手动转成 v2 learning (高优先级 trigger), 让 PM 反馈语义化
