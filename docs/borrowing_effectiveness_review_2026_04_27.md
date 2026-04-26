# 4 条 GitHub 借鉴真有效性审查 (2026-04-27)

> 审查者: Reality Checker (默认 NEEDS WORK), 只读模式, 35 min 边界
> HEAD: `89d28dc` (注: 用户提供的 49acf65 不是当前 HEAD, 实际审查基于 89d28dc — `docs: 草稿状态更新 — FN-01/03/09 已升 experimental`)
> 关键 stake: 上次 NLI / DAR / canonical wiki 借鉴 — commit 了 production 0 触发, 今天 P0/P1 才捞回来. PM 已被坑过两次, 这次默认怀疑.

---

## TL;DR

- APPROVE: **0 条**
- APPROVE WITH PREREQ: **1 条** (借鉴 2, 但 prereq 重到接近"先做 2 个月才能用")
- NEEDS WORK: **2 条** (借鉴 1, 借鉴 4)
- REJECT: **1 条** (借鉴 3, 重复造轮子)

**最大的 anti-pattern**: 4 条里有 3 条会变成下一次"NLI / DAR 模式" — 接通但不工作或不解决真痛点. 这次提前拦截.

---

## 实验数据快速回顾 (本次审查的 ground truth)

`workspace-劳动仲裁/output_experiment_2026_04_27/judge_results.json` (Sonnet 4.6 LLM-as-judge, 5 维度):

| 工况 | field_correctness | field_completeness | lineage_quality | ambiguity_handling | **buildability** | clarification_count | inferred_field_count |
|---|---:|---:|---:|---:|---:|---:|---:|
| **A — Pecker (review_items.json + PRD)** | 4 | 5 | **5** | **5** | **3** | 4 | 3 |
| **B — Single-shot Opus 4.7 review** | 4 | 5 | 3 | 4 | **3** | 3 | 0 |
| **C — Raw PRD only** | 4 | 5 | 4 | 4 | **3** | 1 | 0 |

**关键观察**:
1. **A 真正强项只在 lineage_quality (5 vs 3/4) + ambiguity_handling (5 vs 4/4) 各 +1~+2 分**, 其他维度持平或微弱.
2. **buildability 三工况全是 3 分** (A summary "测试语法有坑", B "DDL 用 PostgreSQL 而非 MySQL 且 handler 缺 Optional 导入", C "ANY 列表绑定存运行时隐患"). buildability 的 bug 全是 LLM 在实现层栽的, 不是 spec 信息不够.
3. impl A 的代码 **已经在代码注释里写出 `lineage: R-016 [V-02]` 等 14+ 处** (`workspace-劳动仲裁/output_experiment_2026_04_27/impl_a_pecker.md:6,53,83,108,117,145,159,177,181,212,226,297,376,378,400,420`).

> 这 3 个观察直接决定 4 条 verdict.

---

## 1. OpenSpec delta_type — verdict: NEEDS WORK

### 借鉴假设
review_items 加 `delta_type: ADDED|MODIFIED|REMOVED|FLAGGED`, 下游 implement agent 直接消费, buildability 提升.

### 1a. 当前 implement agent 真用了多少 review_items 字段?

`build/lib/scripts/experiment_pecker_pipeline_value.py:96-122` 中 `serialize_pecker_for_implement()` 给 implement A 工况的 prompt 输入是:
```
### [{id}] rule_id={rule_id} dimension={dimension}
- **location**: {location}
- **issue**: {issue}
- **suggestion**: {suggestion}
- **evidence ({evidence_type})**: {evidence_content[:300]}
- **verification_status**: {verification_status}
```

**用到的字段**: id, rule_id, dimension, severity (分组用), location, issue, suggestion, evidence_type, evidence_content, verification_status — **共 10 个字段**.

prompt (`build/lib/scripts/experiment_pecker_pipeline_value.py:207-227`) 显式让 implement agent 按 severity 落地 + 在代码注释引用 `issue.id` (例: `# lineage: R-007 [RC-008]`).

### 1b. impl A 实际产物里 lineage 注释覆盖

`workspace-劳动仲裁/output_experiment_2026_04_27/impl_a_pecker.md` grep `lineage:` 结果:
- 14+ 处显式 lineage 注释
- 涵盖 R-008 / R-011 / R-013 / R-016 / R-020 / R-027 / R-029 共 7 个不同 rule_id

**结论**: rule_id + severity + suggestion 已经被 implement agent 完整消费. 这是借鉴 1 的"目标位置".

### 1c. 加 delta_type 真能 +1 buildability?

**impossible**. judge_results.json 里 A 的 buildability=3 是因为:
- judge summary: "测试语法有坑" — pytest 实现层 bug, 与 spec 信息无关
- B 工况 buildability=3 summary: "DDL 用 PostgreSQL 而非 MySQL 且 handler 缺 Optional 导入" — 同样 LLM 实现层 bug
- C 工况 buildability=3 summary: "ANY 列表绑定存运行时隐患" — 同样实现层

**buildability 的瓶颈不在 spec 字段维度**, 在 Opus 4.7 写 Python 代码时的语法/类型/导入. 加 delta_type 给 spec 多一个 enum 字段不改变 LLM 实现层失误概率.

### 1d. 预期 ROI 量化
| 假设 | buildability 预期变化 |
|---|---|
| 加 delta_type, 下游 prompt 不改 | **+0** (字段没人读) |
| 加 delta_type + prompt 显式区分 ADDED/REMOVED 实现路径 | **+0~+0.3** (lineage_quality 已 5/5, 提升空间小) |
| 加 delta_type + prompt + 单元测试桩 | **+0.5** (实测真痛点是 LLM 写测试错语法) |

### 1e. 反面思考 — 不做会怎样?
- 当前 lineage_quality=5 已最高分, **不做不损失任何 already-validated 价值**.
- 只是少了对 OpenSpec 工具链的"协议对齐"营销点. PM 痛点 (buildability) 与此无关.

### verdict: **NEEDS WORK**
- 理由: review_items 已有 10 字段全部被 implement agent 消费, lineage_quality 已满分, buildability 瓶颈在 LLM 实现层不在 spec — 加 delta_type 不解决真痛点.
- 不做的代价: 失去 "OpenSpec 兼容" 标签, 实际功能损失 ~ 0.
- 前置依赖 (如要做): 先证明 ADDED/REMOVED 区分能让 implement agent 走不同代码路径, 否则就是又一次"接通但 0 触发".

---

## 2. clgraph cross-table lineage — verdict: NEEDS WORK (可升 APPROVE-WITH-PREREQ 但 prereq 极重)

### 借鉴假设
列级 lineage graph deterministic 抓 R-016 类型不一致, 不再依赖 LLM 偶然.

### 2a. R-016 这种 case 真有多频繁?

抽 `workspace-劳动仲裁/output/review_items_20260427_default.json` 27 条:
- 跨表/跨章节 loose match: **4/27 (14.8%)**
- **strict 跨表类型/精度不一致 (R-016 类)**: **1/27 (3.7%)** — 仅 R-021
- 同表抽 `review_items_20260426_default.json` 24 条: 跨表 loose 4/24, strict 也是 1 条 (R-015)

**结论**: R-016 类是 **3-4% 长尾**. 哪怕 100% 召回也只新增 1 条 review_item.

### 2b. clgraph 跑算法需要 ground truth DDL — wiki 现状

风鸟 wiki `entities/` 目录 (`C:\Users\20834\Desktop\代码项目\风鸟代码库\wiki\entities\`):
```
技术栈.md
前端组件.md
数据库模型.md       ← 唯一与 DDL 相关
```

`数据库模型.md` 内容是 **"实体类 → 表名" 映射 + 表关系 ASCII 图**:
```
| 实体类      | 数据库表          | 说明           |
|------------|-----------------|----------------|
| `User`     | `t_sys_user`    | 系统管理员账户   |
| `QibabaUser` | `t_qibaba_user` | C 端用户主表   |
```

**完全没有字段级 DDL** (列名 / 类型 / nullable / 约束 / 索引). 只能告诉你"哪个实体对应哪个表名", 给不了"open_time 在主表是 datetime, 在 ent 表是 date".

### 2c. 风鸟代码库 wiki 路径 DDL 子集
- `entities/数据库模型.md`: 仅表名映射, 无 DDL — **0 字段级 spec**
- `concepts/`: `JWT认证流程.md / WebView桥接.md / 混合架构.md` — 全是流程概念, 无 DDL
- 其他子目录 (api / architecture / decisions / modules) 抽样未见独立 DDL 文件

**结论**: clgraph 算法的输入 (column-level metadata) 在风鸟 wiki **不存在**. 算法跑了也比对不出.

### 2d. 反面思考
- 不做: 损失 1 条 / 27 条的 strict cross-table 长尾召回 ≈ 损失 3.7% recall.
- 做了 prereq: 需要先把 ent / 主表 DDL 全部写进 wiki (估约 50-100 张表), PM 没这工程容量.
- 真痛点: R-016 这条 review_items 本身已经被 V-02 / DQ-002 LLM 抓到了, 抓的时机和精度都没差.

### verdict: **NEEDS WORK**
- 理由: 真痛点 case 占比 3.7%, 而且当前 LLM 已抓到 (R-016/R-021/R-022 都已在 review_items 里). DDL ground truth 不存在 — clgraph 算法无输入.
- 不做的代价: 长尾 1-2 条/PRD 的 cross-table 类型不一致召回稳定性, 但 LLM 已经抓到, 仅冗余加固.
- 前置依赖 (如要做): **先把风鸟 50+ 张物理表的字段级 DDL 写入 wiki entities/** (工程量 1-2 周 PM 主导, 极重) → 然后 clgraph 才能跑.
- 替代方案: 在 review-dimensions.yaml 加 V-02-EXT "字段名跨表精度对照表" 检查项 (LLM-prompt-time, 不需要 graph), prompt 工程 1 小时.

---

## 3. LLM code lineage (rule_id propagate) — verdict: REJECT

### 借鉴假设
implement agent 生成代码后, 反向 trace review_items rule_id, PM 调试用.

### 3a. 今天工况 A 已经在做这件事了吗?

`workspace-劳动仲裁/output_experiment_2026_04_27/impl_a_pecker.md` 实测:
- DDL 注释: `-- lineage: R-016 [V-02] / R-020 [D-01] - 主表/ent 表 open_time 类型必须一致 (TIMESTAMP)` (line 6)
- Pydantic field 注释: `keyword: Optional[str] = Field(... # lineage: R-027 [V-03] - 模糊搜索最小长度 ≥ 2)` (line 83)
- handler 注释: `# lineage: R-008 [V-02] - 鉴权 TBD, 暂从 Header 透传` (line 177)
- handler 函数 docstring: `lineage: R-011 [V-03] / R-029 [V-03] - 按字数打码` (line 159)
- pytest 注释: `# page_size=33 不在 20/50/100 -> 业务包络 4001 (lineage: R-013)` (line 420)

**14+ 处 lineage 注释**, 涵盖 7 个不同 rule_id, 嵌入到 DDL / schema / handler / 测试 4 段全部.

### 3b. prompt 已经做了
`build/lib/scripts/experiment_pecker_pipeline_value.py:213` (IMPL_PROMPT_A_PECKER):
```
1. **must severity issue**: 严格按 suggestion 落地, 必须在代码注释引用 issue.id (例: `# lineage: R-007 [RC-008]`)
```

**已经是 prompt-time 强制约束**, 不需要新工具.

### 3c. propagation 工具的真痛点是什么?

如果 PM 想"反向 grep 哪行代码来自哪条 rule":
```bash
grep -rn "lineage: R-" path/to/code/
```
就能列出所有 lineage 注释 — 简单 grep 工具, 不需要 langroid RewindTool 或 Alor-e 论文反向 trace.

### 3d. PM 真会用反向追溯吗?
PM 主要看 `review_items.json` (单一权威源), 不主要看代码. 反向追溯工具的"PM 调试场景"基本是空话.

### 反面思考 — 不做会怎样?
- 当前 lineage_quality=5 已最高, 14+ 处注释覆盖 4 段代码 100%.
- 不做不损失任何 user-visible 价值.
- "做"反而引入 1 个新 schema (`lineage.jsonl`) + 1 个新 CLI (`lineage_check.py`), 后续维护成本.

### verdict: **REJECT**
- 理由: prompt 已让 implement agent 在 4 段代码 100% 嵌入 lineage 注释, lineage_quality=5 已满分. 反向 trace 用 grep 即可. 这是**已经解决的问题**.
- 不做的代价: 0.
- 前置依赖: 无 — 这条直接砍掉.

---

## 4. gatekeeper-library rule 工程化 — verdict: NEEDS WORK

### 借鉴假设
gatekeeper 目录结构 + Makefile + manifest 管 FN-01~10 + 21 条原规则.

### 4a. 当前 review-dimensions.yaml 行数 / 结构

`review-dimensions.yaml` 实测: **352 行**, 4 个 dimension (structure / quality / ai_coding / data_quality), 每个 dimension 内 rules 文本块 + checklist 列表. 已包含 V-02~V-12 / RC-004~RC-015 / EV-01 / EV-04 / FN-01 / FN-03 / FN-09 共 25 条规则.

352 行单 yaml 文件**完全可读, 完全可修改**:
- IDE 折叠后看 dimension 概览
- Ctrl-F 搜 rule_id 直接定位
- git blame 单文件就够追溯历史

加 FN-02/04~08/10 后预估 350 → 500-600 行, 仍是单文件可管.

### 4b. gatekeeper-library 场景对不对?

[open-policy-agent/gatekeeper-library](https://github.com/open-policy-agent/gatekeeper-library) 是 **OPA Rego policy as code, 给 K8s admission controller runtime 用**.
- gatekeeper rule 是 Rego 代码 — runtime 在 webhook 拦截.
- Pecker 规则是 **自然语言 prompt 注入** — LLM-prompt-time, Rego 引擎不可用.

**目录结构借鉴**: `src/<rule>/src.rego + src_test.rego + manifest.yaml` 三件套 → Pecker 改成 `rules/<rule_id>/body.md + test.yaml + manifest.yaml`. 但**目录结构对 PM 维护并不解决任何已知痛点** (见 4c).

### 4c. PM 维护 25 条规则的真痛点是什么?

| 假设痛点 | 解法 | gatekeeper 解决? |
|---|---|---|
| 找规则太慢 | grep / Ctrl-F | yaml 单文件已够 |
| 看 reject_rate / 规则效用 | rule_perf 反馈循环 (`scripts/rule_lifecycle.py`) | **不解决** — gatekeeper 不带 reject_rate |
| 版本管理 | git blame / git log review-dimensions.yaml | **不解决** — gatekeeper 也是 git |
| 多 PRD/业务规则共享 | workspace 本地副本机制已有 | **不解决** — gatekeeper 是 K8s policy 不是文档 |
| 规则数 100+ 后管理 | 拆 yaml + 引入目录结构 | 才有 ROI, 但**当前才 25-31 条** |

### 4d. 反面思考
- 不做: 维护成本 ~ 当前一致, 加 FN-04~10 后单文件 ~600 行仍可控.
- 做了: 引入新目录结构, 既有 prompt 装载逻辑要全部改 (router/agents 全部 yaml 解析路径变动), 工程量大 +回归风险.

### 4e. verdict: **NEEDS WORK**
- 理由: 25 条规则 yaml 单文件 352 行完全可管, gatekeeper 的真功能 (Rego runtime / 自动 release / OPA bundle) Pecker 用不上, 借的只是目录结构. 痛点 (reject_rate / 版本) 与目录结构无关.
- 不做的代价: 失去"工程化感", 失去 manifest 标准化的对外营销点.
- 前置依赖 (如要做): 先等规则数到 50+ 条且 PM 主观感受"yaml 单文件不可读". 现在不到这个临界点.

---

## 投资 portfolio 重排

### P0 立即做 (0 条)
**无**. 4 条借鉴里没有 1 条满足 "明确证据证明能改善 buildability 或者 PM 已知痛点" 的标准.

### P1 先做 prerequisite (1 条)
**借鉴 2 (clgraph)** — **如果**满足前置条件:
- 前置: 风鸟 wiki entities/ 写入 50+ 张物理表字段级 DDL (估 1-2 周 PM 工作量)
- ROI: 长尾 3.7% strict cross-table case 算法保证召回, 而非 LLM 偶然
- 短路替代: 在 `review-dimensions.yaml` V-02 加 "字段名跨表精度对照"子项, 1 小时 prompt 工程, 可拿到 80% 收益不需要 DDL ground truth

### P2 不做 / 推迟 (3 条)
- **借鉴 1 (OpenSpec delta_type)**: lineage_quality 已 5/5 满分, buildability 瓶颈在 LLM 实现层与 spec 字段无关. 加 delta_type 既不解决真痛点也不增加 already-validated 价值, 风险是又一个 "0 触发" commit.
- **借鉴 3 (LLM code lineage)**: prompt 已让 implement agent 100% 嵌入 lineage 注释, 14+ 处覆盖 DDL/schema/handler/测试. **已是 solved problem**, 反向追溯 grep 即可.
- **借鉴 4 (gatekeeper)**: 25 条规则 yaml 单文件 352 行完全可管, gatekeeper 的真功能 (Rego runtime / OPA bundle) Pecker 用不上. 等规则数到 50+ 再考虑.

### 替代真痛点路径 (建议 P0)
本次实验暴露的 buildability=3 全工况持平真痛点:
- A: "测试语法有坑" → **prompt 加 pytest minimal example 模板**
- B: "DDL 用 PostgreSQL 而非 MySQL 且 handler 缺 Optional 导入" → **prompt 加目标 stack 锁定 + import 完整性 self-check**
- C: "ANY 列表绑定存运行时隐患" → 同上

这是 **2-3 小时 prompt 工程, 可期 +1 buildability**, ROI 远超 4 条借鉴任意一条.

---

## 风险 — anti-pattern 总结

### "wiring 但不工作" 反复出现的 4 个特征 (与 NLI / DAR 对应)
1. **借鉴自带 commit-able 接通点** (改 schema / 加配置 / 接入新 lib), 满足 PM "工程上完成了" 心智
2. **缺验收闭环** — 借鉴落地后没人测"真 case 数变化", 只看代码合并
3. **下游消费方未配套改动** — schema 加了字段但 prompt 不读 / wiki 接通了但 worker 不查
4. **真痛点没量化诊断** — 不知道当前瓶颈在 spec 信息还是 LLM 实现, 见啥借啥

### 本次 4 条借鉴的具体 anti-pattern 风险
| 借鉴 | 重蹈 NLI/DAR 模式风险 | 评估 |
|---|---|---|
| 1 OpenSpec delta_type | **高** — schema 改动 commit-able, 但 buildability 不会动, 同 NLI 0 触发模式 |
| 2 clgraph | 中 — 前置 DDL ground truth 缺失会先暴露, 不会假装通了 |
| 3 LLM code lineage | **高** — prompt 已经做了, 加新工具就是 14+ 处注释外面再套层包装 |
| 4 gatekeeper | 中 — 工程量大且改动可见, 至少不会"假装通了" |

### 给 PM 的一句话决策建议
**全砍 / 全推迟**, 把 2-3 小时投到 prompt 工程修 buildability, 比任何借鉴 ROI 都高. 这次提前拦了, 不要再让 NLI / DAR 模式重演.

---

## 报告路径
- 主报告: `C:\Users\20834\Desktop\agent\prd review\docs\borrowing_effectiveness_review_2026_04_27.md`
- 调研基础: `docs/research_ai_coding_upstream_2026_04_27.md`
- 实验数据: `workspace-劳动仲裁/output_experiment_2026_04_27/judge_results.json` 与 `impl_a_pecker.md` / `impl_b_single_shot.md` / `impl_c_raw.md`
- 实验脚本: `build/lib/scripts/experiment_pecker_pipeline_value.py` (vendored)
- review_items 数据: `workspace-劳动仲裁/output/review_items_20260427_default.json` (27 条)
- 风鸟 wiki entities: `C:\Users\20834\Desktop\代码项目\风鸟代码库\wiki\entities\数据库模型.md` (无字段级 DDL)
- 当前规则配置: `review-dimensions.yaml` (352 行)
