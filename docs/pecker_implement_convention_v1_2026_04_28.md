# Pecker Implement Convention v1 (草案, 2026-04-28)

## 用途

Pecker 输出 (review_items.json / pecker_*.md) 的下游消费规约.
**任何接收 Pecker 输出做 implement / DDL / schema 落地的 agent 必须在 system prompt 注入本 convention**, 否则 lineage / ambiguity 维度会塌到 1/5.

> 实证依据: 任务 4 follow-up (`docs/codex_cc_compat_followup_2026_04_28.md`) 显示 model 切换对 lineage 0 影响, system prompt 切换 lineage Δ +4. **Pecker spec 携带的字段信息只占 ~50% 价值, 另 50% 必须靠 convention 强行约束下游行为**.

## review_items 字段语义说明

| 字段 | 类型 | 必读 | 含义 | 下游必须做 |
|---|---|---|---|---|
| `issue_id` | str (R-XXX) | 是 | 全局唯一引用号 | 落地代码注释引用 (`# lineage: R-007`) |
| `severity` | enum | 是 | must / should / could 三档 | 决定落地强度, 见 C-2 |
| `rule_id` | str (V-XX / RC-XX / FN-XX 等) | 是 | Pecker 规则 ID | 业务规则字段必须注释引用 (见 C-4) |
| `dimension` | enum | 否 | 结构层 / 一致性 / 业务规则 / 漏报 | 帮你判定该 issue 影响哪一维, 不强引 |
| `location` | str (PRD 路径) | 是 | PRD 章节定位 | 模糊字段查 PRD 时入口 |
| `issue` | str (中文) | 是 | 问题描述 | 注释里复述时用来定位字段语义 |
| `suggestion` | str (中文) | 是 | 修复建议 | **must 必须严格按 suggestion 落地, should 尽量** |
| `evidence` | str + 等级 (A/B/C) | 否 | 证据原文 + 可信度 | A 级直接信; B 级核对 PRD 原文; C 级标 TODO |
| `verification_status` | enum | 否 | passed / failed / not_run | failed 的不强 must, 标 TODO |

## 5 条强制约定

### C-1 lineage 引用 (核心)

任何非 PRD 明文列出的字段必须有溯源注释, 二选一:

```python
unique_id: str  # lineage: R-011 — case_code+publish_date 的 MD5
case_code:  str | None  # inferred: PRD 1.5 称"案号或为空", 故允许 NULL
```

- `# lineage: <issue_id>` — 字段语义 / 约束直接来自 Pecker issue
- `# inferred: <PRD 章节 + 推理>` — Pecker 没说但 PRD 暗示的, 必须给章节定位

**违反**: 任何字段无 lineage / inferred / PRD 明文位置三者之一引用, 视为 LLM 编造, 不通过 verify.

### C-2 severity 三档落地分级

| severity | 落地强度 | 必须做的事 |
|---|---|---|
| **must** | 强制落地 | 1) 代码注释引 `# lineage: <issue_id>` 2) 实现严格按 `suggestion` 执行 3) 不允许跳过或简化 |
| **should** | 尽量落地 | 1) 落地优先 2) 若与 must 冲突可标 `# deferred: should-conflict-with-<must_id>` 跳过 |
| **could** | 标 TODO | 1) 不强求落地 2) 但必须标 `# TODO: could-<issue_id> — <原文 suggestion>` 让 PM 后续审 |

**反模式**: 把 must 当 should 处理 (如忽略 suggestion 的具体实现细节). 这是 lineage=1 的常见根因.

### C-3 模糊字段必须标 TODO

PRD 多解 / 隐含 / 验证 failed 的字段必须显式标记:

```python
# TODO: 待确认 - PRD 1.5 仅描述"空值率 10%"未定义降级策略, 当前默认 "" 占位
arbitration_org: str | None = ""
```

模板: `# TODO: 待确认 - <原因 + 当前临时方案>`

**触发条件 (任一即触发)**:
1. PRD 没明示但你必须做选择 (例: NULL 排序位置 / 默认值)
2. Pecker `verification_status=failed` 但 severity=must
3. evidence 等级 = C (低可信度)

### C-4 Pecker rule_id 注释 (业务规则强制)

涉及业务规则的字段必须在注释引 `rule_id`:

| 触发场景 | 必须引的 rule_id 前缀 | 示例注释 |
|---|---|---|
| 枚举值 | V-XX (验证类) | `# rule_id=V-05: type 枚举仅 1=送达 2=开庭` |
| 字段计算 | RC-XX (规则一致性) | `# rule_id=RC-008: unique_id = MD5(case_code, publish_date)` |
| 漏报补 | FN-XX (漏报规则) | `# rule_id=FN-03: open_time 必须 NOT NULL 校验` |
| 跨章节一致 | EV-XX (证据治理) | `# rule_id=EV-01: 验收以 2.2.2 开庭公告章节为准` |

**反模式**: 注释只写"开庭时间", 不引 rule_id. judge 会判 lineage=1.

### C-5 inferred 显式声明 (反编造)

PRD / Pecker spec 都没说但你想加的字段, 必须标:

```python
update_time: datetime  # inferred: 标准 audit 字段, 业内通用, PRD 未明示
deleted_at: datetime | None  # inferred: 软删除模式, PRD 1.6 数据状态隐含需求
```

**反模式**: 不加 inferred, 直接当 PRD 字段写. 是 `inferred_field_count` 计数为 0 但实际编造的常见原因 — judge 因为没看到 inferred 标记会以为是 PRD 字段, 漏判.

## Implement Prompt 模板 (system 注入)

下游 agent 的 system prompt 末尾必须含以下段落 (中文 / 英文双语版皆可):

```
你必须遵守 Pecker Implement Convention v1.

5 条强制约定:
1. 任何非 PRD 明示字段必须标 `# lineage: <issue_id>` 或 `# inferred: <PRD 章节 + 推理>`
2. severity=must 必须严格按 suggestion 落地, 注释引 issue_id; should 尽量落地;
   could 标 `# TODO: could-<issue_id> — <suggestion>`
3. 模糊字段 (PRD 多解 / verification_status=failed / evidence C 级) 必须
   `# TODO: 待确认 - <原因 + 当前临时方案>`
4. 业务规则字段 (枚举 / 计算 / 排序 / 漏报) 必须注释引 rule_id (V-XX / RC-XX / FN-XX / EV-XX)
5. 自加字段必须 `# inferred: <reason>`, 否则视为编造

输出失败模式 (任一触发都判失败):
- 字段无 lineage / inferred / PRD 明文位置任一引用
- must severity 没引 issue_id
- 模糊字段没标 TODO
- 自加字段没标 inferred

输入 spec 是 Pecker (PRD review agent) 输出, issue 是真理之源,
若 PRD 与 issue 冲突, 以 issue + suggestion 为准.
```

## 质量验收维度 (与 5+2 judge 对应)

下游产出后用以下维度自检 (或交给 reviewer agent):

| 维度 | 验收标准 | 触发哪条 convention |
|---|---|---|
| **field_correctness** ≥ 4 | 字段名 / 类型 / 约束符合 PRD, 无大量编造 | C-5 (inferred 标注) |
| **field_completeness** ≥ 4 | PRD 列表 / 接口字段全有 | C-2 (must 严格落地) |
| **lineage_quality** ≥ 4 | 每非 PRD 明示字段都有溯源 | **C-1 + C-4** (核心) |
| **ambiguity_handling** ≥ 4 | 模糊字段都标 TODO + 默认值 | **C-3** (核心) |
| **buildability** ≥ 4 | 代码可直接 pytest, 语法 / import 全对 | 不直接由 convention 约束, 由 model 能力决定 |
| **clarification_count** ≥ 1 | 至少 1 处 TODO / 待确认 | C-3 |
| **inferred_field_count** ≥ 0 | 自加字段都标 inferred (隐含: 无 inferred 标但实际编造的字段视为 0 标但实际 > 0) | C-5 |

**Gate v1 (建议触发 abort 重试)**:
- lineage_quality < 3
- ambiguity_handling < 3
- field_correctness < 3

## 实证数据 (v1 草案的依据)

任务 4 follow-up 2×2 数据 (`docs/codex_cc_compat_followup_2026_04_28.md`):

| | Sonnet 4.6 | Opus 4.7 |
|---|---:|---:|
| **with convention (lineage-aware)** | lineage=5, ambig=4 | lineage=5, ambig=4 |
| **without convention (minimal)** | lineage=1, ambig=1 | lineage=1, ambig=1 |

结论: convention 是把 lineage 从 1 拉到 5 的 **唯一变量**. model 切换 (Sonnet ↔ Opus) 对 lineage 影响为 0.

## 版本管理

- v1 (2026-04-28): 5 条强制约定 + 模板 + 7 维验收
- 触发升级条件:
  - judge 5+2 维度新增
  - Pecker rule_id 体系扩展 (e.g. 新增 EV-XX / FN-XX 子类)
  - cross-vendor 实测发现新 fail mode

## 后续 actionable

1. **Pecker 输出层**: review_items.json schema 加 `implement_convention_version: "v1"` 字段
2. **下游 agent 模板**: 把"Implement Prompt 模板"段落作为 system prompt 必须块, 任何 wrapper 不允许跳过
3. **CI 检查**: 落地代码后跑一个 lint script 检查注释里 `# lineage` / `# inferred` / `# TODO` 出现次数, 低于阈值告警
4. **Convention 升级 v2 触发**: 等 Path A 真 Codex 跑完 + 至少 2 PRD 多 endpoint 测试后

## Caveat

- 单 endpoint × 4 数据点, 是初版假设, 需 multi-PRD 验证
- 引用语法 (e.g. `# lineage:` 用 `#` 还是 `//`) 因语言而异, 草案以 Python 为基准
- judge 评分受 prompt 风格二元印象影响, lineage 1/5 离散现象明显, 中间档 2/3/4 出现频率低 — 可能需要 judge prompt 增加细粒度锚点
