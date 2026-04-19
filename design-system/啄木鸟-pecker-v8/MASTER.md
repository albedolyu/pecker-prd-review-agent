# 啄木鸟 v8 · Design System · MASTER

> **定位**：PM 每天用来做 PRD review 的 AI agent 工作台。
> **气质**：Linear + 飞书文档 + Vercel Build Output。
> **版本**：v8（替换 v7 的线稿 · sage 绿 · 编辑部散文方向）。

本文档是前端落地 source-of-truth。所有 token 见 `tokens.css`。所有组件稿见 `canvas.html`。

---

## 1 · 气质决策

**双层设计，共用 token：**

| 层 | Phase | 气质 | 参考 |
|---|---|---|---|
| **日常层 B** | 0 / 1 / 3 / 4 | 工作文档 | 飞书 · GitHub PR · Notion AI |
| **Agent 层 A** | 2（含 1.5 警示） | 调度中心 | Linear · LangSmith · Vercel Build |

**A 层实现方式**：在日常层 token 上通过 `data-phase2` 属性局部覆盖——`surface` 色温下降一档、`text` 对比度提升。**不做整屏深色**。Phase 2 的 RunConsole 区域局部切深色卡（`--surface-console`），提供「系统在跑」的质感锚点而不破坏一致性。

---

## 2 · Color

### 2.1 Neutral（略偏冷的 slate 调）
`--neutral-0` 到 `--neutral-900` 十三档。浅底 `--neutral-25`；ink `--neutral-800`；hairline border `--neutral-200`。**禁 sage 绿 / 米色 / 纸色。**

### 2.2 Accent — `#E8590C` burnt-orange
单一强调色，用于：**CTA · 锚点 · running 状态 · 焦点环 · 选中态**。禁在装饰性位置（分隔线、背景色块）使用。`--accent-500` 主 tone；`--accent-50` 做 running badge 底。

### 2.3 Status 四色 + pill
| role | bg | fg | dot | 用法 |
|---|---|---|---|---|
| queued | `--status-queued-bg` | 灰 | 实心灰点 | 未开始 |
| running | 浅橙 | 橙 | **呼吸橙点 + halo** | AI 干活中 |
| done | 浅绿 | 墨绿 | 实心绿点 | 完成 |
| failed | 浅红 | 警示红 | 实心红点 | 失败 |
| warn / info | 黄 / 蓝 | — | — | 辅助 |

**规则**：状态色由 token 定义，**禁任何单独组件自造状态色**。

### 2.4 Phase 1.5 的 5 色失败分类
| code | token | 含义 |
|---|---|---|
| `quota_exhausted` | `--fail-quota`（赭橙） | 配额打满 |
| `tool_call_failed` | `--fail-tool`（警示红） | 工具调用挂了 |
| `json_parse_error` | `--fail-json`（棕黄） | 解析失败 |
| `empty_submission` | `--fail-empty`（中性灰） | worker 空提交（静默失败） |
| `timeout` | `--fail-timeout`（钢蓝） | 超时 |

「静默失败」刻意用**冷灰**——这是最危险的状态（PM 可能误以为正常），用冷灰比红更合适：不喊叫，但永远"在场"。

### 2.5 10 只鸟的识别色
worker 四鸟（业务/数据/体验/风险）对应 status 主色系的暗化版；苍鹰用**深紫 #4d3a86** 与 worker 层在 hue 上明确拉开（meta 层 ≠ worker 层的视觉承诺）；6-10 占位用中性灰，避免未上线的鸟抢色彩记忆。

---

## 3 · Typography

**主字体族**：`Geist` → `-apple-system` → `PingFang SC` → `Microsoft YaHei` → `system-ui`
**Mono**：`Geist Mono` → `ui-monospace` → `JetBrains Mono` → `Menlo`

选择 Geist 的原因：气质和 briefing 的 Linear/Vercel 参考系同源；规避了 Inter 的 AI-slop 过度使用；和苹方/PingFang 的中英混排视觉重量接近。

**禁**：所有 serif、italic（装饰性）、Fraunces、Noto Serif SC、Roboto、Inter、默认 Arial。

### Scale（紧凑 · PM 工作台）
| token | size | 用途 |
|---|---|---|
| `--text-xs` | 11 | 徽章、shortcut hint |
| `--text-sm` | 12 | 元数据、mono 辅助 |
| `--text-base` | 13 | UI 默认 |
| `--text-md` | 14 | 正文、评论主文 |
| `--text-lg` | 16 | 小标题 |
| `--text-xl` | 20 | 区块标题 |
| `--text-2xl` | 24 | 页标题 |
| `--text-3xl` | 32 | 最大（报告摘要数字） |

**Mono 用法**：仅用于元数据（token 数、耗时、rule_id、model 名、confidence）。**禁在主文案用 mono 装饰。**

---

## 4 · Spacing & Layout

- **严格 4/8 倍数**：`0 / 4 / 8 / 12 / 16 / 20 / 24 / 32 / 40 / 48 / 64`
- **禁 22 / 42 等手工感非整数倍**
- **Phase 3 同屏可见评论数 ≥ 3-5 条**（briefing 要求 · v7 × 2 信息密度）
- 页面 gutter：桌面 24-32 · drawer 16-20 · 卡片内 padding 16

## 5 · Radius

`0 / 2 / 4 / 6 / 8`。卡片 / 按钮统一 `--r-4: 8px`；pill 徽章 `999px`。**禁 12+ 大软圆角。**

## 6 · Shadow

三档弱阴影（`--shadow-sm/md/lg`）+ 焦点环。**禁 blur / glass / neomorphism / 彩色光晕。**

---

## 7 · Motion

**允许**：
- `running` 状态的呼吸点（`dot-breathe` 1.4s 循环 + `dot-halo` 2s 脉冲）
- 实时流式日志滚动（RunConsole）
- 锚点跳转：目标位置 0.3s 橙色 fade

**禁**：hover 位移、缩放弹跳、粒子、装饰性转场。

---

## 8 · 11 个核心组件（清单 + 设计决策）

| # | 组件 | 关键决策 |
|---|---|---|
| 1 | **BirdAvatar** | 32/24/16 三尺寸；状态灯做右下角小点（不重叠线稿轮廓）；`data-bird="1..10"` 切色 |
| 2 | **BirdBadge** | pill 形 · `<dot>职能名`；worker 4 色 + meta 紫 + 占位灰 |
| 3 | **PhaseNav** | 顶部水平 5 段（0 · 1 · 1.5 · 2 · 3 · 4）；1.5 做**不可跳过**的警示样式（警告三角） |
| 4 | **AgentStatusCard** | 头像 + BirdBadge + 状态灯 + 进度条 + mono 元数据；worker 卡等宽并行；失败态内置 Retry CTA |
| 5 | **RunConsole** | 局部深色（`--surface-console`），时间戳 · 来源 · 内容三列；流式光标 |
| 6 | **RunHealthCheck** | session 分类大徽章 + `effective_consistency` 环形 + 5 色矩阵；`partial_silent` 强制二选一 CTA |
| 7 | **CommentThread** | 验证失败默认折叠 · 低 confidence 弱化；mono 元数据行 |
| 8 | **EvidenceBlock** | 引用段（左侧 2px accent 条） + 3 态验证徽章 |
| 9 | **DocumentView** | 行号 + 锚点 inline 高亮 + 汇总条（strong/weak/gaps 计数） |
| 10 | **ShortcutHint** | 11px 深色 pill；`j/k/y/n` 单字符；inline 贴在可操作元素右侧 |
| 11 | **RunDiff** | Sprint 4 后期 · 左右分栏 diff（本轮不稿） |

---

## 9 · Phase 2 的关键视觉决策 · 依赖边

briefing 要求「上层 4 worker + 下层 1 meta + 中间依赖边」。依赖边采用**汇聚式虚线 + 末端锚点**：

- 4 worker 卡底部各一个锚点 (•)
- 苍鹰卡顶部一个锚点 (◇)
- 虚线从 4 个 worker 锚点向下汇聚到苍鹰锚点
- worker `done` 时对应那条虚线**变实线 + 流向动画**（点沿线段移动），视觉表达「这条依赖已满足」
- worker 全部 `done` 后苍鹰卡从 `queued` → `running`

这不是装饰，是 briefing 点名的"系统叙事"。

---

## 10 · 验收自检（briefing 要求）

- [ ] 盲测：随机截屏 → 「AI 工具 / 开发者工具」而不是「杂志 / 博客」
- [ ] Linear vs Kinfolk → Linear
- [ ] Phase 2 截图 3s 内能说出哪只鸟在跑 / 完成 / 失败
- [ ] Phase 3 截图 5s 内能说出哪条评审的依据已验证 / 未验证
- [ ] Phase 3 每屏 ≥ 3-5 条评审

---

## 11 · 禁止清单（v7 → v8 明确放弃）

Fraunces · Noto Serif SC · sage `#eef2e5` · 半透纸卡 · 12+ 大圆角 · 22/42 手工感间距 · 10 鸟 hero 插画 · "编辑部·散文·署名·活字印刷"叙事 · eyebrow+大标+lead 刊头式页头。

---

## 12 · 本轮交付

- ✅ `tokens.css` — 双主题 + Phase 2 覆盖
- ✅ `MASTER.md` — 本文档
- ✅ `components/bird-avatar.jsx` — 占位鸟（等 BirdArt-v2 替换）
- ✅ `components/bird-badge.jsx`
- ✅ `components/phase-nav.jsx`
- ✅ `components/agent-status-card.jsx`
- ✅ `canvas.html` — 所有状态铺在 design canvas 上
- ⏳ 其余 7 组件 · 5 Phase 整屏稿 → 下一轮
