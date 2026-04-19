# 啄木鸟 Pecker · 设计 handoff brief (v7 · ARCHIVED)

> **⚠ 已归档 · 2026-04-18**
> 本 briefing 的设计方向("线稿·sage 绿·散文化刊头")已被 v8 "Agent 工作台"气质完整替代。
> 当前有效的设计 brief 请看:
> - `design-handoff-v8.md`(v8 方向 briefing)
> - `design-system/啄木鸟-pecker-v8/MASTER.md`(v8 设计规范)
>
> 本文档保留作为历史参考,禁止新页面引用。

---

# 啄木鸟 Pecker · 设计 handoff brief (v7 原文)

> 本文档是给下一位设计师(人或 Claude Design)的一次性 briefing。
> 读完这份 + 附件中的 4 个 v7 HTML + MASTER.md,就能接着往下做。

---

## 0. 一句话

**啄木鸟 Pecker** 是 PM 用的 PRD 评审工具 —— 4 位虚拟编辑并行审稿 + 1 位终审交叉校验 + 报告可下载 / 存 wiki / 推飞书。

内部工具,但追求极致视觉。核心差异化:**不像 SaaS 控制台,像编辑部**。

---

## 1. 已经定了的设计方向:**v7 线稿现代散文**

整个产品经历过三代视觉:

| 代 | 气质 | 现状 |
|---|---|---|
| v1 | 内刊印刷感(kraft / tape / grain / 错位 shadow) | **已弃用**,保留 token 兼容老页面 |
| v4 | Ghibli 水彩手作(wobbly radius / tilt / hard offset shadow) | **已弃用**,token 标 `@deprecated-v7` |
| **v7** | **线稿 · 现代散文 · 克制** | **当前主方向** |

### v7 的视觉公式(必须遵守)
- **背景**: sage 浅绿 `#eef2e5` + 一层单层水彩雾(右上角淡绿径向渐变)
- **卡片**: 1px border `rgba(58,66,56,0.22)` · 12px radius · 半透纸底 `rgba(255,253,247,0.45)` · **无 tilt / 无 hard shadow / 无 wobbly**
- **字体**: Fraunces 衬线(带 italic 变体) + Noto Serif SC 中文 + JetBrains Mono 小号 eyebrow
- **CTA**: 1.5px 墨色 border + 右箭头 → · hover 时整个按钮反白(墨底米字)
- **输入**: 下划线式 · focus 时下划线变粗变深
- **编号**: 每个表单字段以 `01 · 标签` 起手,moss 绿 Mono 小号
- **插画**: 全部走线稿 SVG(ink stroke 1.5-2px,辅以少量橙/朱/moss 点缀),不要填色块

### v7 的反模式(禁止)
- ❌ 饱和果冻色 / 霓虹
- ❌ blur 模糊阴影(card 默认)
- ❌ 满屏饱和红(红色只作校稿笔痕 / CTA 点缀)
- ❌ 机械弹簧动效(偏 sine 呼吸)
- ❌ emoji 当 icon
- ❌ v1/v4 遗留的 tilt / wobbly / hard-shadow 再次出现

### 仍然允许的一些装饰
- 斜体衬线 em 作为标题里的强调(moss 绿色)
- `ink-mark` 红笔划(偶尔,不滥用)
- 飘叶粒子 / 小灯串 / 苔藓点 等环境叙事装饰
- prefers-reduced-motion 兜底

### 1.5 · 边界:Ghibli 美学能做到哪一步(读这段再开工)

本产品的设计方向是"宫崎骏式手作美感"(见 MASTER.md 第一段)。v7 线稿克制是这棵树上长出来的一支 · 不是换方向。
你(Claude Design)在这条美学线上的**能力边界**如下,开工前先对齐:

**✅ 你应该主动交付**
- 视觉 token 系统(颜色 / 字体 / 间距 / 圆角 / 阴影)
- 布局气口(非对称 split · 留白 · "坏掉的几何" 非 4 倍数间距)
- **简单线稿 SVG**: 鸟 / 树 / 柴门 / 小灯 / 苔藓 / 远山两笔 —— 现有 `BirdArt-v2.tsx` 10 只鸟就是参考基线,照这档做
- 克制动效(呼吸 opacity · 飘叶粒子 · 1-2px hover 微浮)
- 纸纤维 / 水彩色雾(多层 radial-gradient + SVG feTurbulence 伪造 ~80% 的手绘感)

**⚠️ 你不要试图做的**
- **整幅场景画**(例"一只鸟栖在夕阳下的枝头,背后是远山")—— SVG 画出来会是儿童简笔画,不是 Ghibli
- **封面大图 / landing 主视觉**(需要真·画面叙事)
- **角色表情动画 / 逐帧动态**(那是 Lottie + 动效师的活)
- **"龙猫级"复杂插画** —— 就算我鼓励你做,你做出来也会拉低整体品质

**→ 这些活的正确分工**

MASTER.md 最后一节已经定了:

> 10 只鸟插画 · 来源 Midjourney / Nano Banana / 插画师 —— **不用 SVG 代码画,从图像模型出**

所以遇到"需要一张大图 / 复杂插画"的节点,**请直接在回复里标注**:
> ⚠ 这里建议用 Midjourney 出一张图,提示词参考:"__(你给的 prompt)__",然后用 `<img>` 或 `background-image` 接进来,SVG 槽位保留在 `position: absolute; inset: 0;`

**判断口诀**: 如果这张图超过 10 种线 / 需要渐变填充 / 需要材质表达 · 就别用 SVG,留图像模型的槽。

---

## 2. 核心 tokens(直接抄)

### 颜色

```css
/* Sage 家族 —— v7 主调 */
--bg:              #eef2e5;   /* 主背景 */
--sage-light:      #dbe4cf;   /* 卡底 */
--sage:            #b8ccb0;   /* 水彩雾 */

/* 墨色 */
--ink:             #3a4238;   /* 正文 · 边框 · CTA 描边 */
--ink-deep:        #1a1e18;   /* 眼珠 · 最深文字 */
--ink-soft:        #5c6158;   /* 次要文字 */
--ink-mute:        #8a8a80;   /* meta / 提示 */

/* 叙事色(克制使用) */
--moss-deep:       #5d7357;   /* running 态 · eyebrow · italic em */
--moss:            #8ba888;   /* 辅助绿 */
--rose:            #c98e7f;   /* done 态柔绯 */
--red:             #b85c4a;   /* 校稿红 · 蜡封朱 · 红冠 · ink-mark */
--amber:           #d4a05e;   /* 喙 · 小灯 */
--wood:            #a67c52;   /* 木质 */
--wood-deep:       #6b4e32;   /* 爪 · 深木 */

/* 纸白(少量) */
--paper:           #fffdf7;   /* 卡内半透纸底 · 通常带 alpha 0.45 */
```

### 字体栈

```css
/* 从 Google Fonts 引入 */
@import url('https://fonts.googleapis.com/css2?family=Fraunces:opsz,ital,wght@9..144,0,300;9..144,0,400;9..144,0,500;9..144,1,300;9..144,1,400&family=Noto+Serif+SC:wght@300;400;500&family=JetBrains+Mono:wght@400;500&display=swap');

/* 用途 */
- Display / h1 / 标题:      Fraunces + Noto Serif SC (serif, opsz 响应)
- Body 中英混排:            Noto Serif SC (light 300 / regular 400)
- UI 按钮 / 标签:           Fraunces medium 500(同系列,不换 Inter)
- meta / eyebrow / 编号:    JetBrains Mono 400 · uppercase · letter-spacing 0.2em+
- 手写 caption(慎用):       Caveat
```

**规则**:
- 大号 serif `letter-spacing: -0.015em`
- 正文 `letter-spacing: 0.005em`,line-height 1.85-1.95
- italic 用于 subtitle / meta / 引用 / 标题里的 em —— 杂志 caption 节奏
- 中文 fallback: `Noto Serif SC → PingFang SC → Microsoft YaHei`

### 间距 / 圆角 / 阴影

```css
--radius: 12px;            /* 默认卡片,v7 统一值 */
--radius-sm: 8px;          /* 小按钮 / input 框 */
--radius-pill: 999px;

/* 手工"非 4 倍数"间距 —— 打破网格感 */
--space-col:    22px;      /* 栏间 */
--space-gutter: 42px;      /* 大 gutter */
--space-hang:   11px;      /* 挂件错位(v7 基本不用) */

/* v7 不用 hard shadow,卡片默认无阴影,靠 1px border + 半透背景分层 */
/* 仅 modal/popover 才用 soft shadow */
```

### 全页背景配方

```css
body {
  background: #eef2e5;
  background-image: radial-gradient(ellipse 65% 50% at 80% 15%, rgba(184,204,176,0.35), transparent 70%);
  background-attachment: fixed;
  font-family: 'Noto Serif SC','PingFang SC',serif;
  font-weight: 300;
  color: #3a4238;
}
```

### 动效

```css
--ease-breath: cubic-bezier(0.37, 0, 0.63, 1);
--ease-gentle: cubic-bezier(0.22, 1.36, 0.64, 1);
--duration-fast: 200ms;
--duration-med:  400ms;

/* 只有两种默认动效 */
@keyframes pecker-breathe { /* 透明度呼吸,2.8s 循环 */ }
@keyframes pecker-fade-in { /* 2px 上浮 + 淡入,0.4s */ }

@media (prefers-reduced-motion: reduce) {
  * { animation: none !important; }
}
```

---

## 3. 品牌 IP · 10 只鸟

产品里鸟是一等叙事元素,每个角色都有**职能定位 + 人设描述 + 识别色**。
卡片 SVG 线稿已全部实现,见附件 `BirdArt-v2.tsx`(viewBox 100x100,stroke 1.6-1.8)。

| key | 职能名(UI 展示) | 原鸟名 | 职责 | 是否 worker | 备注颜色 |
|---|---|---|---|---|---|
| `editor-in-chief` | 主编 | 啄木鸟 | 主控协调 | ❌ | 红冠 + 橙喙 · 产品自身,UI 不出现 |
| `structure` | 责编 | 织布鸟 | 结构 / 格式 / 信息密度 | ✅ worker | 黄冠 + 分叉尾 + 线团道具 |
| `quality` | 审校 | 猫头鹰 | 质量 / 逻辑 / 合规 | ✅ worker | 圆盘脸 + 眼镜 + 肚斑 |
| `ai_coding` | 技术编辑 | 渡鸦 | AI Coding 友好度 / 技术约定 | ✅ worker(Opus) | 瘦长 + 翘尾 + 钢笔 |
| `data_quality` | 数据核对员 | 鸬鹚 | 字段映射 / 数值核对 | ✅ worker | S 颈 + 站水边 + 晾翅 |
| `final-reviewer` | 终审 | 苍鹰 | 交叉校验(撤误报 / 补漏报 / 判冲突) | ❌ meta | 钩喙 + 单片眼镜 + 翅膀纹 |
| `reader-feedback` | 读者反馈员 | 信鸽 | 下游信号采集 · EMA 回流 | ❌ bg | 鼓胸 + 扇形尾 + 信卷 |
| `sample-reader` | 试读员 | 杜鹃 | 评审质量 eval · CI 门禁 | ❌ bg | 超长尾 + 肚纹 + 印章 |
| `archivist` | 资料员 | 鸮鹦 | wiki 运维 | ❌ bg | 圆胖 + 头顶绒毛 + 坐书堆 |
| `qa-gatekeeper` | 质检员 | 伯劳 | push 前门禁(密钥 / IP / 临时文件) | ❌ bg | 黑眼罩 + 长尾 + 栖横枝 |

**规则**:
- UI 主视觉只出现前 5 只(4 worker + 终审),其他 5 只留给 tooltip / about 页 / 后台任务插画
- 命名优先用中文职能词(主编/责编/审校),**不要在主 UI 里出现"织布鸟"这种生僻字**,鸟名留在 tooltip 和散文叙事里
- 情绪语调: 散文感 · 拟人但不卡通 · 不要"老铁""宝子"此类网红语,参考"树洞里备了茶,十只鸟等着"这种节奏

---

## 4. 信息架构

```
/                        Landing(ForestLanding.tsx,还是 v1 风,未 v7 化)
  ↓
/login                   柴门 scene + 登录卡(已 v7)
  ↓
/review                  5 phase wizard:
    ├── Phase 0  上传     已 v7 · 左树场景 + 右投稿表单
    ├── Phase 1  预检     已 v7 · 3 列结果(强/弱/盲区)+ 补充说明
    ├── Phase 2  评审中   已 v7 · 横枝进度 + 4 工作卡 + 苍鹰独立一行
    ├── Phase 3  逐条确认 已 v7 · stats + Tabs + item 卡(accept/edit/reject)
    └── Phase 4  报告出口 已 v7 · 封面 + 章节摘要 + 苍鹰散文 + 3 出口
/about                   10 只鸟介绍(未 v7 化)
```

**顶部横条 TopBanner**:
- 左: 圆+半环 line-art mark + Fraunces "啄木鸟 编辑部" + italic "Pecker · 2026 春"
- 右: "你好,XX · 今日 N 份 · 关于 · 登出" · 对话式 · 小号圆点分隔

---

## 5. 5 个 Phase 的数据契约(不能改的功能)

### Phase 0 上传
- 输入: reviewer · workspace · prdName · prdContent · mode(quick|standard) · userNotes
- 交互: dropzone + 粘贴 textarea fallback · workspace Select + 手输 fallback · mode 双卡(简审/精审) · 备注 textarea · 草稿恢复 banner(有未完成评审时)
- 下一步: `POST /api/drafts/{reviewer}` 存 draft phase=1 → `setPhase(1)`

### Phase 1 预检(自动态,无交互)
- 自动 `POST /api/review/precheck` · 返回 strong/weak/gaps/wiki_pages
- UI 三列结果展示 + 可补充说明
- 800ms 后自动 `setPhase(2)`

### Phase 2 评审中(SSE 流式 · 最复杂)
- 自动 `POST /api/review/run`(SSE) · 订阅事件流
- 视觉:
  - 横枝 SVG 进度:4 只 worker 鸟 + 1 只苍鹰分别立位,running 时鸟周围脉冲圈
  - 4 工作卡 grid:每张有 bird portrait + 职能 + 状态 dot + 叙事文案("翻到第三本 wiki。有两处字段名对不上…")
  - 苍鹰独立 dashed 一行: "等四只鸟各自交稿 · 还要 2-3 分钟"
- 失败态:配额耗尽 / 全员失败 / 降级 / 取消 —— 各有不同提示
- 完成后 600ms 自动 `setPhase(3)`

### Phase 3 逐条确认
- reviewResult.items 按 dimension(structure/quality/ai_coding/data_quality)分 Tabs
- 每条 item:
  - meta: ID · severity(高/中/低) · provenance(worker/meta_added/meta_dedup_kept/共识 N) · location · confidence · gate_log
  - 问题 · 依据(evidence,灰色 italic)· 建议(suggestion)
  - 三按钮 accept / edit / reject · edit 展开 textarea 改写 · reject 展开 textarea 写原因
- 底部 stats + "生成报告" `POST /api/review/confirm`

### Phase 4 报告出口
- 封面 paper:meta + 大标题 + 散文 intro + 啄伤度横条(0-10 分)
- 按 dim 分组章节摘要:每条带左彩条(accept 红 / edit moss / reject 灰)
- 苍鹰终审散文块(mode=standard 且 goshawk_summary 有数据)· 误报 / 补报 / 冲突三个小统计
- 运行指标 + 成本归因(telemetry · cost_breakdown · 可选)
- 预览折叠(完整 markdown)
- colophon: 署名 + 3 出口按钮(下载 .md · 保存 wiki · 推飞书)
- 返回确认 / 评审下一个

---

## 6. 目前已落地 v7 的页面(可以对照看)

| 页面 | 文件 | 状态 |
|---|---|---|
| TopBanner | `web/components/TopBanner.tsx` | ✅ 已 v7 |
| 登录 | `web/app/login/LoginForm.tsx` | ✅ 已 v7(柴门 scene) |
| Phase 0 | `web/components/phases/Phase0Upload.tsx` | ✅ 已 v7(树 scene) |
| Phase 1 | `web/components/phases/Phase1Precheck.tsx` | ✅ 已 v7 |
| Phase 2 | `web/components/phases/Phase2Running.tsx` | ✅ 已 v7(横枝 + 工作卡) |
| Phase 3 | `web/components/phases/Phase3Confirm.tsx` | ✅ 已 v7 |
| Phase 4 | `web/components/phases/Phase4Report.tsx` | ✅ 已 v7(报告封面) |
| 共享原子 | `web/components/phases/primitives.tsx` | ✅ PaperCard/NumberedField/CtaArrow/PaperHead/Signature/SubmitRow/Foot |
| 共享头部 | `web/components/phases/PhaseHead.tsx` | ✅ eyebrow + serif 标题 + lead |

---

## 7. 还没解决 · 可以交给 Claude Design 的设计问题

按优先级排序:

### A. 【高】首页 `ForestLanding.tsx` 需要 v7 化
- 目前还是 v1 emerald 童话森林风(matrix 数字雨 + 绿底),和其他页面完全不搭
- 文件: `web/app/ForestLanding.tsx`
- 目标: 给 v7 线稿语言做一张 landing —— 可以参考森林 / 树林 / 树洞作为核心视觉,但必须是 ink stroke line-art 而非 emoji / matrix
- 三个入口: 进入编辑部 · 关于家族 · 直接去评审
- 用户价值: 第一印象就传达"这是编辑部,不是 SaaS 控制台"

### B. 【高】PhaseStepper 顶部 5 阶段条需要 v7 化
- 目前还是 shadcn 圆角 + 色块底 · 和 v7 的轻线稿感冲突
- 文件: `web/components/PhaseStepper.tsx`
- 目标: 做成轻量的横线进度 · 可能类似"杂志目录页"的章节列表 · 或者干脆换成页眉小字 "Phase 02 / 05"
- 约束: 不能跳转交互,只展示(每 phase 自己的"下一步"按钮控制前进)

### C. 【中】`/about` 页十鸟家族介绍
- 目前是 shadcn 卡片堆 · 需要重做
- 参考 v7 盆栽感:一棵树,10 只鸟按"可见 / 后台"散布在枝上,hover 展开人设
- 文件: `web/app/about/page.tsx`

### D. 【中】移动端适配(375 / 768)
- v7 HTML 线稿目前只做了桌面端 1024+
- Phase 2 的 4 工作卡在小屏应该怎么堆?横枝是否要变垂直 timeline?
- 登录柴门 scene 在小屏是隐藏还是压缩?
- Phase 3 Tabs 在小屏是横滚还是 Sheet?

### E. 【低】暗色模式
- 全套 v7 目前只在浅色(sage base)走过 · 没做暗色
- 如果做,建议方向: 深墨青底 + 纸黄色文字 + 暖灯点缀(类似夜里的编辑部)

### F. 【低】微动效细节
- Phase 2 的"啄击震颤"`animate-pecker-peck` 目前在 v4 时代定义过,v7 还没决定要不要用(v7 偏克制)
- 红笔勾的 stroke-dash 动画(`pecker-correct`)在哪些 hover 可以出现
- 啄伤度横条的指针是否要滑动进入

### G. 【低】更多插图资产
- 目前只有 10 只鸟线稿 + 2 个场景(树/柴门)
- 潜在需要: 空态(收件箱无稿子)· error 页 · 404 · 撤稿时的"飞走的鸟"等

---

## 8. 附件清单(请把下面这些一并给 Claude Design)

### 必读 4 份
1. `.superpowers/brainstorm/1109-1776413100/content/login-v7.html` —— 登录柴门线稿
2. `.superpowers/brainstorm/1109-1776413100/content/phase0-v7.html` —— Phase 0 投稿表单线稿
3. `.superpowers/brainstorm/1109-1776413100/content/phase2-v7.html` —— Phase 2 横枝进度 + 工作卡线稿
4. `.superpowers/brainstorm/1109-1776413100/content/phase4-v7.html` —— Phase 4 报告封面线稿

### 设计规范
5. `design-system/啄木鸟-pecker/MASTER.md` —— 完整 v7 + 历代 token 备忘

### 参考代码(看现状和插画资产)
6. `web/app/globals.css` —— 全套 CSS 变量和 v7 utility(看 `/* ============ v7 线稿风 utilities ============ */` 段落)
7. `web/components/birds/BirdArt-v2.tsx` —— 10 只鸟的 SVG 线稿(可以原样复用到新设计)
8. `web/lib/roles.ts` —— 10 只鸟的人设详细描述 + 识别色

### 当前实现(看"我现在在哪")
9. `web/components/TopBanner.tsx`
10. `web/app/login/LoginForm.tsx`
11. `web/components/phases/PhaseHead.tsx` + `primitives.tsx`
12. `web/components/phases/Phase0Upload.tsx`
13. `web/components/phases/Phase2Running.tsx`
14. `web/components/phases/Phase4Report.tsx`

---

## 9. 给设计师的一句提醒

产品叫啄木鸟,不叫 ChatGPT Enterprise。
每一处让用户多停一秒 / 多微笑一下的决定,都比"再加一个 feature"更值得。
树洞里备了茶 —— 这是产品在对用户说的话。
