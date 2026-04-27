# 任务 4 follow-up: 2×2 isolate + implement convention (2026-04-28)

## 任务背景

任务 4 (`docs/codex_cc_compat_2026_04_28.md`) 暴露 Pecker spec 跨 agent 风格不 transferable:

- X (Sonnet 4.6 + lineage-aware): lineage=5 / total=23
- Y (Opus 4.7   + minimal-constraint): lineage=1 / total=14
- **Δ lineage = +4**

但 X / Y 同时换了 model **和** prompt 风格, 是混淆变量, 无法 isolate "model 影响" vs "prompt 影响".

本 follow-up 补跑 Z / W 凑齐 2×2:

| | Sonnet 4.6 | Opus 4.7 |
|---|---|---|
| **lineage-aware** | X (复用任务 4) | **Z (新跑)** |
| **minimal-constraint** | **W (新跑)** | Y (复用任务 4) |

setup:
- 同 endpoint: `GET /api/v1/labour-arbitration/delivery/list`
- 同 spec md: 复用任务 4 的 `pecker_delivery_list.md`
- 同 user_prompt: 直接读任务 4 的 `user_prompt.txt` (字符级一致)
- 唯一变量: model + system prompt

## 2×2 评分对比 (5 维 / 25 总分)

### 总分

| | Sonnet 4.6 | Opus 4.7 | model Δ (Sonnet − Opus) |
|---|---:|---:|---:|
| lineage-aware     | **X = 23** | **Z = 21** | +2 |
| minimal-constraint | **W = 15** | **Y = 14** | +1 |
| **prompt Δ (lineage − minimal)** | **+8** | **+7** | — |

### lineage_quality (单维, 也是 over-fit 焦点)

| | Sonnet 4.6 | Opus 4.7 | model Δ |
|---|---:|---:|---:|
| lineage-aware     | **5** | **5** | 0 |
| minimal-constraint | **1** | **1** | 0 |
| **prompt Δ** | **+4** | **+4** | — |

### ambiguity_handling (与 lineage 强耦合的二阶维度)

| | Sonnet 4.6 | Opus 4.7 | model Δ |
|---|---:|---:|---:|
| lineage-aware     | **4** | **4** | 0 |
| minimal-constraint | **1** | **1** | 0 |
| **prompt Δ** | **+3** | **+3** | — |

### field_correctness / field_completeness / buildability

四工况 field_correctness 全在 4-5 区间, field_completeness 全 5, buildability 3-4 区间. 这三维 prompt 风格几乎不影响 (PRD + spec 字段信号本身够强), 受影响的纯是 lineage / ambiguity.

## Verdict

### 主导因子: **prompt 风格**, 不是 model

- **prompt Δ (同 model 切风格)**: total +7~+8, **lineage +4 (1→5)**, ambiguity +3 (1→4)
- **model Δ (同 prompt 切 model)**: total +1~+2, **lineage 0 (完全相同)**, ambiguity 0
- prompt 的影响是 model 影响的 **3-4 倍**

### 真 over-fit 是 prompt over-fit

任务 4 lineage=5 不是 Pecker spec 自带"携带"的 lineage 信号, 而是 **lineage-aware system prompt 强行注入的产物**. 同 spec 同 user_prompt, system prompt 一掉, lineage 立刻从 5 跌到 1, 与 model 选择 (Sonnet 还是 Opus) 完全无关.

### PM 含义

1. Pecker 的 review_items.json 单独丢给下游 agent, **如果下游 system prompt 没有 lineage convention, spec 形同虚设** (lineage=1, ambig=1)
2. 真 OpenAI Codex / 其他 vendor 接入时, **必须** 在 system prompt 一并下发 lineage convention, 否则 cross-vendor 表现一定会塌
3. Pecker 输出从 "review_items.json" 升级为 "review_items.json + implement_convention.md", 后者必须强制下游消费

## Convention 落地

草案: `docs/pecker_implement_convention_v1_2026_04_28.md`

5 条强制约定 (摘要, 详见草案):

1. **C-1 lineage 引用**: 每个非 PRD 明示字段必须 `# lineage: <issue.id>` 或 `# inferred: <理由>`
2. **C-2 severity 落地分级**: must=必落地+引 issue.id / should=尽量落地 / could=`# TODO`
3. **C-3 模糊字段标记**: 字段含糊或 PRD 多解处必须 `# TODO: 待确认 - <原因>`
4. **C-4 Pecker rule_id 注释**: 涉及业务规则字段 (枚举 / 计算 / 排序) 必须引 rule_id
5. **C-5 inferred 显式声明**: 自加字段必须 `# inferred: <reason>`, 否则视为编造

外加配套模板 (implement prompt 模板) + 验收维度 (与 5+2 judge 一一对应).

## Caveat

- **样本不足**: 单 endpoint × 1 run × 2 model × 2 prompt = 4 数据点, 仍是 single-shot. 建议下一轮 multi-run × multi-endpoint × multi-PRD scale 验证 (保守估计需 12-20 个数据点)
- **Path B 模拟**: Codex 用 Anthropic Opus 4.7 + minimal prompt 模拟, 真 Codex API 风格未覆盖
- **Judge 同 vendor**: Sonnet 4.6 既评 Sonnet 4.6 也评 Opus 4.7, 同 vendor 自评偏差未控
- **judge 一致性高**: 4 工况 lineage / ambiguity 都恰好落在 {1, 4, 5} 离散值, 可能 judge 的 anchor 受 prompt 风格的二元印象影响 (见 `summary` 字段表述模式)

## 后续建议

1. **Convention 试跑** (短期, 1-2 endpoint): 对 Codex / Sonnet 同时下发新 convention, 看 cross-vendor lineage 能否稳到 ≥4
2. **Path A 真 Codex 验证** (等 PM 配 OPENAI_API_KEY): 需重跑 2×2 (Codex × Sonnet) × (lineage / minimal)
3. **Multi-PRD scale**: 至少加风鸟诉前调解 / 积分抵扣两个 PRD, 验证 convention 是否泛化
4. **Pecker 输出 schema 升级**: review_items.json 增加 `implement_convention_version` 字段, 强制下游消费

## 成本与时间

| step | duration (s) |
|---|---:|
| Z impl (Opus + lineage) | 117.5 |
| Z judge | ~30 |
| W impl (Sonnet + minimal) | 271.1 |
| W judge | ~90 |
| **新跑合计** | **509.6** |

新跑 token 估算 (按任务 4 比例: X 374s ≈ 6$, Y 165s ≈ 3$):
- Z (Opus impl) ≈ $4-5 (Opus 单价高)
- W (Sonnet impl) ≈ $2-3
- 2 × judge (Sonnet) ≈ $1-2
- **本 follow-up 总成本 ≈ $7-10** (单跑 X+Y 任务 4 已 ≈ $9, 2×2 总账 $16-19)

## 附: 原始产物路径

- `workspace-劳动仲裁/output_codex_cc_compat_2x2_2026_04_28/summary.json`
- `workspace-劳动仲裁/output_codex_cc_compat_2x2_2026_04_28/impl_agent_Z.md`
- `workspace-劳动仲裁/output_codex_cc_compat_2x2_2026_04_28/impl_agent_W.md`
- `workspace-劳动仲裁/output_codex_cc_compat_2x2_2026_04_28/judge_agent_Z.json`
- `workspace-劳动仲裁/output_codex_cc_compat_2x2_2026_04_28/judge_agent_W.json`
- 任务 4 X / Y 产物: `workspace-劳动仲裁/output_codex_cc_compat_2026_04_28/`
- 实验脚本: `scripts/experiment_codex_cc_compat_2x2.py`
