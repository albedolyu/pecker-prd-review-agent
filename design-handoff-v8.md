# 啄木鸟 v8 设计交接 · design-handoff-v8

> 给 claudedesign 的 briefing。本文档是方向性 brief，不是像素稿。完整方案见 `C:\Users\20834\.claude\plans\ui-velvet-koala.md`。

---

## 一句话定位

**这是一个 PM 每天用来做 PRD review 的 AI agent 工作台**。气质是 **Linear + 飞书文档 + Vercel Build Output**，不是 **Kinfolk + 活字印刷**。

---

## v7 → v8 演变脉络

**v7 走偏了**。v7 方向是"线稿 · sage 绿 · 编辑部散文"，把产品做成了一本可读的杂志。两个核心病因：

1. **气质错位** — PM 打开进入阅读状态，不是工作状态。Fraunces serif italic 大标 + sage 绿半透纸卡 + 10 鸟 hero 插画 + 非 4 倍数间距的手工感——服务的是审美，不是效率。
2. **状态反馈弱** — Phase 2"AI 在干活"的核心戏份 UI 几乎没讲；更严重的是 `partial_silent` 类 run（worker 空提交）完全不告警，PM 可能在不完整的结果上做决策。

**v8 转向**：
- 从"读物"切换成"Agent 工作台 + 工作文档"
- 保留"10 只鸟评审"设定（harness 拓扑核心叙事），但鸟从"插画作者"变成"工作 Agent 成员"
- UI 同时承担 **harness 系统的可观测层和反馈信号收集层**——让 PM 看见系统哪里可信、哪里不可信、反馈有复利感

---

## 气质定位（双层设计）

v8 是 **B + A 混搭**，两层共用同一套 design token，Phase 2 在基调上局部变化。

### 日常层（Phase 0 / 1 / 3 / 4）· B 工作文档气质

- **参考系**：飞书文档 · GitHub PR review · Notion AI 侧边栏
- **底色**：浅色中性，略偏冷（不 sage 绿、不米色）
- **字体**：无衬线工作字体族（气质参考 Inter · 苹方 · PingFang，具体你挑）
- **留白**：紧凑，信息密度 ≥ v7 × 2
- **圆角**：≤ 8px 统一
- **阴影**：弱阴影或无阴影
- **色彩**：克制，主要靠 ink 色 + 中性灰 + 1 个强调色

### Phase 2 层 · A Agent 调度中心气质

- **参考系**：Linear · LangSmith trace · Vercel Build Output
- 在日常层 token 上 **色温下降 + 对比度 +20%**，**不做全暗色**
- monospace 局部点缀（token 数、耗时、rule_id 等元数据）
- 状态灯显眼：queued 灰 / running 呼吸动画 / done 实心 / failed 警告色
- 视觉目标：打开这一屏立刻感觉"系统在跑"，和日常层有别但同根同源

---

## 10 只鸟的新定位

**从"刊物署名插画"→"工作 Agent 成员"**

- **鸟 = 头像优先**，三尺寸：32×32（列表 / 状态卡主位）· 24×24（评论旁 / 徽章）· 16×16（内联标签）
- **源**：`web/components/birds/BirdArt-v2.tsx` 现成线稿 SVG 本身**不改**，只改使用尺寸和场景
- **每只鸟 = 身份（头像）+ 职能徽章 + 状态灯** 三元组
- **禁**：hero 大图、整版插画、散文化拟人署名（"数据鸟写道…"那种叙事）

### 10 鸟职能清单

| 编号 | 代号 | 职能 | 类型 | 上线 |
|---|---|---|---|---|
| 1 | 业务鸟 | 业务逻辑完整性 | worker | ✅ |
| 2 | 数据鸟 | 数据字段 / 指标 | worker | ✅ |
| 3 | 体验鸟 | UX 流程 / 交互 | worker | ✅ |
| 4 | 风险鸟 | 风险 / 合规 / 依赖 | worker | ✅ |
| 5 | 苍鹰 | 交叉校验 + 漏报补充 | meta-reviewer | ✅ |
| 6-10 | 5 只 placeholder | TBD | worker | ⬜ |

**关键**：BirdAvatar 组件按 **10 只全集** 设计，不硬编码 5 只。未上线的 5 只给占位头像（可复用现有线稿或空槽样式）。

---

## 5 个 Phase 的视觉形态

### Phase 0 · 上传（B 文档）
单页，中央表单，顶部 PhaseNav 常驻。拖拽上传区 + workspace 选择 + 评审模式。**禁 hero 插画 / 大标语 / 背景装饰**。

### Phase 1 · 知识盲区预检（B 文档）
主体是 PRD 文档视图（DocumentView 渲染）。盲区**不是独立页**，是文档上的 inline 高亮 + 顶部一条汇总条（strong/weak/gaps 计数）。气质：像在看带标注的文档。

### Phase 1.5 · 运行质量检查（**v8 新增必经节点**，A 调度中心）
插在 Phase 2 → Phase 3 之间，**不可跳过**。

- session 分类徽章：`productive` / `partial_silent` / `quota_exhausted` / ...
- effective_consistency 分数（环形图或水平条）
- 5 鸟健康度矩阵
- **失败分类 5 色**：`quota_exhausted` · `tool_call_failed` · `json_parse_error` · `empty_submission` · `timeout`
- CTA：`继续 Phase 3` / `重跑失败 worker`（partial_silent 场景强制二选一）
- 气质：A 调度中心，带警示色但不恐慌

### Phase 2 · 运行中（**独立一屏**，A 气质核心战场）

**分层可视化** —— 这是 Phase 2 最重要的视觉决策：

- **上层**：4 张 AgentStatusCard 并行（worker 层）
- **下层**：1 张苍鹰卡单行（meta 层）
- **中间**：一条**"依赖边"**（线条 / 虚线 / 连接锚），视觉表达苍鹰 waits on workers

每张 AgentStatusCard：头像 32px + 职能徽章 + 状态灯 + 进度条（流式计数）+ 元数据 tag（monospace，token/耗时）。

苍鹰卡的状态文案特殊：`等待 worker 完成` → `交叉校验中` → `漏报补充 N/N`。

底部：RunConsole 实时流式日志 + 当前 worker 提交预览。

### Phase 3 · 逐条确认（B 气质主战场，**最高频**）

左右分栏：**左** PRD 原文（DocumentView，高亮锚点）· **右** 评论 drawer。

评论 drawer 可切换排序：按鸟分组 / 按维度分组。

**每条评论（CommentThread）结构**：
- **顶部**：鸟头像 24px + 职能 + **苍鹰验证徽章**（通过 ✓ / 撤回 ⊖ / 补充 ＋）
- **主文**：评审意见
- **依据区（EvidenceBlock）**：引用原文段落 + **验证状态徽章**（已验证 ✓ / 验证失败 ✗ / 未验证 ⊖）
- **元数据 tag**（monospace 小号）：`业务鸟 · sonnet-4-6 · conf 0.82 · 2.1k tokens · rule=R042`
- **操作**：accept / reject / edit + 键盘快捷键提示

**关键视觉规则**：
- **验证失败的评审项默认折叠 / 弱化**，需主动展开才能 accept
- **confidence < 0.7 的条目视觉弱化**
- 锚点联动：评论 ↔ 原文双向跳转 + 高亮动画
- 底部：批量操作条 + **`➕ 我发现一个他们漏掉的问题`** 入口

### Phase 4 · 报告（B 文档）
工作文档样式的报告页（**不是刊物封面**）。顶部元信息卡（耗时 / token / 接受率 / session 分类 / 版本）。中段按维度归类的评审摘要。底部：**"你的反馈本周影响了 N 条规则权重"** 反馈回声 + 导出按钮（md / 飞书 / pdf）。

---

## 关键交互模式（视觉上必须体现）

1. **键盘优先** — 可键盘操作元素旁有 `j` `k` `y` `n` 等 key 提示徽章（ShortcutHint）
2. **状态四态全局统一** — queued 灰 / running 呼吸动画 / done 实心 / failed 警告色。禁某个卡片独自创造状态色。
3. **PhaseNav 常驻** — 顶部 5 步（含 1.5）节点，当前高亮，已完成可回跳
4. **锚点联动** — 评论 ↔ 原文双向跳转 + 0.3s 高亮淡出

---

## 11 个核心组件 · 设计交付清单

设计稿**按组件逐个产出**（不是按 phase 产出）。每个组件包含：空态 / 常态 / hover / active / disabled / 错误态。

1. **BirdAvatar** — 3 尺寸（32/24/16），10 只鸟全集，状态灯角标
2. **BirdBadge** — 职能标签（业务/数据/体验/风险/苍鹰等）
3. **PhaseNav** — 顶部 5 步（含 1.5）进度条，常驻，支持回跳
4. **AgentStatusCard** — Phase 2 用，头像 + 职能 + 状态 + 进度 + 元数据 + 失败态 recovery action
5. **RunConsole** — Phase 2 用，实时流式日志 + 当前提交预览
6. **RunHealthCheck** — Phase 1.5 用，session 分类 + 5 色失败矩阵 + CTA
7. **CommentThread** — Phase 3 用，评论 + 依据区 + 苍鹰徽章 + confidence tag + accept/reject/edit
8. **EvidenceBlock** — 依据区子组件，引用段落 + 3 态验证徽章
9. **DocumentView** — PRD 原文渲染 + 锚点 + 高亮 + 评论联动
10. **ShortcutHint** — 快捷键提示（角标 / 底部常驻条）
11. **RunDiff** — 管理页 Run 对比，左右分栏 diff（可放 Sprint 4 后期做）

---

## 明确放弃的 v7 元素（禁止使用清单）

| 禁止 | 原因 |
|---|---|
| Fraunces serif italic 大标 | 刊物气质 |
| Noto Serif SC 中文衬线正文 | 阅读气质 |
| sage 绿 `#eef2e5` 主色 | Kinfolk 气质 |
| 半透纸卡 `rgba(255,253,247,0.45)` | 手作气质 |
| 12px 以上软圆角 | 装饰过度 |
| 非 4 倍数间距（22 / 42 手工感） | 反工具气质 |
| 10 鸟 hero 插画 | 抢戏、不工作 |
| "编辑部 · 刊头 · 散文 · 署名 · 活字印刷"叙事 | 定位错误 |
| eyebrow + 大标 + lead 的刊头式页头 | 章节感取代流程感 |

---

## 色彩 / 字体 / 间距方向（你填细节）

### 色彩
- 基调：浅色中性，略偏冷
- ink 色作主文字
- **1 个强调色** 用于 CTA / 锚点 / running 状态
- 状态色：success / warning / error / info 四色齐备
- Phase 2 层在基调上色温下降 + 对比提升

### 字体
- 主字体族：无衬线工作字体（Inter · 苹方 · PingFang 气质）
- monospace：元数据、token 计数、rule_id、耗时
- **禁所有 serif / italic 装饰**

### 间距 / 网格
- 回归 **4 / 8 倍数标准网格**
- **禁 22 / 42 这类非整数倍手工感间距**
- 信息密度：Phase 3 每屏至少同时显示 3-5 条评审意见

### 圆角
- ≤ 8px，统一
- 状态徽章可用 pill 形

### 阴影
- 弱阴影或无阴影
- **禁 blur / glass / neomorphism**

### 动效
- 允许：呼吸灯（running）· 实时流滚动 · 锚点跳转高亮
- **禁装饰性动效**：无意义 hover 位移、抖动、弹跳、粒子

---

## 你的交付物

1. **`design-system/啄木鸟-pecker-v8/MASTER.md`** — v8 完整设计规范（token 表 + 字体 + 间距 + 色彩 + 动效）
2. **11 个核心组件的视觉稿**（所有状态齐备）
3. **5 个 Phase（含 1.5）的整屏组合稿**（用上述组件拼）
4. **10 只鸟头像 3 尺寸的最终稿**
5. （可选但建议）**token JSON** — 便于前端落 CSS 变量

---

## 检验标准（交付前自检）

### 盲测 · 这是什么产品？
随机截任一屏给不懂这个项目的朋友看，让 TA 猜"这是什么产品"：
- ✅ 能猜：AI 工具 / 协作工具 / 开发者工具 / 企业工具
- ❌ 若猜：博客 / 杂志 / 艺术网站 / 文学刊物 — **不合格**

### Linear vs Kinfolk 测
问"这像 Linear 还是像 Kinfolk" → **必须是 Linear**

### harness 可读性测
- 打开 **Phase 2** 截图 → 3 秒内能说出"哪只鸟在跑 / 哪只鸟完成 / 谁失败"
- 打开 **Phase 3** 截图 → 5 秒内能说出"哪条评审意见的依据经过验证 / 哪条未验证"

### 信息密度测
- Phase 3 一屏至少 3-5 条评审意见可见
- v7 的同屏信息量 × 2 是基线

---

## 附：与 v7 文档的关系

- v7 规范 `design-system/啄木鸟-pecker/MASTER.md` → 归档，不再引用
- v7 briefing `design-handoff.md` → 归档
- v7 组件 `PhaseHead` / `primitives.tsx`（PaperCard/NumberedField/…）/ `BirdArt.tsx`（旧彩色版）→ 标 `@deprecated-v7`，新设计不使用

如果你对本 briefing 的任何方向有质疑，回来和 PM 对齐再开工，不要自己猜。
