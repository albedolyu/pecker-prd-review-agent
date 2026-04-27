# Pecker 跨 agent 风格兼容性 (2026-04-28) — Path B 模拟

## 任务

- baseline endpoint: GET /api/v1/labour-arbitration/delivery/list (跟任务 1 baseline 一致)
- spec 输入: `workspace-劳动仲裁/output/review_items_R2_2026_04_28.json` (干净 setup, 0 幻觉 ID)
- 用任务1已 filter 好的 `pecker_delivery_list.md` 作为 spec md (复用 task1 setup)
- Agent X = `claude-sonnet-4-6` + lineage-aware system prompt (Claude Code 风格)
- Agent Y = `claude-opus-4-7` + minimal-constraint system prompt (Codex 风格模拟)
- Judge   = `claude-sonnet-4-6` (5 维 + 2 计数)

## Path B Caveat

**没 OPENAI_API_KEY 配置, 走 Path B**: 用 Anthropic 模拟跨 vendor.

- 测的不是真跨 vendor (Codex API)
- 测的是 **不同 model + 不同 prompt 风格** 在同一份 Pecker spec 上的输出差异
- 真跨 vendor 验证需等 PM 配 OPENAI_API_KEY 后用 Path A 跑

## 评分对比表

| agent | model | 风格 | field_correct | field_complete | lineage | ambig | buildability | clar | inferred | 总分 (5维) |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| X | claude-sonnet-4-6 | lineage-aware | 5 | 5 | **5** | 4 | 4 | 2 | 0 | 23 |
| Y | claude-opus-4-7 | minimal-constraint | 4 | 5 | **1** | 1 | 3 | 0 | 0 | 14 |

## Δ 维度细分

| 维度 | X | Y | Δ (X-Y) |
|---|---:|---:|---:|
| field_correctness | 5 | 4 | +1 |
| field_completeness | 5 | 5 | +0 |
| lineage_quality | 5 | 1 | +4 |
| ambiguity_handling | 4 | 1 | +3 |
| buildability | 4 | 3 | +1 |

## Verdict

- **lineage Δ (X-Y)**: +4
- **lineage 跨风格显著差异** (Δ=4, X=5 vs Y=1) — Pecker spec 对 prompt 风格高度敏感
- **Spec over-fit 判定**: spec 在 X 风格优势明显 (Δtotal=9)
- **vs 任务 1 baseline (delivery/list lineage=5)**: X=5, Y=1 —
  仅 X 饱和, 提示 spec 的 lineage 信号需要 system prompt 配合 (lineage-aware) 才能放出
- **关键反转**: 任务 1 (4/4 endpoint lineage=5) 其实是 "Pecker spec + Opus 4.7 + lineage-friendly 用户 prompt" 的产物 —
  本任务证明只要 system prompt 切到 minimal-constraint, **同样的 spec + 同样的 Opus 4.7 + 几乎一样的用户 prompt, lineage 直接掉到 1**.
  说明 Pecker 的 lineage 信号不是 spec 自带"携带"的, 而是 spec + 风格指令的合力
- **隐含 PM 含义**:
  - 接 Pecker spec 的下游 implement agent 必须有 lineage-aware system prompt 配套, 否则 spec 形同虚设
  - 真 Codex / 其他 vendor 接入时, 需要在 system prompt 一并下发 "lineage convention" (引用 rule_id / 标 inferred), 不能只丢 spec md 让 agent 自由发挥
  - 不要用任务 1 的 4/4 饱和率推论 "Pecker spec 跨 agent 通用"

## Judge 1 句话总评

- **agent_X**: 字段完整准确，溯源注释规范，ANY(:ids)参数传递需验证
- **agent_Y**: 字段与接口对齐良好，但零 PRD 溯源、零 TODO，ANY(:ids) SQLAlchemy 绑定在生产环境有运行时风险，keyword 子查询缺 entid 约束存在逻辑漏洞

## Caveat

- **Path B 模拟**: Codex 用 Anthropic Opus 4.7 + minimal prompt 模拟. 真 Codex API 风格 (e.g. system 提示风格, 单次输出长度, tool use 行为) 未覆盖. 等 PM 配 OPENAI_API_KEY 后跑 Path A.
- **混淆变量**: X-Y 同时换了 model (Sonnet ↔ Opus) + system prompt 风格 (lineage-aware ↔ minimal). 严格说不能把 Δ 全归给 prompt 风格. 需要 follow-up 跑 2x2 (X model × X prompt / X model × Y prompt / Y model × X prompt / Y model × Y prompt) 才能 isolate.
- **判定单点**: 只跑了 1 endpoint × 1 次 implement, 没做 multi-run sampling. lineage Δ 可能受 sampling noise 影响 ±1 分.
- **Judge 同 vendor**: Sonnet 4.6 既评 Sonnet 4.6 也评 Opus 4.7, 同 vendor 自评偏差未控.
- **任务 1 baseline (lineage=5) 来自 Opus 4.7 + 嵌在 USER_PROMPT 里的 lineage instruction**: 任务 1 的 IMPL_PROMPT 用户消息里有
  > "must severity issue: 严格按 suggestion 落地, 必须在代码注释引用 issue.id (例: `# lineage: R-007 [RC-008]`)"
  
  这本身就是强 lineage 指令. 本任务的 Y **同时去掉了用户 prompt 里这段 lineage instruction + 加 minimal-constraint system prompt**, 才看到 lineage 直接掉到 1 (零 PRD 溯源). 这印证 lineage=5 不是 Pecker spec 自带"携带"的, 而是 spec + lineage instruction 的合力. 拆掉指令, spec 就只剩字段层信号 (field_correct=4 / complete=5 都还在).

## 风险记录

- API failure: 无
- judge parse: 全部 OK
- empty output: X impl chars=15147, Y impl chars=14415

## 成本与时间

| step | duration (s) |
|---|---:|
| agent_X (impl + judge) | 374.4 |
| agent_Y (impl + judge) | 165.3 |
| **合计** | **539.7** |

## 附: 原始产物路径

- `workspace-劳动仲裁/output_codex_cc_compat_2026_04_28/summary.json`
- `workspace-劳动仲裁/output_codex_cc_compat_2026_04_28/impl_agent_X.md`
- `workspace-劳动仲裁/output_codex_cc_compat_2026_04_28/impl_agent_Y.md`
- `workspace-劳动仲裁/output_codex_cc_compat_2026_04_28/judge_agent_X.json`
- `workspace-劳动仲裁/output_codex_cc_compat_2026_04_28/judge_agent_Y.json`
- `workspace-劳动仲裁/output_codex_cc_compat_2026_04_28/user_prompt.txt`
