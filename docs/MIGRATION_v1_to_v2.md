# 啄木鸟 v1 → v2 迁移手册

**状态**: 渐进迁移期 (cuckoo_eval 与 rule_regression 共存; feedback v1 与 v2 共存)
**最后更新**: 2026-04-29
**计划完全删除 v1 的时间**: 2026-06-30 (约 2 个月观察期)

> 本文档是"做什么"的操作 cookbook. 决策依据 (为什么有两套) 见
> [v1_vs_v2_feedback_strategy.md](./v1_vs_v2_feedback_strategy.md).

---

## 1. TL;DR — 我现在该跑什么

| 老命令 (v1, 仍可跑但 emit DeprecationWarning) | 新命令 (v2, 推荐) | 何时切 |
|---|---|---|
| `python cuckoo_eval.py --report ... --test-case ...` | `python scripts/rule_regression.py --rules-yaml workspace-sample/review-rules/review-checklist.yaml --baseline scripts/fixtures/regression_baseline.json` | 立即, baseline 已就绪 |
| `python cuckoo_eval.py --generate-test-case ...` | (没有直接替代, baseline 由 worker 跑出来) `python scripts/rule_regression.py --update-baseline` | 立即 |
| `python feedback.py --code-dir ... --report ...` | `python scripts/feedback_v2.py add ...` (PM 主动加) 或 飞书 @机器人 (自动入库) | 立即, 但 v1 仍兜底未覆盖规则 |
| 直接 import `cuckoo_eval.parse_review_report` | (移到 `cuckoo_parser.parse_review_report`, 但都已 deprecated; 新流程不解析报告, 直接拿 worker JSON) | 等 caller 全清后删 |

如果你只是要跑回归 / 提 PR — 看 §2.
如果你在维护规则库 / 反哺 worker — 看 §3.

---

## 2. cuckoo_eval → rule_regression (P/R baseline + CI gate)

### 2.1 概念对照

| 维度 | cuckoo_eval (v1) | rule_regression (v2) |
|---|---|---|
| 输入 | 啄木鸟评审报告 markdown + 手卷 test_case.json | yaml 规则文件 + worker JSON 输出 + 持久 baseline |
| 单位 | 报告级 (整份评审 PASS/FAIL) | 规则级 (每条 rule 的 P/R) |
| baseline | 不存 (每次重跑) | `scripts/fixtures/regression_baseline.json` (持久, 进 git) |
| 失败定义 | 综合得分 < 阈值 | macro P 或 macro R 跌 > tolerance (默认 0.05) |
| CI 集成 | 无 | `.github/workflows/rule_regression.yml` (static) + `rule_regression_real.yml` (real worker on self-hosted) |
| 真实 worker | 不调 (只解析已生成的报告) | 调 (改 prompt 时跑回归捕捉真实回归) |
| 历史趋势 | `eval_history.json` (单数值) | `regression_results.json` per run + git commit baseline 演进 |

### 2.2 输出格式对照

**v1 cuckoo_eval 输出** (eval_history.json 单条):
```json
{
  "timestamp": "2026-04-11 14:23",
  "test_case": "劳动仲裁",
  "model": "claude-sonnet-4-6",
  "overall_score": 0.78,
  "overall_verdict": "PASS",
  "recall": 0.85,
  "precision": 0.72,
  "location_accuracy": 0.65,
  "evidence_reliability": 0.83,
  "severity_accuracy": 0.70,
  "format_completeness": 0.95,
  "detail": {"total_bugs": 12, "total_items": 15, "hit_count": 10}
}
```

**v2 rule_regression 输出** (regression_results.json):
```json
{
  "summary": {
    "macro_precision": 0.81,
    "macro_recall": 0.76,
    "rule_count": 31,
    "tolerance": 0.05,
    "passed": true
  },
  "rules": {
    "RC-001": {
      "dimension": "field_consistency",
      "precision": 0.83, "recall": 0.71,
      "TP": 5, "FP": 1, "FN": 2, "TN": 12,
      "worker_finding_count": 6
    },
    "RC-002": { ... }
  },
  "baseline_diff": {
    "RC-007": {"precision": -0.08, "recall": +0.02}
  }
}
```

### 2.3 渐进迁移路径

#### Step 1 — 现状 (now): 共存期
- cuckoo_eval 跑老 test case, 仍有效 (deprecation warning 不阻塞)
- 新提的 PR 都用 rule_regression 跑 P/R gate
- merge_reviews / cuckoo_adapter 内部 helper 还用 cuckoo_scorer (不动)

#### Step 2 — baseline 全覆盖 (≈4 周后)
触发条件: `workspace-sample/review-rules/review-checklist.yaml` 全 31 条规则
都有 positive_example + negative_example, 且 baseline 真实 worker 跑过 ≥ 3 次稳定.

行动:
1. cuckoo_eval main() 改成 `print("[ERROR] cuckoo_eval 已退役, 改用 scripts/rule_regression.py"); sys.exit(2)`
2. 老 test_case JSON 归档到 `eval/legacy_test_cases/`
3. 同步更新 README / DEV.md 引导

#### Step 3 — 彻底删 (≈8 周后, 约 2026-06-30)
触发条件: grep 全代码库无 `import cuckoo_eval` / `from cuckoo_eval` 残留.

行动:
1. 删 `cuckoo_eval.py`
2. 评估 `cuckoo_parser.py` 是否还有 caller (merge_reviews 仍用就不删)
3. `cuckoo_scorer` 内部 helper 整理, 把 `match_items_to_bugs` 等保留的函数挪到
   `eval/route_eval/scorers/cuckoo_legacy.py` (改名突出已退役)
4. 删本文档的 §2 (留个跳转到 git history 的指引)

### 2.4 常见问题

**Q: 我已经有一份 cuckoo eval 报告 (markdown), 还能怎么用?**
A: 留作历史. 新 baseline 直接跑 `python scripts/rule_regression.py --update-baseline` 重建.

**Q: rule_regression 没跑过 baseline, CI 怎么办?**
A: PR 里 commit `scripts/fixtures/regression_baseline.json` (空也行, 第一次 PR 时
   maintainer 跑一次 `--update-baseline` 提交基线).

**Q: 我改了 worker prompt, P 跌了 7%, 是不是必须 update-baseline?**
A: **不**. 先看 `regression_results.json` 里哪条 rule 跌了, 复盘 prompt 改动是否
   合理. 真要降 baseline 必须在 PR description 注明 + maintainer 显式批准.

---

## 3. feedback (commit-watch v1) → feedback_v2 (NL learnings)

### 3.1 概念对照

| 维度 | feedback v1 (信鸽一代) | feedback_v2 (信鸽二代) |
|---|---|---|
| 信号源 | git commit / 代码注释 / 字段命名 / UI 状态扫码 | PM 在飞书 @机器人 自然语言反馈 / Web UI 点 accept/reject |
| 存储 | `rule_perf_history.json` (json) + `rule_impact_timeline.json` | `learnings.db` (sqlite, 持久) |
| 注入 worker prompt 的位置 | `_build_feedback_section` (优先级低, 文案标"辅助") | `_build_learnings_section` (优先级高, 文案标"高优先级") |
| 信号粒度 | 推断 (commit 含义猜规则关联) | 直接 (PM 显式说哪条 finding 误报) |
| 触发频率 | PM 手工跑 / 定时 scan registered repos | 每次 PM 反馈实时入库 |
| 噪声 | 大 (commit 不一定与 rule 一一对应) | 小 (启发式抽 finding_id 漏抽率 ~20%) |

### 3.2 worker prompt 注入顺序 (review/prompting.py:469-490)

```
system_prompt
├── (默认规则 + 维度提示)
├── examples block (L3 升级)
├── ## PM 反馈编译记录 (Learnings) — 高优先级 / 信鸽 v2     ← 最先看到
│   • org_global > team_local > pr_local
│   • 冲突时 learning 优先
├── ## 真实依据清单 (refs_section) — 防 evidence 造假
└── ## 近期反馈提示 — 辅助优先级 / 信鸽 v1                  ← 最后看到, 仅供参考
    • 与上文 v2 冲突时, 以 v2 为准
```

### 3.3 渐进迁移路径

#### Step 1 — 现状 (now): 共存
- v1 自动跑 (定时 scan registered repos, 见 `scripts/setup_oat_task_scheduler.ps1`)
- v2 由 PM 飞书反馈触发 + Web UI 反馈
- worker prompt 同时注入两套, 文案标明 v2 优先

#### Step 2 — v2 覆盖 ≥ 80% 规则 (≈ 6 周观察)
触发条件 (全部满足):
- v2 覆盖度 ≥ 80%: `python scripts/feedback_v2.py list --workspace workspace-sample`
  看 related_rule_ids 去重数 / yaml 总规则数
- v2 可靠度: learning 平均 usage_count ≥ 5 (`python scripts/learnings_dashboard.py`)
- 老 caller 全清: grep 全代码库无 `_build_feedback_section` 调用残留 (除 prompting.py 本身)
- eval gate: 关闭 v1 一周, P/R 不掉

行动:
1. `_build_feedback_section` 加 `if not os.environ.get("PECKER_FEEDBACK_V1_ENABLE")` 默认关闭
2. 影子模式跑一周, 看 macro P/R 是否回退 (`scripts/shadow_run.py`)
3. 跑通后 commit 关闭 v1 default

#### Step 3 — 删 v1 (≈ 8 周后)
1. 删 `feedback.py` / `feedback_cmd.py`
2. 删 `_build_feedback_section` (review/prompting.py)
3. 保留 `rule_perf_history.json` 历史文件 (don't lose data)
4. `register_repo.py` / `registry.py` (scan 模式) 评估是否还用; 不用就删
5. 更新 `scripts/setup_oat_task_scheduler.ps1` 移除 v1 scan 任务

### 3.4 PM 操作迁移 cheat sheet

**老操作 (v1)**:
```bash
# 跑完 AI coding 后手工:
python feedback.py --code-dir /path/to/code --report output/PRD_改动报告_20260411.md
```

**新操作 (v2)**:
- **场景 A — 飞书反馈 (推荐)**: 在群里 @机器人 "R-001 是误报, 字段约定为 20"
  - 自动写 `learnings.db`
  - 累计 reject ≥ 3 自动升级为 learning
- **场景 B — Web UI**: 浏览器打开评审报告 → 每条 finding 旁边点 [接受/误报/改写]
- **场景 C — 命令行**: `python scripts/feedback_v2.py add --rule-id RC-001 --workspace workspace-sample --instruction "字段统一用 snake_case"`

---

## 4. cuckoo_parser.parse_review_report → 直接消费 worker JSON

老流程: worker 输出 markdown 报告 → cuckoo_parser 正则解析 → 后续逻辑.
新流程: worker 用 `tool_choice: {"type": "any"}` 强制返回结构化 JSON, 跳过解析.

### 4.1 仍依赖 cuckoo_parser 的代码路径

```bash
grep -r "from cuckoo_parser" --include="*.py" .
# 当前结果 (2026-04-29):
#   cuckoo_eval.py — 兼容 wrapper, 已 deprecated
#   merge_reviews.py — 还用; 需要在 v3 迁移时改
#   feedback.py — 间接依赖 (通过 _parse_review_items, 实现独立)
```

### 4.2 迁移指南

merge_reviews.py 改造方案:
1. 上游 worker 改 schema, 返回 JSON list 而非 markdown
2. merge_reviews 直接消费 list, 不做正则
3. 老 path 留 fallback (markdown 报告归档复盘时仍能解析), 但新增标 `[v1-fallback]` 日志

详细 code change 见 `docs/sprint-real-prd-calibration-evidence-governance.md`.

---

## 5. 在 CI 上的过渡

### 5.1 不破坏现有 PR

- `.github/workflows/rule_regression.yml` (static gate) — 一直跑, ubuntu-latest 不烧钱
- `.github/workflows/rule_regression_real.yml` (real worker) — self-hosted runner, 必跑改 prompt 的 PR
- `pytest tests/` 全跑 — 包括老的 `test_cuckoo_eval_hardening.py` / `test_cuckoo_parser.py`

新增 deprecation warning 不会让老测试 fail (default filter 不 raise).
要让 CI catch 误用, 跑 `python -W error::DeprecationWarning -m pytest tests/`.

### 5.2 新 PR 的检查清单

提 PR 改 prompt / 规则 / worker / dimensions yaml 时, CI 会自动:
1. static gate (yaml schema / baseline 同步)
2. real worker P/R 回归 (self-hosted runner, 跌 > tolerance 阻塞)
3. PR comment 自动贴 P/R 表格

如果 self-hosted runner 离线, real-worker job mark skipped 不阻塞 (兜底跑本地 pre-push hook).

### 5.3 fallback: 没 self-hosted runner 怎么提 PR

```bash
# 装 pre-push hook (一次性)
make install      # 走 Makefile install target
# 或直接:
python scripts/install_git_hooks.py

# push 时自动跑 P/R, 跌阈值阻塞
git push
```

详见 `docs/CI_SELF_HOSTED_RUNNER_SETUP.md` §7 fallback 模式.

---

## 6. 验证清单 (维护者 release 前)

- [ ] `python -c "import cuckoo_eval"` emit DeprecationWarning (走 stderr)
- [ ] `python cuckoo_eval.py --help` 显示 `[DEPRECATED]` 标记
- [ ] `python feedback.py --help` 显示 deprecation 提示
- [ ] `python scripts/feedback_v2.py list` 能正常列出 learnings
- [ ] `python scripts/rule_regression.py --rules-yaml workspace-sample/review-rules/review-checklist.yaml --baseline scripts/fixtures/regression_baseline.json` 跑通
- [ ] `pytest tests/` 全过 (deprecation 不导致老测试 fail)
- [ ] CI `.github/workflows/rule_regression.yml` static gate 通过
- [ ] PR description 加链接到本文 (新规则改动时引导 reviewer)

---

## 7. 历史归档 (don't delete the data)

退役 v1 时, 以下数据**保留不删**:
- `eval_history.json` — cuckoo_eval 历次跑分历史
- `rule_perf_history.json` — v1 信鸽规则统计
- `rule_impact_timeline.json` — 规则权重时序
- `eval/test_cases/*.json` — 老手卷测试用例

迁到 `legacy/` 子目录, 不进新 baseline 但保留可回溯.

---

## 8. 联系人

- **维护者**: PM (产品经理), 不是工程师 — 决策按 harness engineering 原则做
- **issue / 反馈**: 提 PR 改本文, 或在团队群 @PM
- **退役进度跟踪**: `docs/SPLIT_PLAN.md` 有最新时间表
