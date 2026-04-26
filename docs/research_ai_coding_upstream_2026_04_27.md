# Pecker 第二轮 GitHub 调研 — AI coding 上游 spec 注入器方向 (2026-04-27)

> 背景: 三工况对照实验印证 Pecker 真护城河是 **lineage_quality (5 vs B/C 的 3/4)** + **ambiguity_handling (5 vs 4/4)**, 不是 field_correctness. PM reframe 为 "AI coding pipeline 上游 spec 注入器", 围绕这一定位调研 5 个新方向.

> 调研时点: 2026-04-27 / 数据来源: GitHub + arXiv + 厂商 blog / 已剔除 Day4 重复

---

## 方向 1 — Spec-to-Code Pipeline (上游 spec → 下游 implement)

### 1.1 [Fission-AI/OpenSpec](https://github.com/Fission-AI/OpenSpec) (43k ★, v1.3.1 = 2026-04-21, MIT)
- **匹配度**: 9/10 — 与 Pecker 定位最相近, 主打"在写代码前先达成 spec 共识", 且与 Spec Kit 不同的是有明确 **delta spec** 概念 (ADDED/MODIFIED/REMOVED 三态), 这恰好是 Pecker 评审输出的天然语义
- **核心模式**: `propose → apply → verify → archive` 四阶段, `/opsx:verify` 做三维一致性检查 (COMPLETENESS / CORRECTNESS / COHERENCE), `/opsx:bulk-archive` 检测多个 spec 的冲突 (e.g., "add-dark-mode 和 update-footer 都改了 specs/ui/")
- **Pecker 借鉴点**:
  - 改 `output/<run>/review_items.json` schema, 给每条 review_item 增加 `delta_type: ADDED|MODIFIED|REMOVED|FLAGGED`, 直接对齐 OpenSpec delta 格式 → 下游 implement agent 可消费
  - 仿 `/opsx:verify` 三维分类, 把现有 review_items 的 severity 拆成 completeness/correctness/coherence 三轴 (R-016 类型不一致 = COHERENCE, R-020 缺字段 = COMPLETENESS)
  - 借鉴 `bulk-archive 冲突检测` 思路用到 Pecker 跨 PRD 评审 (B 端版本中多个 PRD 同时改一个 schema 时)
- **License + 可移植性**: MIT, 可直接抄概念. Node 实现, Pecker Python 不能直接 import, 但 markdown 协议层可移植
- **风险/不适配**: OpenSpec 偏 "spec 作为协作合约", Pecker 是"评审已有 PRD", 起点不同; delta 概念需要适配为"评审建议的 delta"

### 1.2 [bmad-code-org/BMAD-METHOD](https://github.com/bmad-code-org/BMAD-METHOD) (~25k ★ 估算, 持续 release 中, MIT)
- **匹配度**: 7/10 — 多 agent 拓扑 (Analyst / PM / Architect / Dev / UX) + 文档逐阶段累积是真正的 "上游 spec 注入" 范本, 但偏完整 SDLC, 不止评审
- **核心模式**: Analysis → Planning (生成 PRD) → Architecture (生成 architecture.md + ERD + API spec) → Implementation, 每阶段产物作为下一阶段 context. `bmad-core/agent-teams/` YAML 定义 agent 编队
- **Pecker 借鉴点**:
  - 仿 `architect agent` 输出 `architecture.md + ERD + API spec` 三件套, 让 Pecker 苍鹰审核完后**输出三件套**给下游 implement, 不是单一 review_items.json
  - `bmad-core/workflows/*.yaml` 编队声明可借鉴: `pecker.workflow.yaml` 把 4 worker + 苍鹰 + 验证拓扑显式化, 现在散在 `core/router.py` 里
- **License + 可移植性**: MIT, 工作流 yaml 可直接借鉴
- **风险/不适配**: BMAD 假设是 greenfield 开发, Pecker 评审场景是 brownfield + PRD 已有, 不是从零生成

### 1.3 [github/spec-kit](https://github.com/github/spec-kit) (91k ★, v0.8.1 = 2026-04-24, MIT)
- **匹配度**: 6/10 — Day4 已收 (重复列出仅因更新到 v0.8.1, 新增 `/speckit.analyze` cross-artifact 一致性命令值得追踪)
- **新增借鉴点**: `/speckit.analyze` 命令在 plan 后 implement 前做 cross-artifact 一致性 + 覆盖度分析, 与 Pecker 苍鹰角色定位相同, 可对照 prompt design

> **方向 1 小结**: OpenSpec 是最该深读的, **建议按 OpenSpec delta_type 重做 review_items schema, 这是 1 周内能落地、对 ai-coding 下游消费立刻显著的改造**.

---

## 方向 2 — Cross-Document Consistency / Cross-Table Validation

### 2.1 [mingjerli/clgraph](https://github.com/mingjerli/clgraph) (3 ★, v0.0.3 = 2025-12-31, MIT)
- **匹配度**: 8/10 — **直接对应 R-016 open_time 跨表类型不一致**这种 case 的算法层. 静态 SQL 解析 + 列级 lineage graph, 不需要 DB
- **核心模式**: `Pipeline → ColumnLineageGraph` 三对象, `trace_column_backward / forward / propagate_all_metadata` 三方法. 列是 node, 转换是 edge, impact analysis = forward trace, root cause = backward trace
- **Pecker 借鉴点**:
  - 新建 `review/cross_table_lineage.py`, 在 PRD 抽出所有 DDL/字段定义后, 用 clgraph 思路构建列级 graph; 对每个字段做 `propagate_metadata({type, nullable, default})`, 一旦同一逻辑列在不同表的 metadata 不一致 → 自动报 R-016 类规则
  - 用作 `worker/data_quality.py` 的算法增强: 现在该 worker 是纯 LLM, 加 clgraph 预扫一遍可显著降漏报
- **License + 可移植性**: MIT, Python, 可直接 `pip install` 集成
- **风险/不适配**: clgraph 当前不显式做"类型不一致"检测, 只做 lineage; 类型对比需要 Pecker 自写 propagation rule. star 数低 (3) 维护风险, 但库简单可 vendor

### 2.2 [Satissss/LinkAlign](https://github.com/Satissss/LinkAlign) (71 ★, EMNLP 2025 Main, MIT)
- **匹配度**: 6/10 — 学术框架, 强项是大 schema 检索过滤(噪声隔离 + foreign key path refinement), 适合 Pecker 处理大型 PRD 含 50+ 表的场景
- **核心模式**: 三步 — multi-round semantic enhanced retrieval / irrelevant info isolation / schema extraction enhancement; 强约束 "predicted tables 必须有 FK 连通路径"
- **Pecker 借鉴点**:
  - 该项目 FK path refinement 思路可用于 Pecker 验证"PRD 中 cross-table 关系字段是否在 DDL 里有 FK 配套"; 如果没有就报 P0 风险 (lineage 完整性问题)
  - 多轮检索 + 噪声隔离 prompt 工程可借给 `core/router.py` 处理大 PRD 时的 chunk 选择
- **License + 可移植性**: MIT, Python, 但是科研代码, 工程化要适配
- **风险/不适配**: 偏 text-to-SQL, 不直接做 cross-document 验证

### 2.3 (空白宣告) — **该方向真无成熟"PRD/Spec 跨文档一致性"开源工具**
- 检索结论: OpenAPI 工具 (Spectral / openapi-spec-validator) 都是单文档级; spec-kit `/speckit.analyze` 是 prompt-driven 不是 graph-driven; 数据库领域有 dbt/sqlmesh 但偏纯 schema 不含 PRD 文本
- **战略判断**: **方向 2 是 Pecker 的真空白**. 目前没人把"PRD 文本 + DDL + API spec + UI 设计"拼成图后跨文档跑 lineage. **Pecker 在这个点上有 OSS 早期采用红利**, 是 5 个方向里 OSS 价值最高的

---

## 方向 3 — LLM Code Lineage Tracking (code → spec rule_id 反向追踪)

### 3.1 [langroid/langroid](https://github.com/langroid/langroid) (~3.6k ★ 估算, 活跃, MIT)
- **匹配度**: 7/10 — 多 agent 框架内置 message-level provenance + RewindTool, 是"消息级 lineage"的成熟实现
- **核心模式**: `Task` 模块自动记录 message 依赖, `RewindTool` rewind 到第 N 个之前消息时自动清空所有依赖消息. 实现在 `langroid/agent/tools/rewind_tool.py`
- **Pecker 借鉴点**:
  - 抄 RewindTool 数据结构到 `output/<run>/lineage.jsonl`: 每条 review_item 带 `parent_msg_ids[]` + `tool_call_id`, 让下游 implement 时记录 "代码行 X 来自 review_item Y 来自 worker Z 的 message N"
  - 改 `core/audit_logger.py`, 借鉴 langroid 的 message provenance schema, 让 Pecker audit 链对齐
- **License + 可移植性**: MIT, Python, 可直接拿 schema 用
- **风险/不适配**: langroid 是消息层 lineage, Pecker 需要 spec→code 的跨进程 lineage, schema 要扩展

### 3.2 [arXiv 2506.16440 + Alor-e/evaluating-llm-doc-code-traceability](https://arxiv.org/abs/2506.16440) (3 ★, 2025-07, License 未明)
- **匹配度**: 7/10 — Claude 3.5 Sonnet 在 doc-to-code traceability 上 F1=79.4-80.4%, 比 TF-IDF/BM25/CodeBERT 高一截. 论文+小型实证仓库
- **核心模式**: one-to-many 匹配策略, prompt 把 doc 段 + 代码 artifact list 一起喂 LLM, 评估 trace link / explanation quality / multi-step chain
- **Pecker 借鉴点**:
  - 实现 `cli/lineage_check.py`: 给定 review_items.json + 实现后的 code diff, 调 Claude 跑 doc-to-code trace, 反向标注每行代码对应的 rule_id
  - 论文报告 IAE (Implicit Assumption Errors) 是最常见错误 (e.g., 因命名相似就假设继承), 给 Pecker prompt 加防御性约束: "禁止仅凭命名相似建立 trace link"
- **License + 可移植性**: 论文 + 实证, 方法论可移植
- **风险/不适配**: 是 evaluation 论文不是工具, 需要 Pecker 自己实现

### 3.3 [MassGen Issue #881 (changedoc proposal)](https://github.com/massgen/MassGen/issues/881) (issue, 未实现)
- **匹配度**: 5/10 — 只是 RFC, 但**问题描述与 Pecker 痛点 100% 对齐**: "现有工具 (Cursor / Spec-Kit / Kiro) 都只追踪 attribution 或 requirements, 没人捕捉 'spec→implementation 的推理链, 经多视角辩论精炼后的版本'"
- **核心模式**: changedocs as tuple `(answer, updated_spec, updated_changedoc)`, agent j 看 agent i 的输出后继承并修改 spec 与 changedoc
- **Pecker 借鉴点**:
  - 这个 issue 实际上**正在描述 Pecker 苍鹰应该输出的东西**. 把 Pecker `goshawk.py` 的输出从 `final review` 升级为 changedoc tuple `(updated_review_items, updated_evidence_chain, decision_rationale)`, 让下游 ai-coding 工具 (cursor/aider) 直接消费
- **License/可移植性**: 仅是 RFC
- **风险/不适配**: 没人实现, Pecker 抄概念即可

> **方向 3 小结**: 没有成熟工具, 最相关的反倒是 MassGen 一个 RFC issue. 这是 Pecker **第二个 OSS 早期采用红利**. 落地优先级: langroid schema 抄出 + Alor-e 论文反向 trace 工具.

---

## 方向 4 — Domain-Specific Rule Libraries (DSL for spec validation)

### 4.1 [open-policy-agent/gatekeeper-library](https://github.com/open-policy-agent/gatekeeper-library) (~1k ★, 持续维护, Apache-2.0)
- **匹配度**: 8/10 — 这是**业内最成熟的"领域规则库 + 自动化 release"标杆**. 严格 SemVer (minor = backward-compat 改, patch = simple 改), `make generate` 自动生成 template.yaml + artifacthub-pkg.yml, 与 Pecker FN 风鸟 10 条规则的发布需求高度对齐
- **核心模式**: `src/<policy-name>/src.rego` + `src_test.rego` 双文件, gomplate 渲染. 每条规则有独立的 `manifest.yaml` 描述 metadata (severity/applies_to/version)
- **Pecker 借鉴点**:
  - **核心借鉴**: 把 `output/wiki/external_canonical/` (FN 风鸟 10 条规则) 改造成 gatekeeper 风格的 `rules/<rule_id>/manifest.yaml + body.md + test.yaml` 三件套, 然后用 Makefile 一键生成 wiki + reject_rate 监测
  - SemVer 严格执行 → memory 中的 `rule_lifecycle` (auto-deprecation by reject_rate) 落地依据
  - artifacthub 模式给 Pecker 多 PRD/多业务场景规则共享提供模板
- **License + 可移植性**: Apache-2.0, Rego 不能直接用 (Pecker 是自然语言+LLM), 但目录结构 + Makefile + manifest schema 全部可移植
- **风险/不适配**: 真正的 Rego 引擎不能用 (Pecker 规则是自然语言 + LLM judge), 需要替换执行引擎

### 4.2 [aatakansalar/yaml-opa-llm-guardrails](https://github.com/aatakansalar/yaml-opa-llm-guardrails) (5 ★, ~活跃, MIT)
- **匹配度**: 7/10 — YAML 写规则 + 自动编译 Rego + FastAPI middleware 拦截 LLM 输出, 与 Pecker "PM 写自然规则 + 后端编译为 LLM-judge prompt" 同构
- **核心模式**: YAML schema (`name / description / type / action / priority / enabled`) 加 type-specific fields → Jinja2 渲染 Rego → 打成 OPA bundle. FastAPI middleware 拦截 `/v1/chat/completions` 等 LLM endpoint
- **Pecker 借鉴点**:
  - **直接抄 YAML schema** (rule type / action / priority / enabled), 给 FN 风鸟 10 条规则提供结构化语法替代当前自由文本
  - **Pecker 评审本身就是个 middleware**, 借鉴 FastAPI middleware 模式做 `pecker proxy` 拦截 implement agent 请求, 注入 review_items 作为 prompt context
- **License + 可移植性**: MIT, Python, 可直接借
- **风险/不适配**: star 5, 很新, 不能 vendor 依赖, 抄概念即可

### 4.3 [DecisionsDev/rule-based-llms](https://github.com/DecisionsDev/rule-based-llms) (52 ★, 48 commits, Apache-2.0)
- **匹配度**: 6/10 — IBM ODM/ADS 商业规则引擎 + LLM hybrid 范本. 对 Pecker 启示: **当 PM 规则确定性强时, 不该让 LLM 复读, 直接调规则引擎**
- **核心模式**: chatbot 双模式 — LLM-only (RAG) vs Decision Services (LLM 提取参数 + 调规则服务 + 合成回答). LLM 退化为参数抽取器
- **Pecker 借鉴点**:
  - 给 Pecker 加 `rule_engine_dispatcher.py`: 简单结构化规则 (字段缺失/枚举校验) 走规则引擎, 复杂语义规则 (跨章节一致性) 才走 LLM. 现在所有规则都走 LLM, 浪费 token
- **License + 可移植性**: Apache-2.0, 但绑 IBM ODM, 不可直接 vendor; 思路可借
- **风险/不适配**: 商业引擎依赖

### 4.4 (补) [openvalidation/openvalidation](https://github.com/openvalidation/openvalidation) (~250 ★, 维护稳定, Apache-2.0)
- **匹配度**: 5/10 — 自然语言 DSL → Java/C#/JS/Python 多语言代码生成. 比 LLM 早, 但语法+grammar 约束严格, **比 LLM 更确定性**
- **Pecker 借鉴点**: 给 Pecker 规则库加可选的"DSL 语法约束模式", PM 写规则时 IDE 自动补全可允许的 token, 减少自由文本歧义
- **风险**: PM 不可能学新 DSL, 现实落地难

> **方向 4 小结**: gatekeeper-library 是金标准, 必须借鉴目录结构 + Makefile + manifest schema. yaml-opa-llm-guardrails 给 YAML 规则 schema 模板.

---

## 方向 5 — Multi-Sample LLM Consensus / DAR 学术深化

### 5.1 [arXiv 2510.01499 — Beyond Majority Voting (OW + ISP)](https://arxiv.org/abs/2510.01499) (2025-10)
- **匹配度**: 9/10 — **直接对应 Pecker 苍鹰聚合算法的下一代升级**. 提出 Optimal Weight (OW) + Inverse Surprising Popularity (ISP) 两算法, 利用 second-order info (模型间 correlation), 在 UltraFeedback / MMLU / ARMMAN 数据集上**一致超过 majority voting**
- **核心思想**:
  - 传统 majority vote 假设 model 独立 (Condorcet), 同质模型违反假设导致 correlated errors
  - **OW**: 给每个模型一个学到的权重, 而不是等权
  - **ISP**: 不是奖励多数, 而是奖励"出乎意料地受支持"的少数派 (Bayesian truth serum 思路)
- **Pecker 借鉴点**:
  - 改 `goshawk/aggregator.py`: 当前 DAR 是 `{majority:3, unanimous:2}` 静态阈值, 升级为 ISP 加权: 多数派但 confidence 低 → 降权; 少数派但 evidence 强 → 升权
  - 实现 `second_order_correlation_score(worker_i, worker_j)`: 计算两 worker 历史一致率, 一致率高的 pair 投票算 1.5 票而不是 2 票, 防止同质 worker 互锁
- **License**: 论文, 算法可自实现
- **风险/不适配**: 需要离线训练 weight; 冷启动时无 historical correlation 数据, 退回 majority vote

### 5.2 [arXiv 2604.17139 — Token-Level Round-Robin (RR)](https://arxiv.org/abs/2604.17139) (2026-04)
- **匹配度**: 6/10 — 极新论文 (2026-04), 提出 token 级交替生成防止 adversarial majority. 对 Pecker 长期重要, 短期 ROI 低
- **核心思想**: agent 在共享 auto-regressive context 里轮流贡献 token; 把 aggregation 从"线性投票"变成"非线性 operator product"
- **Pecker 借鉴点**:
  - **不建议短期落地**, token-level 协作需要重写 worker 调度, ROI 不高
  - **认知价值**: 论文证明了"response-level 投票在恶意多数下必然崩溃", 给 Pecker DAR 设计加上"adversarial robustness" 这个新维度. **未来如果 Pecker 引入 untrusted external worker, 必须重新设计**
- **风险/不适配**: 实现成本高, 对 closed API model 不可行 (需要 token 级 logprob 控制)

### 5.3 [arXiv 2511.02309 — Inverse-Entropy Weighted Voting](https://arxiv.org/abs/2511.02309) (2025-11)
- **匹配度**: 8/10 — IEW 用 token-level logprob 的 Shannon entropy 计算权重: 推理链熵越低 (越确定) 权重越高. 在 matched compute 下击败 parallel self-consistency
- **Pecker 借鉴点**:
  - Anthropic API 不直接给 token logprob, 但可用 sampling 多次 + 答案 entropy 近似. 改 `goshawk/confidence_score.py`: worker 4 个产出 review_items 列表, 计算列表内部 entropy, 低 entropy worker (产出稳定一致) 在苍鹰投票里加权
- **License**: 论文
- **风险/不适配**: Claude API 没有原生 logprob, 需要近似

### 5.4 [arXiv 2510.04048 — Voting Ensembles with Abstention](https://arxiv.org/abs/2510.04048) (2025-10)
- **匹配度**: 7/10 — variable voting threshold, 当 dominant response 低于阈值时**集体 abstain**. 给 Pecker 苍鹰一个新选项: 4 worker 分歧严重时输出"未达共识, 需人工介入"而不是强行合并
- **Pecker 借鉴点**: 给苍鹰加 `abstain_threshold` 配置, e.g. 当某 review_item 在 4 worker 中只有 1 票, 且 evidence 弱 → abstain (mark as `tentative`) 而不是丢弃 → 给 PM 二次决策权

> **方向 5 小结**: ISP (5.1) ROI 最高, 短期可落地; IEW (5.3) 第二; RR (5.2) 长期重要不急.

---

## 综合 Top 5 推荐 (跨方向, 按落地 ROI)

1. **OpenSpec delta_type schema** (方向 1.1) — 1 周内可落地, 改 `output/<run>/review_items.json` schema, 立刻给下游 ai-coding 工具一个标准消费格式. ROI: 9/10
2. **clgraph 列级 lineage graph** (方向 2.1) — 直接攻克 R-016 类型不一致 case 的算法层, 把 Pecker 关键卖点 (lineage_quality=5) 从"LLM 偶然抓到"升级为"算法保证抓到". 改 `review/cross_table_lineage.py`. ROI: 9/10
3. **gatekeeper-library 规则库目录结构** (方向 4.1) — 给 FN 风鸟 10 条规则 + 未来 PRD-domain rules 提供工程级目录 + Makefile + manifest. 改 `output/wiki/external_canonical/` 的组织方式. ROI: 8/10
4. **ISP 加权聚合** (方向 5.1) — 升级 `goshawk/aggregator.py`, 把当前 DAR 静态阈值改为 ISP 加权, 在 same compute 下提升 R-016 类隐患召回. ROI: 8/10
5. **langroid 消息级 lineage schema** (方向 3.1) — 抄 RewindTool 数据结构到 `output/<run>/lineage.jsonl`, 让 Pecker 输出可被 implement 端反向追溯. ROI: 7/10

---

## 不推荐 (避坑)

- **Tessl spec-as-source** — 太激进 (代码完全 generate from spec), Pecker 评审定位不需要这么重
- **BMAD-METHOD 全套** — agent 团队太大, Pecker 4 worker 已够; 抄它的 yaml workflow 即可
- **Token-Level RR (5.2)** — 论文新意大但落地代价过高, 等场景出现 adversarial worker 再考虑
- **DecisionsDev IBM ODM** — 商业引擎, 不可 vendor
- **Reqflow / OpenFastTrace** — 传统 V-model 工具, 输出 HTML 报表为主, 不适合作为 ai-coding pipeline 中间产物

---

## 战略洞察

### 哪些方向是空白 (= Pecker 早期采用红利)
- **方向 2 (cross-document consistency)**: **真空白**. OpenAPI 工具单文档级、dbt/sqlmesh 偏纯 schema, 没有把 PRD 文本 + DDL + API + UI 拼成图跑 lineage 的工具. **Pecker 在这是 OSS 候选**
- **方向 3 (LLM code lineage)**: **次空白**. langroid 是消息级, MassGen #881 还是 RFC, Alor-e 是评估论文. 没有"spec rule_id → code line"的成熟工具. **Pecker 第二个 OSS 候选**

### 哪些方向已有成熟标准, Pecker 直接借
- 方向 1 (Spec-to-Code): OpenSpec/Spec Kit/Kiro/Tessl 已成生态, Pecker 必须对接, 不要自创
- 方向 4 (规则库): gatekeeper-library 是 7 年沉淀的金标准, 直接抄
- 方向 5 (聚合算法): arXiv 2025-2026 论文成熟, 直接实现

### 如果只能投一个
**投方向 2 (cross-document consistency / clgraph 借鉴)**. 理由:
- 这是今天三工况实验印证的 Pecker **唯一难以被 single-shot 和 raw PRD 替代**的能力
- OSS 空白 = Pecker 早期 OSS 红利
- 算法可量化 (lineage graph node/edge 数), 不是纯 LLM 黑箱, 容易做 demo + benchmark
- 与方向 1 (OpenSpec delta) 天然耦合: cross-table 不一致就是一种 delta_type=COHERENCE 的 review_item

### 意外发现
1. **Spec Kit / Kiro / Tessl / BMAD 都不做 cross-document 一致性**. 它们假设 spec 是单文档. 这意味着 Pecker 上游 + cross-doc validation 组合能力是**生态空白**
2. **arXiv 论文 (2603.28005 Rethinking Atomic Decomposition)** 提示: atomic decomposition 不一定优于 holistic prompt. 给 Pecker evidence verify 的 NLI atomic claim 路径打了反例, 可能要重新评估
3. **kenhuangus/llm-wiki (Day4 推荐)** 与本次 OpenSpec delta 概念有冲突: 一个主张 "wiki 是知识沉淀", 另一个主张 "spec 是变更增量". Pecker 需要明确两者关系 — 建议 wiki 沉淀稳定知识, delta 描述本次评审产出

---

## 数据汇总表

| 方向 | 项目数 | 最强项目 | 最强项目 ★ | 落地优先级 |
|---|---:|---|---:|---|
| 1 Spec-to-Code | 3 | Fission-AI/OpenSpec | 43k | High |
| 2 Cross-Doc Consistency | 2 (1 空白) | mingjerli/clgraph | 3 | **Highest (空白红利)** |
| 3 LLM Code Lineage | 3 (主要参考论文 + RFC) | langroid/langroid | ~3.6k | Medium-High |
| 4 Domain Rule Library | 4 | gatekeeper-library | ~1k | High |
| 5 Multi-Sample Consensus | 4 篇论文 | arXiv 2510.01499 (ISP) | N/A | Medium |

---

## 报告路径

- 主报告: `C:\Users\20834\Desktop\agent\prd review\docs\research_ai_coding_upstream_2026_04_27.md`
- 与之配套: `docs/research_2026_04_26_day4.md` (Day4 已有方向)
- 建议落地动作: 见综合 Top 5 推荐, 优先级 1-3 起手

---

## Sources

### 方向 1 — Spec-to-Code Pipeline
- [Fission-AI/OpenSpec](https://github.com/Fission-AI/OpenSpec)
- [bmad-code-org/BMAD-METHOD](https://github.com/bmad-code-org/BMAD-METHOD)
- [github/spec-kit](https://github.com/github/spec-kit)
- [GitHub Spec-Driven Development Blog](https://github.blog/ai-and-ml/generative-ai/spec-driven-development-with-ai-get-started-with-a-new-open-source-toolkit/)
- [Tessl spec-as-source](https://tessl.io/blog/tessl-launches-spec-driven-framework-and-registry/)
- [Kiro spec-driven IDE](https://kiro.dev/docs/specs/)

### 方向 2 — Cross-Document Consistency
- [mingjerli/clgraph](https://github.com/mingjerli/clgraph)
- [Satissss/LinkAlign (EMNLP 2025)](https://github.com/Satissss/LinkAlign)
- [tokern/data-lineage](https://github.com/tokern/data-lineage)
- [SchemaGraphSQL arXiv:2505.18363](https://arxiv.org/pdf/2505.18363)
- [Snowflake LLM Schema Propagation](https://www.snowflake.com/en/developers/guides/schema-lineage-auto-propagation-llm/)

### 方向 3 — LLM Code Lineage
- [langroid/langroid](https://github.com/langroid/langroid)
- [langroid RewindTool](https://langroid.github.io/langroid/reference/agent/tools/rewind_tool/)
- [arXiv:2506.16440 LLM Doc-to-Code Traceability](https://arxiv.org/abs/2506.16440)
- [Alor-e/evaluating-llm-doc-code-traceability](https://github.com/Alor-e/evaluating-llm-doc-code-traceability)
- [MassGen #881 changedoc proposal](https://github.com/massgen/MassGen/issues/881)
- [Embedding Traceability in LLM Code Gen ACM FSE 2025](https://dl.acm.org/doi/10.1145/3696630.3730569)

### 方向 4 — Domain Rule Libraries
- [open-policy-agent/gatekeeper-library](https://github.com/open-policy-agent/gatekeeper-library)
- [aatakansalar/yaml-opa-llm-guardrails](https://github.com/aatakansalar/yaml-opa-llm-guardrails)
- [DecisionsDev/rule-based-llms](https://github.com/DecisionsDev/rule-based-llms)
- [openvalidation/openvalidation](https://github.com/openvalidation/openvalidation)
- [microsoft/dsl-copilot](https://github.com/microsoft/dsl-copilot)
- [LinuxBozo/brij-spec](https://github.com/LinuxBozo/brij-spec)

### 方向 5 — Multi-Sample LLM Consensus
- [arXiv:2510.01499 Beyond Majority Voting (OW + ISP)](https://arxiv.org/abs/2510.01499)
- [arXiv:2604.17139 Consensus Trap / Token-Level RR](https://arxiv.org/abs/2604.17139)
- [arXiv:2511.02309 Inverse-Entropy Voting](https://arxiv.org/html/2511.02309)
- [arXiv:2510.04048 Voting Ensembles with Abstention](https://arxiv.org/abs/2510.04048)
- [arXiv:2510.13918 Optimal Aggregation LLM + PRM](https://arxiv.org/html/2510.13918)
- [arXiv:2509.02534 Darling Diversity-Aware RL](https://arxiv.org/html/2509.02534v1)
- [arXiv:2603.28005 Rethinking Atomic Decomposition](https://arxiv.org/abs/2603.28005)
- [arXiv:2506.07446 AFEV Atomic Fact Extraction](https://arxiv.org/abs/2506.07446)
