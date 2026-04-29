# 信鸽 v1 vs v2 反馈系统 — 共存策略 + 退役 Trigger

**状态**: 共存 (v2 优先, v1 降权辅助)
**最后更新**: 2026-04-29
**关联代码**:
- v1: `feedback.py` / `feedback_cmd.py` / `review/prompting.py::_build_feedback_section`
- v2: `scripts/feedback_v2.py` / `review/learnings_store.py` / `review/prompting.py::_build_learnings_section`
- Web 接入: `feishu_bot.py::_try_parse_feedback` / `api/routes/feishu.py` (POST /feishu/event)

---

## 1. 为什么有两套反馈系统

### v1 (信鸽一代)
- 时间: 2026-Q1 落地
- 输入: 代码 commit 历史 (PM 改了哪些字段、加了哪些 TODO)
- 输出: `rule_perf_history.json` 中的 rejection_rate / missed / impact_score
- 信号路径: `feedback.py` 跑 git diff → 写规则统计 → `_build_feedback_section` 注入 worker
- 优点: 自动化, 不依赖 PM 主动操作
- 缺点:
  - 信号滞后 (commit 距离评审决策可能有几天)
  - 推断噪声大 (commit 含义不一定与评审 rule 一一映射)
  - 无法捕捉 "这条规则误报但 PM 没改代码" 的情况

### v2 (信鸽二代, CodeRabbit 模式)
- 时间: 2026-04-22 落地
- 输入: PM 在飞书里 @机器人 用自然语言反馈 ("R-001 是误报, 字段约定为 20")
- 输出: `learnings.db` (sqlite) 中的 learning record (trigger_pattern + instruction)
- 信号路径: 飞书 bot → `_try_parse_feedback` → `record_outcome` + auto-learning → `_build_learnings_section` 注入 worker
- 优点: 信号准 (PM 直接确认), 实时, 可携带 rule_id 关联
- 缺点:
  - 依赖 PM 主动 @机器人 (覆盖度低)
  - 启发式解析有 ~20% 漏抽率 (heuristic finding_id + outcome 抽取)

### 决策: 共存, v2 优先

两套互补, 不互替:
- 大部分场景 v2 信号有效 → v2 主导
- v2 没覆盖的规则 (PM 还没反馈过) → v1 兜底
- v1 与 v2 冲突时 → 以 v2 为准 (PM 直接反馈优先于 commit 推断)

---

## 2. Worker Prompt 注入顺序 (review/prompting.py)

```
system_prompt
├── (默认规则 + 维度提示)
├── examples block (L3 升级)
├── ## PM 反馈编译记录 (Learnings) — 高优先级 / 信鸽 v2     ← 最先看到, 优先级最高
│   • org_global > team_local > pr_local
│   • 冲突时 learning 优先
├── ## 真实依据清单 (refs_section) — 防 evidence 造假
└── ## 近期反馈提示 — 辅助优先级 / 信鸽 v1                  ← 最后看到, 仅作参考
    • 与上文 v2 冲突时, 以 v2 为准 (在文案里显式注明)
```

代码位置: `review/prompting.py:469-490`

### 优先级如何落地

不仅是物理顺序, 还在文案里显式注明:
- v2 section 标题加了 **"高优先级 / 信鸽 v2"** + "与默认规则/v1 冲突时 learning 优先"
- v1 section 标题加了 **"辅助优先级 / 信鸽 v1"** + "与上文 v2 冲突时, 以 v2 为准"

worker (Claude Sonnet 4.6) 读到这两段时会理解优先级层级, 不会两边都给等权重.

---

## 3. 何时退役 v1 — 量化 trigger

不要早删 v1, 等以下条件**全部**满足后再退:

| 维度 | 阈值 | 度量方法 |
|---|---|---|
| v2 覆盖度 | 现役规则 ≥ 80% 至少有 1 条 learning | `python scripts/feedback_v2.py list --workspace workspace-sample` 看 related_rule_ids 去重数 / yaml 总规则数 |
| v2 可靠度 | learning usage_count 平均 ≥ 5 (说明真在帮 worker 决策) | `python scripts/learnings_dashboard.py` 看 usage 分布 |
| 老 caller 全清 | 没有任何代码路径还在 import `_build_feedback_section` 或读 `rule_perf_history.json` | grep 全代码库, 必须为空 |
| eval gate 通过 | 关闭 v1 后跑一周 rule_regression, P/R 不掉 | 看 `scripts/fixtures/regression_results.json` |

满足后的退役动作:
1. `_build_feedback_section` 加 `if not os.environ.get("PECKER_FEEDBACK_V1_ENABLE")` 默认关闭
2. 跑一周影子模式, 看 macro P/R 是否回退
3. 删 `feedback.py` / `feedback_cmd.py` (保留 `rule_perf_history.json` 历史)
4. 移 `_build_feedback_section` 到 `legacy/` 或彻底删

---

## 4. cuckoo_eval.py 的位置

cuckoo_eval 与 v1/v2 反馈是不同维度的事:
- v1/v2: 评审中的 worker prompt 信号
- cuckoo_eval: 评审后的离线 eval 工具 (P/R 评分)

**cuckoo_eval 已废弃** (2026-04-29 标记):
- 替代品: `scripts/rule_regression.py`
- 保留原因 (向后兼容):
  1. `eval/route_eval/scorers/cuckoo_adapter.py` 还在复用 `cuckoo_scorer` 内部 helper
  2. `tests/test_cuckoo_eval_hardening.py` 锁住的工具函数 (_safe_get / _atomic_write_json) 还有别处用
- 已加 deprecation warning: 模块文档头 + `main()` 入口 stderr 输出 + warnings.warn
- 退役 trigger: 当 `workspace-sample/review-rules/review-checklist.yaml` 全规则覆盖
  positive_example + negative_example, 且 cuckoo_adapter 改完, 再删

---

## 5. ops checklist

### 维护 v2 (主)
- 每月看一次 `scripts/learnings_dashboard.py` 输出, learning 累计在涨即 OK
- learning_id 删除走 `python scripts/feedback_v2.py delete <id>`, 不要直接改 sqlite
- 飞书 @机器人 反馈走 `/api/feishu/event` (生产路由, 见 docs/feishu_integration.md)

### 监控 v1 (辅助)
- `rule_perf_history.json` 漂移检测: `python scripts/cleanup_rule_perf.py --dry-run` 每月跑
- v1 还能 fire 的规则 (rejection_rate > 0.3 等阈值), 看是不是没被 v2 覆盖 — 是的话推 PM 用飞书反馈一次, 把信号迁到 v2

### 冲突排查
当 worker 表现奇怪时, dump prompt 看 v1/v2 section 有没有矛盾:
```bash
PECKER_DEBUG_PROMPT=1 python parallel_review.py --workspace workspace-sample
# 看 logs/ 下的 worker_prompt_<dim>_<ts>.txt
```
如果 v2 说 reject 但 v1 说 missed → 排查 PM 反馈是否过时, 撤回 learning.
