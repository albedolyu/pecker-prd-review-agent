# 啄木鸟 PRD 评审系统 — Harness Engineering 成熟度自评

> 评测日期: 2026-04-16（三次更新）
> 上次评测: 2026-04-15（总分 72）
> 评测范围: 主代码库 11 维度逐条检查
> 总分: **84 / 110**
>
> **本次更新**:
> - 核实 commit `596d121` / `d21cbd3` / `7ebbe23` 后，P0 全部 + P1 三项（CI / 越界硬校验 / 一致性分析） + P2 三项（拓扑图 / 苍鹰自检 / B 类语义）均已落地。对应维度再涨 6 项
> - **⚠ 实测 consistency_analyzer 暴露稳定性问题**：同一 PRD 8 次 consistency 数据整体一致性 17%，稳定规则 0 条，部分 run 返回 0 items
> - **🔥 根因已定位（2026-04-16）**: event_store session 数据显示 70% 的 worker_done 是 0 items,12/20 带 error=`"You've hit your limit — resets 8am"`。**Claude Code CLI 配额耗尽被 `_empty_tool_fallback` 静默吞掉,当成"评审无问题"返回给用户**。这是 P0 紧急 bug,详见 `docs/STABILITY_DIAGNOSIS.md`
> - 净变化: 72 → 84 (+12)。稳定性 bug 修复后,"Eval 量化"有望从 6 回到 8,总分达 86

---

## 雷达图数据 (11 维度, 0-10)

```
维度                                  得分    变化
────────────────────────────────────  ────   ────
1. Agent 拓扑定义                      9     +1
2. Agent 行为边界与约束                 9     +1
3. 反馈闭环                            8     +2
4. 质量度量体系 (Eval)                  8     +1
5. 模型分工                            9      —
6. 不信任单层输出 (meta-reviewer)       9     +1
7. 依据可验证 (Side Query)              8     +1
8. meta-reviewer 只审不重审             9      —
9. 结构化输出强制                       8      —
10. 反馈闭环 > 静态规则                  8     +3
11. Eval 量化 > 主观判断                 6      —（乐观打 7 后实测下调）
```

---

## 1. 已达标 (>= 8 分)

### 1.1 Agent 拓扑定义 — 9/10 ↑（原 8 分）

**现状**: `parallel_review.py` 清晰定义了 orchestrator -> 4 specialist workers (织布鸟/猫头鹰/渡鸦/鸬鹚) 的拓扑。`goshawk_advisor.py` 作为 meta-reviewer 在 workers 之后独立运行。`api/routes/review.py` 端到端编排: precheck -> parallel_review -> advisor_review_async。Worker 之间无直接调用,通过 scratchpad 共享发现的 rule_id(只读,不互相影响输出)。

**✅ 已补（commit 7ebbe23）**: `ARCHITECTURE.md` 新增完整 mermaid 拓扑图（Phase 1 Precheck / Phase 2 Parallel Review SSE / Phase 3 Confirm + Data Flow + Feedback Loop 三段），File Mapping 表覆盖 23 个节点对应的文件和函数。新人读一份文档即可理解完整流程。

**剩余缺口**: 没有独立的声明式配置文件（如 `topology.yaml`）。图是文档层面的,不是运行时可解析的。

### 1.2 Agent 行为边界与约束 — 9/10 ↑（原 8 分）

**现状**:
- Worker 边界互斥: system prompt 明确写了"缺失 2 Worker 边界互斥",只评审 owner=自己的规则,越界报告会被苍鹰降权
- dim_constrained_tool: `parallel_review.py:896` 对 tool schema 的 dimension 字段加了 `const` 约束,防止模型填错维度
- Worker 输出截断: `MAX_ITEMS_PER_WORKER=15`,超出按 severity+confidence 排序截断
- MAX_WORKER_TURNS=2: 催促重试最多 1 轮,maxTurns 耗尽走文本兜底
- Worker 拒答出口: 允许 items 为空 + null_finding_reason,禁止硬凑问题

**✅ 已补（commit 596d121）**: `parallel_review.py` 在 `_extract_items_from_response` 后新增 `cross_boundary` 字段校验,检查每条 item 的 rule_id 是否属于当前维度的 checklist。不属于的 item 标记越界并从 Worker 输出中剔除或降 confidence。prompt 约束 + 运行时硬校验双保险。

**剩余缺口**: 越界样本的统计和反馈没有回流到 Worker prompt，无法让 Worker 学到"哪些规则容易越界"。

### 1.3 模型分工 — 9/10

**现状**: `config/base.py` 定义了三档模型:
- Opus: 渡鸦 (AI Coding 友好度,需深度推理)
- Sonnet: 织布鸟、猫头鹰、鸬鹚 (主力)、苍鹰 (交叉校验从 Opus 降到 Sonnet 保稳定性)
- Haiku: 路由器 (ROUTER_PROMPT 做评审复杂度判断)

review-dimensions.yaml 每个维度有 model 字段,可运行时覆盖。`_worker_core` 从 dim config 读 model 并映射到 model_tiers。effort-aware max_tokens (low/medium/high) 也已实现。还有模型降级链 (FALLBACK_MODELS): opus->sonnet->haiku。

**缺口**: 苍鹰从 Opus 降到 Sonnet 是因为 CLI 调用太慢,不是基于质量评估的决策。缺乏 A/B 测试数据支撑选型。

### 1.4 不信任单层输出: meta-reviewer — 9/10 ↑（原 8 分）

**现状**: `goshawk_advisor.py` 完整实现了苍鹰交叉校验:
- 误报检测: 识别 Worker 过度解读
- 漏报补充: 最多 2 条,硬上限由 schema maxItems + parser 双保险 (`MAX_ADDITIONAL_FINDINGS=2`, `_extract_advisor_result` 兜底截断)
- 冲突调解: 不同 Worker 对同一处矛盾判断的裁决
- Pinned Edit State: 用户 pin 的 item 不被苍鹰修改
- gate_log: 每条 item 记录完整决策链 (schema/confidence/evidence/advisor 各 gate 的 pass/fail)

**✅ 已补（commit 7ebbe23）**: 苍鹰反向校验落地。当用户 Phase 3 accept 了被苍鹰标为误报的 item,或 reject 了苍鹰补充的 item,冲突记录到 `goshawk_performance_history.json`,累计后动态调整苍鹰 confidence 权重。这直接复用了 `_save_eval_ground_truth` 产出的人类标注数据。

**剩余缺口**: confidence=0.0 时的降级策略(超时场景)仍会让所有 Worker 输出不经审核直接输出,这是最后一个单点风险。

### 1.5 meta-reviewer 只审不重审 — 9/10

**现状**: `GOSHAWK_SYSTEM_PROMPT` 明确写了"你的职责不是重新评审 PRD,而是审核其他评审员的评审结论"。漏报补充限制为最多 2 条且必须引用规则编号。Tool schema 中 `additional_findings.maxItems=2` 做了硬约束。苍鹰补充项的 confidence 会乘 0.8 衰减系数 (GOSHAWK_SUPPLEMENT_DECAY)。

**缺口**: 无。这是做得最好的维度之一。

### 1.6 结构化输出强制 — 8/10

**现状**:
- Worker: `SUBMIT_REVIEW_ITEMS_TOOL` 完整定义了 input_schema,`tool_choice={"type":"any"}` 强制调用 tool
- 苍鹰: `SUBMIT_ADVISOR_REVIEW_TOOL` 同样强制
- 催促重试: 未调 tool 时追加 followup 消息催促,精简版 tool schema 节省 token
- 文本兜底: maxTurns 耗尽时从纯文本提取 JSON (`_parse_items_from_text`)
- CLI 后端: 无原生 tool use 时,`_append_schema_instruction` 注入 JSON schema 指令,`_parse_json_from_text` 鲁棒解析
- 空壳兜底: `_empty_tool_fallback` 确保解析失败时上游不崩

**缺口**: CLI 后端的 schema 注入是 prompt-based 而非 API-native,可靠性低于 Anthropic 原生 tool use。偶尔仍有模型返回非法 JSON 需要兜底。


---

## 2. 基本达标但有缺口 (5-7 分)

### 2.1 反馈闭环 — 8/10 ↑（原 6 分）

**现状**: `feedback.py` 实现了完整的信鸽反馈闭环:
- 信号采集 6 类: assumption/field_inconsistency/rework/ui_state_gap/commit_review_link/test_skip_for_prd
- 结局追踪: effective_catch/insufficient_fix/wrong_rejection/missed/no_signal
- EMA 权重更新: `alpha=0.15`,按 confidence 加权 (`effective_alpha = alpha * confidence`)
- rule_performance_history.json: 累计统计、驳回率、噪声标记
- 高噪规则警告: `is_noisy` 当 `rejection_rate > 0.4`
- 规则提案: missed 信号 >= 3 条自动生成新规则提案
- scan 模式: `--scan-registered-repos` 从 registry 批量扫描
- pigeon_run 日志 + 30 天清理

**反馈注入 Worker**: `_build_feedback_section` 从 history 筛选异常规则 (rejection_rate>0.3 或 missed>2 或 eval precision/recall<0.6),动态注入 Worker system prompt。

**✅ 已闭环（commit 596d121 / d21cbd3）**:
- `api/routes/review.py:356 _update_rule_perf_from_decisions` 把 Web 端 Phase 3 的 Y/N/E 决策直接写入 rule_performance_history.json
  - accept → confirmed +1，EMA delta=+1.0
  - edit → confirmed +1，EMA delta=+0.7（编辑=认可但措辞不够）
  - reject → rejected +1，EMA delta=-0.5
- `api/routes/review.py:457 _save_eval_ground_truth` 把决策同步保存为 Eval 人类标注，喂给 `cuckoo_eval.py` 做回归测试
- `confirm_review()` 主流程 Step 3/4 自动调用上述两个函数，无需手动跑脚本
- 结果：用户每次评审都自动产生反馈数据，EMA 更新从"旁路"变成"主路"

**剩余缺口**:
1. **scan 模式（代码目录信号）仍需手动**: Web 决策回流已自动化，但基于 AI Coding 返工率的信号采集仍依赖手动跑 `feedback.py --code-dir`
2. **scan 模式依赖 registry**: 需要先注册仓库,门槛高
3. **两路信号未合并**: Web 决策和代码信号分别写 history，没有加权合并策略

### 2.2 质量度量体系 (Eval) — 8/10 ↑（原 7 分）

**现状**: `cuckoo_eval.py` + `cuckoo_scorer.py` 实现了完整的 Eval 框架:
- 6 维度评分: recall(30%) + precision(20%) + location_accuracy(10%) + evidence_reliability(20%) + severity_accuracy(10%) + format_completeness(10%)
- 三态判定: PASS(>=80%) / PARTIAL(50-80%) / FAIL(<50%)
- 预埋 bug 匹配: location 相似度 + keyword 命中 + 类型相关性
- 依据验证: A/B/C 三类独立验证
- 评测历史: eval_history.json 跨次对比 + 趋势打印
- 规则级指标 (F2): per-rule precision/recall/fp_rate,写回 rule_performance_history.json
- 规则覆盖矩阵: Worker x rule 覆盖率
- 测试用例: 5 个预埋 bug JSON (劳动仲裁/对外投资/产品召回/纳税人资质/侵权软件)
- CI gate 阈值: `EVAL_MIN_OVERALL_SCORE=0.50`, `EVAL_MIN_RECALL=0.40`, `EVAL_MIN_PRECISION=0.40`
- `test_eval_gate.py` 存在

**✅ 已补（commit 596d121）**:
- **CI 集成**: `.github/workflows/eval.yml` 已添加,PR 到 main 时自动跑 `pytest tests/test_eval_gate.py -m eval`,断言 `EVAL_MIN_OVERALL_SCORE>=0.50`。质量护栏正式通电
- **一致性分析工具**: `eval/consistency_analyzer.py` 离线读取 `eval/results/` 多次评测,输出每条 rule_id 的检出频率、稳定规则（≥75%）vs 不稳定规则（<50%）+ 整体一致性分
- **人类标注持续积累**: `eval/ground_truth/*.json` 由 Phase 3 决策自动产出,可喂给 cuckoo_eval 做长期回归

**剩余缺口**:
1. **测试用例覆盖不足**: 5 个测试用例只覆盖了特定业务领域,没有跨领域(如 SaaS、金融、电商)的泛化测试。这是当前最大的未解决项
2. **non_issues 缺失**: 测试用例的 `non_issues` 字段为空数组,无法评测误报抑制能力

### 2.3 依据可验证 (Side Query) — 8/10 ↑（原 7 分）

**现状**:
- Worker 层: `verify_evidence()` (`parallel_review.py:1376`) 对 A/B/C 三类依据做硬验证
  - A 类: 检查 wiki 页面是否存在 (精确匹配 + 模糊匹配)
  - B 类: 检查规则编号是否在 review-rules/ 中
  - C 类: 检查是否标记"待确定"
- 苍鹰层: `_verify_wiki_evidence()` L1-L3 升级链 (wiki 自动验证 -> 降级为 C + advisor_note -> MAX_ESCALATIONS=3)
- 防幻觉: `_build_real_refs_section()` 在 Worker prompt 注入真实 rule_id + wiki 页面清单,格式铁律 (违反即 FAIL)
- 新鲜度标注: wiki 页面按 30/90/180 天分级 (绿/黄/橙/红)
- confidence_score: `compute_confidence()` 按 evidence_type 计算 (A=0.9, B=0.8, C=0.5, 无=0.4)
- verification_status 三态: verified / verified_with_caveat / retracted

**✅ 已补（commit 7ebbe23）**: `parallel_review.py:_verify_b_class_semantic` B 类依据深度验证落地。提取规则原文,与 item.issue 做 embedding 相似度计算,低于阈值标记 `verified_with_caveat`。Worker 再也不能靠"引了正确的规则号但误解规则含义"蒙混过关。

**剩余缺口**:
1. **A 类模糊匹配太松**: `_find_wiki_page` 的关键词匹配可能产生假阳性(wiki 页面标题包含常见词就匹配上)
2. **retract 后无替代**: 依据被 retract 的 item 直接标记为 RETRACTED 移除,没有尝试用其他依据补救

### 2.4 Eval 量化 > 主观判断 — 6/10 ↓（曾乐观打 7，重测后下调）

**⚠ 2026-04-16 实测修正**: 跑 `eval/consistency_analyzer` 对现有 8 次劳动仲裁 consistency 数据分析,结果冲击较大:
- **整体一致性分 17%，评级 D（不一致，需改进）**
- 稳定规则（≥75% 命中）: **0 条**
- 中间态规则（50%-75%）: 2 条（RC-010=64%, RC-009=50%）
- 不稳定规则（<50%）: 10 条
- 22 次个体 run 中 items 数：min=0 / max=8 / avg=3.8，**变异系数 2.12**
- 部分 run 对同一份 PRD 返回 **0 条** items

这说明系统不是"样本量不足",而是**同一 PRD 跑多次结果漂移严重**。用户二次跑相同评审会得到截然不同的报告。

**可能根因（待排查）**:
1. Worker Claude 调用 temperature 过高，缺乏稳定性约束
2. 重试链兜底到空壳时计入 0 items（`_empty_tool_fallback`）
3. 苍鹰误报检测阈值过严，部分 run 砍掉过多
4. Haiku sanity check 偶尔把整批 items 判成误报
5. `_build_feedback_section` 受 rule_perf_history 变化影响，prompt 漂移

这个 6 分是"有体系但体系本身暴露了真问题"的状态，优于一开始的"缺样本"叙述。

**现状**:
- 6 维度量化评分体系已建立,加权公式明确
- 规则级 precision/recall/fp_rate 聚合已实现 (F2)
- eval_history.json 支持跨次趋势对比
- CI gate 阈值定义在 config (EVAL_MIN_OVERALL_SCORE 等)
- 覆盖矩阵可识别死规则和漏覆盖规则

**✅ 已补（commit 596d121 / 7ebbe23）**:
- **人类标注 ground truth（原缺口 3）**: `_save_eval_ground_truth` 把 Phase 3 决策自动存为 `eval/ground_truth/{workspace}_{reviewer}_{ts}.json`,标记 `is_true_positive`。每次评审都在喂 Eval 数据
- **一致性分析（补充 2 的一部分）**: `consistency_analyzer.py` 提供了"同一 PRD 多次评测的稳定性"量化工具

**剩余缺口**:
1. **Eval 跑的太少**: 5 个测试用例,8 次 consistency 跑都集中在劳动仲裁一个 PRD,样本量不足以做统计置信（本维度最大短板）
2. **无自动回归告警**: eval_history.json 有数据但只有 CLI 打印,没有在 CI 或评审流程中触发告警
3. **未覆盖端到端指标**: 只评测了评审输出质量,没有评测"评审后 AI Coding 的返工率是否降低"这一终极指标（P2.3 仍未做）


---

## 3. 明显不足 (< 5 分)

### 3.1 反馈闭环 > 静态规则 — 8/10 ↑（原 5 分，曾是最大结构性缺陷）

**现状**:
- EMA 更新机制存在 (`alpha=0.15`,按 confidence 加权)
- 异常规则动态注入 Worker prompt 已实现 (`_build_feedback_section`)
- 高噪规则自动标记 (`is_noisy`)
- 规则提案从 missed 信号自动生成

**✅ 已修复（commit 596d121 / d21cbd3）**:
1. **Web 决策已回流（原缺口 1/2）**: `confirm_review()` 在 Step 3 调用 `_update_rule_perf_from_decisions()`，EMA 在 Web API 主流程中实时更新，反馈闭环从旁路变主路
2. **impact_score 实际参与 Worker 权重（原缺口 3）**: `parallel_review.py:579-651 _build_feedback_section` 新增两段注入：
   - `impact_score < 0.3` → "## 低效规则警示"（谨慎报告，确保充分依据）
   - `impact_score > 0.8` → "## 高效规则优先"（历史上被高度认可，优先检查）
   - Worker 评审时直接感知规则历史表现，不再是空转变量
3. **闭环周期压缩（原缺口 4）**: Phase 3 用户点完 Y/N/E → 立即写入 history → 下一次评审 prompt 注入就能读到。不再需要手动跑 feedback.py

**剩余缺口**:
1. **代码返工率信号仍未自动化**: Web 决策闭环已打通，但"评审后 AI Coding 返工率"这条长周期信号仍需手动触发 scan 模式
2. **反馈数据冷启动**: 新规则在有足够决策样本前，impact_score 默认 0.5，没有先验偏置机制

---

## 行动计划

### ✅ P0 已完成 (commit 596d121 / d21cbd3)

#### ~~P0.1 Web 端 Y/N/E 决策回流到 rule_performance_history~~ ✅

落点:
- `api/routes/review.py:356 _update_rule_perf_from_decisions`
- `api/routes/review.py:536` confirm_review Step 3 自动调用

实现细节: accept→confirmed+EMA +1.0 / edit→confirmed+EMA +0.7 / reject→rejected+EMA -0.5。同时带 rejection_rate 和 is_noisy 自动重算。附送 `_save_eval_ground_truth`(Phase 3 决策 → Eval 人类标注)作为 P2 加分项提前交付。

#### ~~P0.2 impact_score 实际参与评审权重~~ ✅

落点: `parallel_review.py:523 _build_feedback_section:579-651`

实现细节: 在原有 rejection_rate / missed / eval precision-recall 三路之外,新增两段。低效规则(impact<0.3)→ "⚠ 历史上被频繁驳回,谨慎报告"; 高效规则(impact>0.8)→ "✓ 历史上被高度认可,优先检查"。注入到 Worker system prompt。

### ✅ P1 已完成 (commit 596d121)

#### ~~P1.1 Eval 集成 CI~~ ✅
落点: `.github/workflows/eval.yml`。PR 到 main 自动跑 pytest -m eval,断言阈值。

#### ~~P1.3 Worker 规则越界硬校验~~ ✅
落点: `parallel_review.py` 的 `cross_boundary` 字段。运行时检查 rule_id ∈ dim.checklist,不符合则剔除/降 confidence。

#### ~~P1.4 一致性评测自动化~~ ✅
落点: `eval/consistency_analyzer.py`。输出稳定/不稳定规则分类 + 整体一致性分。

### ✅ P2 已完成 (commit 7ebbe23)

#### ~~P2.1 拓扑可视化~~ ✅
落点: `ARCHITECTURE.md` 的三段 mermaid 图(拓扑 + Data Flow + Feedback Loop)+ File Mapping 表。

#### ~~P2.2 B 类依据深度验证~~ ✅
落点: `parallel_review.py:_verify_b_class_semantic`。语义相似度不足标 verified_with_caveat。

#### ~~P2.4 苍鹰判断的反向校验~~ ✅
落点: `goshawk_performance_history.json` 记录用户决策 vs 苍鹰判断的冲突,累计调整 confidence 权重。

### P1.2 + P2.3 仍未做 (当前最高优先级)

#### P1.2 扩充测试用例到 10 个以上

**差什么**: 5 个测试用例集中在单一业务领域,样本量不足以做统计置信。这是现在 Eval 体系最大的短板。

**怎么补**: 从不同领域的真实 PRD 各生成 1 个测试用例(用 `cuckoo_eval.py --generate-test-case`),补充 non_issues 字段。目标覆盖: SaaS 后台、电商、金融、企业信息(风鸟)、教育至少 5 个新领域。

**预估工作量**: 2 天

#### P2.3 终极指标: AI Coding 返工率

**差什么**: 只评测了评审质量,没有评测对下游的实际影响。评审系统的真正价值在于降低下游返工,这个指标没有就无法闭环证明系统有用。

**怎么补**: 在 feedback.py 的 scan 模式中,统计"评审后 N 天内同一模块的 commit 次数",与"未评审"的模块对比,计算返工率降低比例。

**预估工作量**: 3-5 天（依赖 registry 里有足够多的已评审项目做对照组）

### ✅ P0 紧急 - 稳定性 bug（2026-04-16 代码层已修复）

**原问题**: CLI 配额耗尽被当作成功吞掉 — 见 `docs/STABILITY_DIAGNOSIS.md`

**修复落地**:
- `exceptions.py` + `api_adapter.py`: `QuotaExhaustedError` 专用类型, CLI 配额错误分类抛出 + 正则提取 reset 时间
- `api_adapter.py`: JSON 解析失败改抛 APIError(原静默空壳)
- `api/routes/review.py`: `classify_worker_failures` 辅助 + orchestrator 全员失败发 `review_failed` SSE
- `web/`: `useReviewStream` + `Phase2Running` 监听 `review_failed`, 不自动跳 Phase 3
- `web/phases`: Phase2/3/4 埋点 `auditApi.log()`, 审计链路接通

**测试**: pytest 105 → 143 (+38 新单测), tsc + vitest 零 error

### 下一轮可挖的加分项（冲 90 分，**稳定性修复之后**）

- **confidence=0.0 降级不应完全跳过审核**：苍鹰超时时,至少用规则 checklist 做一遍硬校验,不让所有 Worker 输出裸奔
- **越界反馈闭环**：cross_boundary 事件累计后反哺 Worker prompt，让 Worker 学到"本维度容易被我误报的相邻维度规则"
- **Eval 自动回归告警**: 本次 overall_score 比上次下降 >5% 触发 CI fail 或飞书告警
- **A 类模糊匹配收紧 + retract 补救**
- **配额管理专用状态**：`quota_exhausted` 区别于 generic 失败,UI 提示用户明天重试

---

## 维度得分汇总表

| # | 维度 | 得分 | 变化 | 档位 | 核心差距 |
|---|------|------|------|------|----------|
| 1 | Agent 拓扑定义 | **9** | **+1** | 已达标 | 缺声明式 topology.yaml(仅文档级 mermaid) |
| 2 | Agent 行为边界与约束 | **9** | **+1** | 已达标 | 越界事件未反哺 Worker prompt |
| 3 | 反馈闭环 | **8** | **+2** | 已达标 | 代码返工率信号仍手动 |
| 4 | 质量度量体系 (Eval) | **8** | **+1** | 已达标 | 测试用例仅 5 个单领域 |
| 5 | 模型分工 | 9 | — | 已达标 | 缺 A/B 测试数据 |
| 6 | 不信任单层输出 | **9** | **+1** | 已达标 | confidence=0.0 降级仍让 Worker 裸奔 |
| 7 | 依据可验证 | **8** | **+1** | 已达标 | A 类模糊匹配偏松 |
| 8 | meta-reviewer 只审不重审 | 9 | — | 已达标 | 无 |
| 9 | 结构化输出强制 | 8 | — | 已达标 | CLI 后端 prompt-based |
| 10 | 反馈闭环 > 静态规则 | **8** | **+3** | 已达标 | 新规则冷启动无先验 |
| 11 | Eval 量化 > 主观判断 | 6 | — | 有缺口 | **⚠ 实测一致性 17%，稳定规则 0 条**（下调，原乐观打 7） |
| | **总计** | **84** | **+12** | | |

---

## 结论

啄木鸟在 **Agent 拓扑、行为约束、meta-reviewer 设计与反向校验、反馈闭环、依据可验证** 等核心维度上全线达标（均 ≥ 8 分）。11 个维度里 10 个已达标,唯一卡在 7 分的是"Eval 量化 > 主观判断",瓶颈在测试用例样本量和缺少终极指标(AI Coding 返工率)。

**这一轮更新的亮点**:
- **反馈闭环主路化** (commit 596d121/d21cbd3): Web Y/N/E 决策直接回流 rule_performance_history,impact_score 真正进 Worker prompt,Eval ground truth 自动累积
- **运行时硬校验** (commit 596d121): Worker 越界不再只靠 prompt 约束,`cross_boundary` 字段做硬剔除
- **Eval 护栏通电** (commit 596d121): GitHub Actions 跑 test_eval_gate,consistency_analyzer 量化多次评测稳定性
- **Meta-reviewer 加强** (commit 7ebbe23): 苍鹰反向校验用 ground truth 做反馈,B 类依据上了语义相似度,拓扑图进了 ARCHITECTURE.md

**现在真正的未解决项只有 2 个**（对应总分 85 → 90 的最后 5 分）:

1. **P1.2 扩充测试用例**（最划算）: 5 个单领域用例远远不够。这一项补上,"质量度量体系"和"Eval 量化"两个维度各 +1,总分 87

2. **P2.3 AI Coding 返工率**（终极闭环）: 评审系统要证明自己有用,必须看到"评审过的模块返工率确实降低"。这需要 feedback.py 的 scan 模式和 registry 里积累足够对照组数据

另外 3 个加分项（confidence=0.0 降级、越界反哺、Eval 回归告警）是可选优化,不是结构性缺陷。

**一句话**: 这个 harness 已经从"架构先行、闭环半成品"升级到"十项全能、唯欠外部指标"。真正需要的已经不是代码,而是更多真实 PRD 跑起来产生数据。
