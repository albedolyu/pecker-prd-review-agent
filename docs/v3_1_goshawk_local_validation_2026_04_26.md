# v3.1 + goshawk_mode=local 验证 (2026-04-26)

**结论先行**: 在劳动仲裁这一对照下,**苍鹰 LOCAL 模式不仅没省时,反而比 FULL 模式慢 13.4%** (goshawk 阶段 +31s),且在 sparse-wiki 场景下 LOCAL 模式 must 项数量与 FULL 持平 (10 vs 11),内容上各漏对方部分 must 项 (sampling noise 主导,无法仅归因于局部化)。**不推荐 goshawk_mode=local 做 default**。

---

## 0. 执行情况说明 (降级)

原计划跑 4 run (fengniao + 劳动仲裁 各 full/local),实际:

| # | workspace | mode | 状态 |
|---|---|---|---|
| 1 | fengniao-mediation | full | 失败 (cli backend "对话太长" 退出码 1, retry 3 次都炸在第二个 sonnet read_file 调用) |
| 2 | fengniao-mediation | local | 失败 (同 #1 错因) |
| 3 | 劳动仲裁 | full | **完成** |
| 4 | 劳动仲裁 | local | **完成** |

**降级原因**: fengniao workspace 在当前 cli backend 状态下 system prompt 触发 transient "对话太长" 硬错误,无法绕开 (任务约束: 禁止改源码)。劳动仲裁 workspace 在同 backend 上能跑通,因此实测对比仅基于劳动仲裁这一对样本 (n=2, 不是 n=4)。

实测对比仍可作为**首版信号**,但**单 PRD n=2 无法控住 sampling noise** — memory `pecker_sprint_day3_2026_04_26.md` 已确认 pecker 单 run 间 N0 浮动 50% / merged_to_facet 浮动 125%,所以本报告 verdict 偏 conservative。

---

## 1. 跑批结果

| run | workspace | mode | total | worker wall | goshawk (jsonl Δ) | goshawk (内部 timer) | items final | must | cost | session jsonl |
|-----|-----------|------|------:|------------:|------------------:|--------------------:|------------:|-----:|-----:|---------------|
| 1 | fengniao | full | N/A | N/A | N/A | N/A | N/A | N/A | N/A | (失败,见 §0) |
| 2 | fengniao | local | N/A | N/A | N/A | N/A | N/A | N/A | N/A | (失败,见 §0) |
| 3 | 劳动仲裁 | full | **654.9s** | 257.0s | 232.9s | 317.6s | 22 | 11 | $2.54 | rev_1777206876_13907346.jsonl |
| 4 | 劳动仲裁 | local | **671.9s** | 253.2s | **264.1s** | **513.0s** | 23 | 10 | $2.87 | rev_1777208075_3a64b406.jsonl |

**字段说明**:
- `total` = `review_started` → `final_reviewer_done` 事件墙钟差 (jsonl 真实事件时间戳)
- `worker wall` = `workers_started` → `checkpoint`
- `goshawk (jsonl Δ)` = `final_reviewer_started` → `final_reviewer_done` 事件差
- `goshawk (内部 timer)` = pecker stdout 报告的 `[苍鹰 meta 评审] done (Xs)`,**比 jsonl 大** (含 setup/teardown,推测包了 advisor 内部多次 cli 调用的 wait 时间)
- `must` = final review_items.json 里 severity=must 计数

**关键观察**:
- worker wall 几乎相同 (Δ=−3.8s, 1.5%): 验证 LOCAL 只动苍鹰,不影响 worker 阶段 ✓
- goshawk **变慢** 31.2s (jsonl) / 195.4s (内部 timer)
- cost 反而 **+$0.33 (+13%)**,因为苍鹰看了更多 item (Run 4 N3=23 vs Run 3 N3=22) 且额外 cli call 开销

---

## 2. 时间节省 (local vs full) — 反方向

| workspace | total Δ | goshawk (jsonl) Δ | goshawk (timer) Δ | 节省比例 |
|-----------|--------:|------------------:|------------------:|---------:|
| 劳动仲裁 | **+17.0s** (+2.6%) | **+31.2s** (+13.4%) | **+195.4s** (+61.5%) | **负节省** |

**完全没省**,反而更慢。验收标准 (≥10% 节省) **不达成**。

### 为什么反向?

1. **`_select_high_priority_items` 过滤后实际筛选项 ≈ 全集** — Run 4 raw 26 items, evidence_verify 后 21 items,其中 must severity 已经多 (劳动仲裁字段歧义 / 移动端缺失等典型 must 模式),又叠加 wiki sparse 全部走 verified_with_caveat (LOCAL 模式条件之一),几乎所有 item 都被选中要 goshawk,根本起不到"局部化"效果。
2. **苍鹰内部 timer (513s) >> jsonl 间隔 (264s)** 暗示 LOCAL 路径触发了**额外 cli 调用** (推测是 facet 检测 / 跨章节合并的 advisor_review tool 多调一轮),消耗了苍鹰内部 wait 但事件没 emit。
3. **Run 4 N3=23 > Run 3 N3=22**,苍鹰 added 项数也是 2 vs 2 (相同),merged_to_facet 同 4 — funnel 结构相似,**但绝对耗时反向**。

---

## 3. 质量对比 (item-level)

按内容相似度配对 must (R-编号在两 run 间不一致,需按 location+issue 主题匹配):

| 主题 | Run 3 (FULL) must | Run 4 (LOCAL) must | 状态 |
|------|---|---|---|
| 通配符示例前后矛盾 (1.4 脱敏) | R-005 | R-001 | 双方都有 ✓ |
| 风险扫描 1.2 占位空白 | R-003 | R-005 | 双方都有 ✓ |
| 移动端 2.3.3 占位 | R-007 | R-004 | 双方都有 ✓ |
| AI Coding 鉴权 TBD | R-010 | R-007 | 双方都有 ✓ |
| 主表 vs ent 字段类型不一致 | R-012 | R-008 | 双方都有 ✓ |
| 多模块缺 API 规范 | R-026 | R-010 (扩了风险扫描+标签) | 双方都有,Run 4 范围更广 ✓ |
| **FR-17 vs 3.4 标签矛盾** | R-001 | (无) | **Run 4 LOCAL 漏** |
| **筛选超 30 条数据** | R-006 | (无) | **Run 4 LOCAL 漏** |
| **content 跨页跳转转换逻辑** | R-008 | (无) | **Run 4 LOCAL 漏** |
| **content HTML 模板** | R-013 | (无 must,可能在 should 不同表述) | **Run 4 LOCAL 漏** |
| **unique_id MD5 case_code NULL** | R-015 | (无) | **Run 4 LOCAL 漏** |
| 字段差异 (搜索 4 字段 vs 主页 3 字段) | (无) | R-002 | **Run 3 FULL 漏** |
| 仲裁详情弹层布局缺失 | (无) | R-006 | **Run 3 FULL 漏** |
| 移动端 vs Web 筛选维度不一致 | (无) | R-009 | **Run 3 FULL 漏** |

**汇总**:
- Run 4 LOCAL 漏掉 Run 3 FULL 抓到的 **5 条 must**
- Run 3 FULL 漏掉 Run 4 LOCAL 抓到的 **3 条 must**
- 双方共有 must: 6 条
- Run 3 must = 6+5 = 11; Run 4 must = 6+3 = 9 实际 must,加上 R-027 (单方有但配不上对) = 10 — 与文件计数 11 / 10 一致

### 必须做的 caveat: 这不是"LOCAL 漏 must" 的强证据

- 单 PRD n=2,**完全无法分离 sampling noise vs 苍鹰局部化损失**
- worker raw items 分布 Run 3 (8/7/7/3) vs Run 4 (7/7/10/2) **本来就不同**,苍鹰只是在 worker 给的食材上做选择,差异源头在 worker
- 配对结果显示 **双向漏报近似对称** (5 vs 3),不是单边故事 — 这是 sampling noise 的特征,不是局部化故障特征
- 所以**不能下"LOCAL 模式遗漏 5 条 must"的强结论**

---

## 4. Verdict

### 必须达成的两个条件
- [ ] total 时间至少 ≥10% 节省 → **未达成** (实测 −2.6%,负节省)
- [?] 0 must-severity item 被漏 → **数据噪声大,无法判定** (双向都漏)

### 推荐: **维持 full 做 default**

理由 (按强度排序):

1. **耗时硬不达标** (强证据): 在唯一一个能跑通的 workspace 上,LOCAL 不仅没省时,反而 +13.4% goshawk wall + 苍鹰内部 timer +61.5%。这一条已经足以否决 default 改动。
2. **fengniao 跑不出来**: 即使 fengniao 能跑,它 baseline goshawk 只有 125.8s,LOCAL 即使 −20% 也只省 25s 绝对值小,而劳动仲裁这种慢 PRD (goshawk 232s+) 才是真值得优化的场景 — 而正是在这种场景上 LOCAL 反而慢。**ROI 完全反向**。
3. **`_select_high_priority_items` 过滤条件在 sparse-wiki 真业务场景下退化为"几乎全选"**: must / 低 conf / cross_boundary / caveat / retracted / facet 这几类的并集,在劳动仲裁这种字段密集 PRD 下覆盖了大部分 worker raw items (21/26 经 evidence_verify 已是 verified_with_caveat 全降权),所以局部化失效。
4. **质量信号弱阳但样本不足**: LOCAL 漏了 5 条 FULL 抓到的 must (筛选超 30 / FR-17 vs 3.4 标签 / content 转换 / HTML 模板 / unique_id MD5),这些是真业务关键问题。但 FULL 也漏了 3 条 LOCAL 抓到的,所以**信号被 sampling noise 完全混淆**,**单凭 n=2 不能下质量结论**。

### 应该怎么做 (非本任务范围,只是建议)

LOCAL 模式不该作为全局 default,但可以:
- 保留为可选 env (现状),让用户在小 PRD / wiki rich 场景手动开
- 在 `_select_high_priority_items` 加一道软上限,比如 N3 > 15 时自动 fallback 回 full,避免劳动仲裁这种"几乎全选"退化
- 或者根本上重新审视 LOCAL 的实现 — 看苍鹰内部 timer 比 jsonl Δ 多 248.9s 是不是代码问题 (multiple advisor_review 调用)

---

## 5. 风险记录

| 类型 | 详情 |
|------|------|
| 失败 | Run 1 fengniao full: cli backend "对话太长" 退出码 1, retry 3 次均失败,均死在第 2 个 sonnet read_file 调用 (req=c9cfcc71 / 184f29af / cc176481 三次都同样) |
| 失败 | Run 2 fengniao local: 同上,死在 req=50a229d7 |
| sampling noise | Run 3/4 worker raw 分布差异 (data_quality 3 vs 2,ai_coding 7 vs 10),N0 计数差 1 (25 vs 26),已在 memory `pecker_sprint_day3_2026_04_26.md` 标注为 pecker 已知噪声 |
| 苍鹰内部 timer 异常 | Run 4 苍鹰 timer 513s vs jsonl event Δ 264s,差 249s 不在标准事件范围内,LOCAL 模式可能触发额外 cli 调用 (建议看 goshawk_advisor.py) |
| 成本上限 | 已用 $5.41 (Run 3 $2.54 + Run 4 $2.87),未触 $10 上限 |
| 时间上限 | Run 3 实际 ~16min, Run 4 实际 ~21min, 单 run 已超 15min 软限,但都跑完没卡死,无降级跳过 |

---

## 附录: 数据一致性自检

- Run 3 jsonl `total_ms` (review_completed.duration_ms = 256945) 只覆盖到 worker 完成,**不含苍鹰**。本报告 `total` 字段用 `final_reviewer_done` − `review_started` 真实墙钟,与 baseline `docs/timing_profile_2026_04_26.md` 算法一致。
- Run 4 jsonl 完整,N3=23 ↔ 文件 review_items.json 23 条 ↔ 报告 must=10 ↔ 全部相符。
- baseline `docs/timing_profile_2026_04_26.md` 劳动仲裁 baseline = 561.0s/90.6s — 与本次 Run 3 (654.9s/232.9s) 差异较大: baseline 那次 N3=3 仅 3 个 item 苍鹰只看 3 个(快),本次 22 个(慢) — **再次印证 sampling noise 主导**。
