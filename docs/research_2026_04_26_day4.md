# Pecker Day4 开源调研 (2026-04-26)

调研对象: Pecker (啄木鸟) PRD 评审 agent —— 4 worker 并行 + 苍鹰终审 + evidence verify + wiki 分级 + 漏斗。
覆盖 5 方向: multi-agent cross-val / evidence verify / PRD review / KB provenance / self-eval observability。
排除已借鉴: kenhuangus/llm-wiki, Ar9av/obsidian-wiki, FSoft-AI4Code/CodeWiki, Tobi Lutke LLM Wiki。

---

## 方向 1 — Multi-agent harness with cross-validation

苍鹰当前是「Opus 单层终审 4 worker」, 单点失败风险高 (P=0.571 / R=0.267 即使 Run 4 历史最佳)。
寻找: 多 reviewer ensemble / 投票 / debate 收敛模式。

### 1.1 Skytliang/Multi-Agents-Debate (557 stars, GPL-3.0, 44 commits)
- 匹配度: 6/10 — 论文级 PoC, "devil/angel" 二元辩论模式简洁可抄, 但 GPL-3.0 不利于内嵌
- 核心模式: 两个对立 agent 独立陈述 → 多轮辩论 → judge 收敛。强调 "tit-for-tat" 防 thinking degeneration
- Pecker 借鉴点: 不直接用代码 (GPL 污染), 抄模式到 `goshawk_advisor.py`。当前苍鹰是单 Opus 评 4 worker, 可加一个 "devil 苍鹰" (Sonnet, 故意挑刺) + "angel 苍鹰" (Sonnet, 故意辩护), 第三个 Opus judge 看辩论结论。具体落地: 在 `goshawk_advisor.py` 的 `GOSHAWK_SYSTEM_PROMPT` 之外, 新增 `_DEVIL_PROMPT` / `_ANGEL_PROMPT`, 跑 1 轮辩论后让现有 Opus 判定。`debate4tran.sh` 的 prompt 模板可对照
- License & 可移植性: GPL-3.0 — 抄思路不抄代码, 不引入依赖
- 风险/不适配: 3 倍成本 + 延迟翻倍, 可能过度。**先做 ablation: 只在 funnel 显示 ev_verify→goshawk 段损耗 > 30% 时启用**

### 1.2 quotient-ai/judges (334 stars, Apache-2.0, **2026-04-02 已 archived**)
- 匹配度: 8/10 — Jury 模式 100% 贴 pecker, 即使 archived 也是 "Replacing Judges with Juries" 论文官方实现, 抄完即可
- 核心模式: `Jury.vote()` 聚合多个 judge → `Verdict`。Classifier (bool) + Grader (Likert) 两套 evaluator, 每个 judge 用不同 prompt + model 跑同一输入, 多数投票
- Pecker 借鉴点: 在 `goshawk_advisor.py` 顶部加 `class GoshawkJury`, 内部跑 3 个 Sonnet (不同 prompt seed, 都用现有 `GOSHAWK_SYSTEM_PROMPT` 但 temperature 错开 0.0/0.3/0.7), 每个产出 `flagged_as_false_positive` list, 投票 ≥2 才算误报。这样把 "苍鹰单 Opus" 变成 "3-judge jury", 对冲 sampling noise (Day3 memory 主根因)。`judges/jury.py` 的 vote 函数 50 行, 直接抄。Apache-2.0 + archived 反而稳定可 fork
- License & 可移植性: Apache-2.0, 兼容
- 风险/不适配: archived 不再修 bug, 自己 fork 维护; 3x 调用成本, 但 Sonnet < Opus 实际可能持平

### 1.3 microsoft/llm-as-judge (24 stars, MIT, 持续维护)
- 匹配度: 7/10 — Judge Assembly 概念跟苍鹰目标完全对齐, 但 star 少未经实战
- 核心模式: 多个 specialized judge 组成 Assembly, 每个 judge 评估不同维度, 最后聚合。对比 Super Judge (单大 judge) 二选一架构
- Pecker 借鉴点: 现有 4 worker (data_quality/quality/structure/ai_coding) 本质就是 4 个 specialized judge, 苍鹰是 Super Judge 模式。可以借鉴 `src/app/judges/` 的 schema 拆分: 每个维度有自己的 evaluation schema, 苍鹰对各维度独立调一遍 mini-review 而不是一次评 4 worker 全集。落地: `goshawk_advisor.py` 新增 `_review_per_dimension()`, 4 次小 LLM call 替代 1 次大 call, 减少 long context 衰减
- License & 可移植性: MIT, FastAPI/Python 同栈
- 风险/不适配: star 数低 (24) 反映成熟度; 调用次数 ×4

---

## 方向 2 — Evidence verification / claim-grounded LLM

`review/evidence_verify.py` 当前只查 wiki 文件名 + rule_id 字符串匹配。痛点: 拿不到 entailment 级别的判断, NLI 设计上线但 sparse 场景永不触发 (Day3 evening memory)。

### 2.1 ritun16/chain-of-verification (CoVe 主流实现, MIT)
- 匹配度: 9/10 — 4 步 CoVe 模式 (baseline → plan questions → answer → refine) 跟 pecker "worker → ev_verify → goshawk → PM" 同构, 借鉴空间最大
- 核心模式: LLM 先答 → LLM 自己生成 verification questions → 独立回答这些 questions (可走 RAG) → 用 verification 结果改写原答。3 chain types: WikiData / Multi-Span QA / Long-Form QA
- Pecker 借鉴点: 当前 `evidence_verify.py` 只做了 CoVe 的第 1+3 步。要补第 2 步 — 让苍鹰对每条 review item 生成 2-3 个 verification questions (e.g. "PRD 第 X 段真的没说明这个吗?"), 然后 separate Sonnet call 在 PRD 全文 + wiki 上回答。具体改: `review/evidence_verify.py` 新增 `generate_verification_questions(item)` + `answer_verification(question, prd_text, wiki_index)`, 把 verified_with_caveat 的 22 条 (Day3 fengniao v3) 真正拉到 verified 或 retracted。仓库 `chain_of_verification/` 目录代码 200 行可直接 port
- License & 可移植性: MIT, Python + LangChain (我们自己 wrap 即可不依赖 LangChain)
- 风险/不适配: ×3-5 LLM call; verification question 生成本身可能编, 需要 schema enum (我们 Day3+ 已有这套设施)

### 2.2 explodinggradients/ragas (13.7k stars, Apache-2.0, v0.4.3 2026-01)
- 匹配度: 9/10 — Faithfulness metric 是业界 claim-decomposition 基准, 跟 pecker EV-01 完全同向
- 核心模式: 把 generated answer 拆成 atomic statements → 每条 statement 跟 retrieved context 跑 entailment → 算 supported/total。**双 judge prompt 平均** 抗 prompt sensitivity 是 RAGAS 独家
- Pecker 借鉴点: 当前 review item 的 "依据" 字段是整句 free text, 没拆成 atomic claim。借鉴 `ragas/metrics/_faithfulness.py` 的 `_create_statements_prompt`, 在 `review/evidence_verify.py` 新增 `_decompose_to_atomic_claims(evidence_text)`, 把 "PRD 第 3 章未说明 SLA, 见 wiki/api/sla.md" 拆成 ["PRD 第 3 章未说明 SLA", "wiki/api/sla.md 里有 SLA 定义"] 两条独立 claim, 每条单独 verify。**双 judge prompt 抗 sampling noise 这点直接抄**, 跟 Day3 P0-2 WORKER_SEED 思路同源
- License & 可移植性: Apache-2.0, pip 装就能跑, 也可只抄关键 prompt + 解析逻辑
- 风险/不适配: RAGAS faithfulness 在 hard negative (entity-swap) 上仍 fail (基准研究), 知道边界用; 默认 GPT-4o, 我们改 Sonnet

### 2.3 confident-ai/deepeval (15k stars, Apache-2.0, v3.9.7 活跃)
- 匹配度: 8/10 — pytest-style 跟 pecker 测试栈完全合, FaithfulnessMetric 实现独立可调
- 核心模式: Decompose context to statements → LLM 对每条 statement verdict (Yes/No/IDK) → 算分。"Pytest for LLMs" 集成 CI 是亮点
- Pecker 借鉴点: 直接 `pip install deepeval` + 在 `tests/test_evidence_verify_*.py` 加一组 `@deepeval.assert_test` 测试用例, 不用自己造解析。具体: 新增 `tests/test_evidence_verify_faithfulness.py`, 把现有 calibration suite 的真业务 PRD ground truth 喂进去, 拿 FaithfulnessMetric 跑 baseline, 后续每次 sprint 跑 regression。落地零成本, 直接补 CI gate
- License & 可移植性: Apache-2.0, pytest 原生
- 风险/不适配: DeepEval 的 statement decomposition 在 golden context 给 0.46 (基准研究) 偏低, 跟 RAGAS 互补但不能单用; 调用 OpenAI 默认, 改 Anthropic 需要 wrap

---

## 方向 3 — Spec / PRD review agents (直接竞品)

### 3.1 github/spec-kit (90.8k stars, MIT, v0.8.1 2026-04-24)
- 匹配度: 7/10 — 大方向贴 pecker (spec-driven dev), 但是 generation 流程不是 review 流程, 借鉴 schema 而非 pipeline
- 核心模式: `/specify` → `/plan` → `/tasks` 三段式 slash command, 每段产出 markdown 契约。强调 "spec is contract", 跟 pecker 强调 "wiki is canonical source" 同源
- Pecker 借鉴点: spec-kit 的 `templates/spec-template.md` / `plan-template.md` 是 PM 写 PRD 的标准结构, 可以反向用作 pecker 的 PRD 章节完整度 checklist。具体: 把 spec-kit 的 spec.md 里 "User Scenarios", "Functional Requirements", "Acceptance Criteria" 等 section, 写进 `review/dimensions.py` 的 `_DEFAULT_REVIEW_DIMENSIONS`, 给 structure worker 一组 "缺失章节" 检测规则。`/plan` 命令产生的 artifact 列表 (research.md / data-model.md / contracts/) 也是 pecker 可以挑战的章节 — "你 PRD 写到这一阶段了吗?"
- License & 可移植性: MIT, 模板纯 markdown
- 风险/不适配: spec-kit 是 vibe-coding 上游 (PRD → code), pecker 是 review 下游 (PRD → critique), 方向相反。不能直接调 spec-kit CLI

### 3.2 Saml1211/PRD-MCP-Server (低 star, 但 validate 接口正合)
- 匹配度: 6/10 — 唯一明确暴露 "validate PRD against best practices" 的 OSS 项目, 但 best-practice 库浅
- 核心模式: MCP server 提供 `generate_prd` + `validate_prd_document` 两个 tool, validate 走 LLM-as-judge + 内置 rule list
- Pecker 借鉴点: 看它的 `validate_prd_document` 实现, 它是怎么把 best practice 列表喂给 LLM 的 schema 设计 — 我们当前 `review/dimensions.py` 是 yaml + jsonschema, 它可能是更轻量的 markdown checklist。如果它的 best-practice list 比我们覆盖广, 直接合并到我们的 review-rules
- License & 可移植性: 检查 repo (未明确)
- 风险/不适配: star 数低, 实战未验证; 是 generator 主导, validate 是附属

### 3.3 该方向无更好开源 — Paska (NLP requirements smell, 2305.07097) 是论文 + closed source
- 检索结论: NLP requirements smell detection (ARM / QuARS / Paska / TAPHSIR) 多为 closed-source 学术原型, 没有 active GitHub repo。**该方向开源稀缺**, 反而说明 pecker 是 underserved 市场, 借鉴模式靠论文而非代码

---

## 方向 4 — Knowledge base provenance & lineage

### 4.1 trungdong/prov (W3C PROV Python 实现, 多年维护, Apache-2.0)
- 匹配度: 8/10 — W3C PROV 是 provenance 国际标准, pecker frontmatter v2 (authority/sources/verified_by/last_verified) 应该往这个标准靠
- 核心模式: `Activity` (动作) / `Entity` (产物) / `Agent` (执行者) 三元组 + `wasGeneratedBy` / `used` / `wasInformedBy` 关系。可序列化为 PROV-N / PROV-O (RDF) / PROV-JSON / PROV-XML
- Pecker 借鉴点: 当前 wiki frontmatter 是自创字段, 升级成 PROV-JSON 子集。具体: `review/evidence_verify.py` 输出的 `verified_by` / `last_verified` / `sources` 改用 PROV 词汇 — `prov:wasGeneratedBy` (哪个 worker LLM call) / `prov:used` (哪些 wiki page) / `prov:wasInformedBy` (上游 ev_verify session id)。这样 pecker 的 lineage 可以被任何支持 W3C PROV 的工具消费, 比如未来接 DataHub / Marquez。落地: 新增 `review/provenance.py`, 用 trungdong/prov 序列化每条 review item
- License & 可移植性: Apache-2.0, `pip install prov`, Python 原生
- 风险/不适配: PROV 表达冗长, 单条 review item 多 200 字符 metadata, 但只在 archive 时输出, 不影响 in-flight; 学习曲线一天内可吃透

### 4.2 Flowcept (LLM Agents for Workflow Provenance, MIT, arXiv 2509.13978v2)
- 匹配度: 7/10 — 第一个把 LLM tool call 完整映射到 W3C PROV 的工程实现, 跟 pecker agent topology 高度同构
- 核心模式: 每个 tool 调用 = `prov:Activity` 子类, args = `prov:used`, result = `prov:generated`, LLM 交互独立记录, 用 `prov:wasInformedBy` 串起 tool exec → LLM call。Agent 本身是 `prov:Agent`
- Pecker 借鉴点: 抄它的 schema 而非代码 — 我们 4 worker 各 1 次 LLM call, 苍鹰 1 次, ev_verify N 次。每次都对照 Flowcept 的 PROV mapping 出 lineage record。具体: `agent_session_log.py` (如果有) 或 logger 输出加一份 `.prov.jsonl`, 每行一条 PROV statement, archive 在 `output_archive_*/`。这样 funnel report 不再是单维 5 层, 而是完整 DAG, PM 可以看 "R-007 是怎么从 raw → PM 的具体每步"
- License & 可移植性: MIT
- 风险/不适配: PROV graph DAG 渲染需要单独工具 (Graphviz / d3), 不是开箱; pecker 现有 funnel 已经够 PM 看, 这是锦上添花

---

## 方向 5 — Self-evaluating LLM systems

### 5.1 langfuse/langfuse (26.1k stars, MIT, v3.170.0 2026-04-23 极活跃)
- 匹配度: 9/10 — 自托管 + LLM-as-judge + prompt versioning + score feedback loop, pecker 缺啥它有啥
- 核心模式: Trace SDK 埋每次 LLM call → 后台跑 LLM-as-judge / 用户标注 / 自定义 eval pipeline → score 反哺 prompt management → CI gate 决定 prompt 升不升级
- Pecker 借鉴点: 当前 pecker 的 funnel + rule_perf + reject_reason 是手搓 observability, 全可以替换成 Langfuse trace + score。具体: 1) `parallel_review.py` 每次 worker call 用 `langfuse.trace()` 包起来 2) `review/evidence_verify.py` 的 verified/caveat/retracted 用 `langfuse.score()` 写回 trace 3) 现有 `scripts/funnel_report.py` 改为查 Langfuse API 4) `review-rules/*.yaml` 用 Langfuse Prompt Management, 每次 sprint 改规则走 prompt version + AB。**Langfuse Prompt Management 直接解决 pecker 当前 "rule precision_7d 怎么反哺规则" 的开放问题** — 它的 prompt link to traces 就是答案
- License & 可移植性: MIT (除 ee 目录), Docker Compose 自托管 5 分钟起
- 风险/不适配: 引入 Langfuse 是大动作, 数据搬迁 + 团队学习; 当前 pecker funnel 已经能用, 投入产出比要看 PM 是否需要长期数据 dashboard。**Day4 不上, 但写进 Day5+ 路线图**

### 5.2 UKGovernmentBEIS/inspect_ai (2k stars, MIT, 5441 commits 极活跃, Anthropic 实际用户)
- 匹配度: 9/10 — Anthropic / DeepMind / Grok 都用, 跟 pecker 测试需求 1:1 贴
- 核心模式: `Task` (评什么) / `Solver` (怎么做) / `Scorer` (怎么打分) 三元抽象, scorer 可以 compose multi-step agent。200+ pre-built evals 包含 honesty / jailbreak / agent eval
- Pecker 借鉴点: pecker 的 calibration suite (真业务 PRD ground truth + multi-run overlap) 完全可以重写成 inspect_ai Task。具体: 新增 `evals/pecker_consistency.py`, 定义 `@task def pecker_consistency()` 跑 3-PRD 基线 (劳动仲裁 77.6%/风鸟诉前 76.2%/积分抵扣 83.6%), `Scorer` 计算 N0 数 + overlap%。这样 sprint 每天跑 `inspect eval evals/pecker_consistency.py --model claude-sonnet-4-6`, 比手工跑 3 轮可控。借鉴文件: `inspect_ai/scorer/_metric.py` 看怎么自定义 scorer
- License & 可移植性: MIT, Python only, 不绑架构
- 风险/不适配: inspect_ai 偏向 single-shot eval, pecker 是 multi-agent pipeline, scorer 拼装需要工程量; **但是 Day3+ memory 提到 "consistency 多轮跑必须手动清 sessions, --resume skip 不可靠", inspect_ai 的 isolated task runner 正好治这个痛点**

### 5.3 promptfoo/promptfoo (20.6k stars, MIT, 0.121.8 2026-04-24 极活跃, 已 OpenAI 收购仍开源)
- 匹配度: 8/10 — YAML config + CLI + GitHub Action diff, 跟 pecker GitOps 风格匹配
- 核心模式: `promptfooconfig.yaml` 声明式定义 prompts × providers × tests × assertions, CLI 跑 + 输出 PR diff (before/after eval matrix)
- Pecker 借鉴点: 比 inspect_ai 更轻, 适合做 pecker 的 "rule 改动 PR gate"。具体: 新增 `.promptfoo/pecker_rules.yaml`, 把 `review-rules/*.yaml` 每条规则做成一个 test case (输入: 含/不含违规的 PRD 片段, 期望: pecker 是否触发该规则), GitHub Action 在改 review-rules 的 PR 上自动跑, PR 评论里显示 precision/recall 变化。**这是 pecker 当前缺的 rule lifecycle 闭环最后一公里**, 比自己写 funnel_report 阅读门槛低
- License & 可移植性: MIT, Node.js + YAML, 跟 pecker Python 栈隔离干净 (走 CLI)
- 风险/不适配: Node.js 依赖; promptfoo 偏向 prompt 测试不是 agent 测试, 对苍鹰这种多 worker 拓扑表达力有限; 跟 inspect_ai 二选一即可

---

## 综合 Top 5 推荐 (跨方向, 按落地优先级)

1. **explodinggradients/ragas (方向 2)** — 抄 faithfulness 的 atomic claim decomposition + 双 judge prompt 平均到 `review/evidence_verify.py`, **这是当前 22 条 verified_with_caveat 真正变可信的最短路径**, 1 周可落地
2. **quotient-ai/judges 的 Jury 模式 (方向 1)** — 苍鹰单 Opus → 3-Sonnet jury, 直接对冲 Day3 sampling noise 主根因 (rule_id `merged_to_facet` 浮动 125%)。代码 50 行 fork, 2 天可落
3. **UKGovernmentBEIS/inspect_ai (方向 5)** — 把 calibration suite 重写成 inspect Task, 解决 "consistency 多轮跑必须手动清 sessions" 顽疾, 同时 sprint 后能拿到 Anthropic 自己用的 eval 框架。3-5 天落
4. **ritun16/chain-of-verification (方向 2)** — CoVe 第 2 步 (verification questions) 是 pecker 唯一缺的 ev_verify 完整环节, 跟 ragas 方向互补 (ragas 拆 claim, CoVe 生成 question), 同 sprint 可一起做
5. **trungdong/prov (方向 4)** — wiki frontmatter v2 升级成 W3C PROV-JSON 子集, 是 long-term 标准化关键。**不紧急但战略**, 在加新字段前先做, 后期接 Marquez/DataHub 不用迁移

## 不推荐 (避坑)

- **Skytliang/Multi-Agents-Debate** — GPL-3.0 不能内嵌, 思路抄即可不引依赖。Star 557 ≠ 成熟
- **microsoft/llm-as-judge (24 stars)** — 概念对但实战未验证, FastAPI/Azure 包袱重, 不如自己实现
- **Saml1211/PRD-MCP-Server** — best-practice 库浅, validate 接口浅, 不如直接抄 spec-kit 模板
- **Langfuse Day4 不上** — 大投入大产出, 但 pecker 现有 funnel 够用, 进 Day5+ 路线图避免 Day4 失焦
- **promptfoo vs inspect_ai 选 inspect_ai** — Anthropic 自家用, 多 agent 表达力强, Node 依赖坑

## 意外发现

1. **Requirements smell detection 学术圈活跃但开源稀缺** — Paska/QuARS/ARM/TAPHSIR 论文 100+ 引用但全 closed source, **pecker 是这个细分赛道少有的可上线 OSS 候选**, 论文里 12 类 weak phrase 可以直接抄进 `review-rules/quality.yaml`
2. **W3C PROV 已是国际标准但 LLM 圈无人用** — Flowcept (arXiv 2509.13978v2, 2026-09) 是首个把 LLM tool call 映射 PROV 的工程实现, **pecker 现在抄等于早期采用, 后续接生态不用迁移**
3. **judges (quotient-ai) Jury 模式 2026-04 archived** — Apache-2.0 反而稳定可 fork, 不是坏事
4. **inspect_ai 的 Task/Solver/Scorer 三元抽象跟 pecker dimensions/worker/goshawk 完全同构** — 几乎是为 pecker 这种系统设计的, 早接早赚
5. **Anthropic / DeepMind / Grok 内部都用 inspect_ai** — pecker 既然主要跑 Anthropic 模型, 用 inspect_ai 比自造 eval 框架降维打击

---

## 来源链接

- [Skytliang/Multi-Agents-Debate](https://github.com/Skytliang/Multi-Agents-Debate)
- [quotient-ai/judges](https://github.com/quotient-ai/judges)
- [microsoft/llm-as-judge](https://github.com/microsoft/llm-as-judge)
- [ritun16/chain-of-verification](https://github.com/ritun16/chain-of-verification)
- [explodinggradients/ragas](https://github.com/explodinggradients/ragas)
- [confident-ai/deepeval](https://github.com/confident-ai/deepeval)
- [github/spec-kit](https://github.com/github/spec-kit)
- [Saml1211/PRD-MCP-Server](https://github.com/Saml1211/PRD-MCP-Server)
- [trungdong/prov](https://github.com/trungdong/prov)
- [LLM Agents for Workflow Provenance (Flowcept, arXiv 2509.13978v2)](https://arxiv.org/html/2509.13978v2)
- [langfuse/langfuse](https://github.com/langfuse/langfuse)
- [UKGovernmentBEIS/inspect_ai](https://github.com/UKGovernmentBEIS/inspect_ai)
- [promptfoo/promptfoo](https://github.com/promptfoo/promptfoo)
- [Paska — Automated Smell Detection in NL Requirements (arXiv 2305.07097)](https://arxiv.org/abs/2305.07097)
- [Multi-Agent Debate for LLM Judges with Adaptive Stability Detection (arXiv 2510.12697)](https://arxiv.org/html/2510.12697v1)
- [Replacing Judges with Juries (judges 库 jury 模式来源)](https://www.databricks.com/)
- [Karpathy LLM Wiki gist](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f)
