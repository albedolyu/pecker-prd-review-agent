# 啄木鸟 Pecker · Design System Master (v7 · ARCHIVED)

> **⚠ 已归档 · 2026-04-18**
> v7 方向("线稿·sage 绿·编辑部散文"气质)已被 v8 "Agent 工作台 + 工作文档"气质 **完整替代**。
> v7 的实际代码 token 保留在 `web/app/globals.css` 的 `@deprecated-v7` 段,只为让少数未迁移页面(如 ForestLanding / about)不崩,新组件严禁引用。
>
> **当前版本请看** `design-system/啄木鸟-pecker-v8/MASTER.md`。
>
> 本文件保留作为历史参考,不再维护。

---

# 啄木鸟 Pecker · Design System Master (v7 原文)

> 当做具体页面时,优先读 `design-system/啄木鸟-pecker-v7.archived/pages/[page].md`。
> 页面文件不存在则完全按本文件执行。

**Project:** 啄木鸟 Pecker
**Direction:** Hand-Crafted Editorial · 宫崎骏式手作美感 · 内部工具但追求极致
**Generated:** 2026-04-17 (v2, overrides UI-UX-Pro-Max skill Flat Design default) · **Archived: 2026-04-18**

> 本 MASTER 在 skill 推荐的 "Notes & Writing · Flat Design" 基础上调整:
> - 保留色板家族 (warm stone + amber on cream) 但扩展到吉卜力自然色阶
> - 保留可访问性 / 间距 / 响应式标准
> - **覆写** Flat Design → Hand-Crafted Editorial,启用手作细节 (旋转 / 偏移阴影 / 水彩晕染)

---

## 色彩 · Color

### 主色板(v3 调整: 浅绿主调 · sage dominant)

| Role | Hex | CSS Variable |
|------|-----|--------------|
| **Sage Base (主背景, default)** | `#eef2e5` | `--color-background` |
| **Sage Light (卡片底/柔背景)** | `#dbe4cf` | `--color-sage-light` |
| **Sage (中绿/水彩雾主)** | `#b8ccb0` | `--color-sage` |
| **Sage Mid (强调绿)** | `#a8bfa0` | `--color-sage-mid` |
| Primary (深墨橄榄) | `#3a4238` | `--color-primary` |
| Primary Ink (纯墨) | `#1a1e18` | `--color-primary-ink` |
| Accent (琥珀 CTA) | `#d4a05e` | `--color-accent` |
| Accent Deep (蜡封朱) | `#b85c4a` | `--color-accent-deep` |
| Rose Dust (柔绯 / done 态) | `#c98e7f` | `--color-rose` |
| Moss (深苔 / running 态) | `#8ba888` | `--color-moss` |
| Moss Deep (深绿 / 描边) | `#5d7357` | `--color-moss-deep` |
| Wood (木质) | `#a67c52` | `--color-wood` |
| Wood Deep (深木) | `#6b4e32` | `--color-wood-deep` |
| Cream (奶黄, 保留但减用) | `#ede4cc` | `--color-cream` |
| Cream Light (纸白, 少量用于纸质感) | `#f7f1dd` | `--color-cream-light` |
| Ink (文字主) | `#3a4238` | `--color-foreground` |
| Ink Soft (次要) | `#5c6158` | `--color-foreground-soft` |
| Ink Mute (meta) | `#8a8a80` | `--color-foreground-mute` |
| Destructive (校稿红) | `#b85c4a` | `--color-destructive` |

**Notes:** 主背景走 sage-light(`#eef2e5`)——浅绿雾里带一点暖,不饱和不冷。
暖色 (cream / wood / amber) 减用到点缀比例(< 15% 屏幕面积)。
水彩雾主色是 sage(`#b8ccb0` 0.4 alpha) + 少量 amber(0.12 alpha)。
红色仅作"校稿痕迹"/CTA,不作全局警告色。error 态用 dusty rose `#c98e7f` 背景。

### 状态语义色(去糖果化)

| State | Color | Usage |
|-------|-------|-------|
| Running | `--color-moss` | 生机 / 进行中 |
| Done | `--color-rose` | 完成 / 收尾 |
| Idle | `--color-wood` (opacity .6) | 待命 |
| Error | `--color-accent-deep` (背景 10%) | 出错但温柔 |

## 字体 · Typography

### 方向定调: Fraunces + Nunito + Caveat 三栈

```css
@import url('https://fonts.googleapis.com/css2?family=Fraunces:opsz,ital,wght@9..144,0,300;9..144,0,400;9..144,0,500;9..144,1,300;9..144,1,400&family=Nunito:wght@300;400;500;600;700&family=Noto+Serif+SC:wght@300;400;500&family=Caveat:wght@400;500&display=swap');
```

| 用途 | 字体 | 备注 |
|------|------|------|
| Display / h1 / 重要标题 | **Fraunces** (serif, variable opsz) | 大字用 144 opsz 饱满,小字用 9 opsz 清晰 |
| Body (中英混排) | **Noto Serif SC** (light 300 / regular 400) | 中文默认 fallback,保持 serif 气质 |
| UI / Button / Label | **Nunito** (500-700) | 圆润 sans,不用 Inter 那种理性字 |
| 手写 caption / 签名 / 注释 | **Caveat** (500) | 只在"像手写"的位置用 |

**规则:** serif 大字要 `letter-spacing: -0.01em`,正文 `letter-spacing: 0.005em`。
italic 用于 subtitle / meta / 引用 — 杂志 caption 的节奏。
中文 fallback 按 `Noto Serif SC → PingFang SC → Microsoft YaHei`。

## 间距 · Spacing (带"手工栏位")

| Token | Value | Usage |
|-------|-------|-------|
| `--space-xs` | `4px` | 图标紧邻 |
| `--space-sm` | `8px` | inline gap |
| `--space-md` | `16px` | 通用 padding |
| `--space-lg` | `24px` | section padding |
| `--space-xl` | `32px` | 大段落 |
| `--space-2xl` | `48px` | section 间距 |
| `--space-3xl` | `64px` | hero |
| **`--space-hang`** | `11px` | 挂件错位(非 4 倍数) |
| **`--space-col`** | `22px` | 手工栏位(非 4 倍数) |
| **`--space-gutter`** | `42px` | 手工 gutter(非 4 倍数) |

**关键:** 部分元素故意用**非 4 倍数**打破 Tailwind 默认网格。这是手作感的来源。

## 阴影 · Shadows (Hand-Crafted Offset, 不是 blur 模糊)

```css
/* Hard offset(手作核心) */
--shadow-hard-sm:   2px 2px 0 -1px rgba(58,66,56,0.16);
--shadow-hard-md:   4px 4px 0 -1px rgba(58,66,56,0.18);
--shadow-hard-lg:   6px 6px 0 -2px rgba(58,66,56,0.20);

/* Soft(仅用于悬浮/模态,不作为默认阴影) */
--shadow-soft-sm:   0 1px 2px rgba(58,66,56,0.04), 0 4px 8px -4px rgba(58,66,56,0.08);
--shadow-soft-md:   0 2px 4px rgba(58,66,56,0.06), 0 12px 24px -8px rgba(58,66,56,0.12);
--shadow-soft-lg:   0 4px 8px rgba(58,66,56,0.08), 0 24px 48px -12px rgba(58,66,56,0.20);

/* Paper-drop(hard + soft 组合,像纸片贴在书上) */
--shadow-paper: 3px 3px 0 -1px rgba(58,66,56,0.12),
                0 2px 6px rgba(58,66,56,0.08);
```

**默认卡片用 `--shadow-paper`**。hover 升级到 `--shadow-soft-lg`。

## 形状 · Shape (Wobbly Corners)

```css
--radius-sm:     8px;
--radius-md:    12px;
--radius-lg:    18px;
--radius-xl:    24px;
--radius-pill:  999px;

/* Wobbly corners(关键手作细节) */
--radius-wobbly-a:  18px 22px 16px 20px;
--radius-wobbly-b:  20px 16px 22px 18px;
--radius-wobbly-c:  22px 18px 20px 16px;
```

**卡片应该用 `--radius-wobbly-*`,每次随机挑一个**。这让卡片像"手画的圆"。

## 旋转 · Rotation (Anti-Polish 手作感)

```css
.tilt-a { transform: rotate(-0.6deg); }
.tilt-b { transform: rotate(0.4deg); }
.tilt-c { transform: rotate(-0.3deg); }
.tilt-d { transform: rotate(0.8deg); }
```

**所有卡片应该 hover 平正,但 rest 态带 `.tilt-*` 之一微旋**。保留"手放上去"的痕迹。

## 动效 · Motion

**核心:** 用 sine wave / 弹性 spring,**不用机械 cubic-bezier**。

```css
/* 呼吸 */
--ease-breath:    cubic-bezier(0.37, 0, 0.63, 1);
/* 轻弹 */
--ease-gentle:    cubic-bezier(0.22, 1.36, 0.64, 1);
/* 标准 */
--duration-fast:  200ms;
--duration-med:   400ms;
--duration-slow:  600ms;

@keyframes pecker-sway {
  0%, 100% { transform: translateY(0) rotate(var(--rest-tilt, 0)); }
  50%      { transform: translateY(-3px) rotate(calc(var(--rest-tilt, 0) + 0.3deg)); }
}

@keyframes pecker-breathe-pulse {
  0%, 100% { opacity: 1; transform: scale(1); }
  50%      { opacity: 0.5; transform: scale(1.6); }
}

@media (prefers-reduced-motion: reduce) {
  * { animation: none !important; transition: opacity 150ms linear !important; }
}
```

## 底纹 · Background Layer

```css
/* 水彩晕染(替代单色背景) */
body {
  background:
    radial-gradient(ellipse 70% 50% at 15% 20%, rgba(181,201,175,0.35), transparent 65%),
    radial-gradient(ellipse 55% 45% at 88% 85%, rgba(214,160,94,0.20), transparent 65%),
    var(--color-cream-light);
}

/* 横线纸(用于 textarea / note 类元素) */
.paper-ruled {
  background:
    linear-gradient(rgba(253,249,236,.92), rgba(253,249,236,.92)),
    repeating-linear-gradient(0deg,
      transparent 0, transparent 26px,
      rgba(167,124,82,0.12) 26px, rgba(167,124,82,0.12) 27px);
}

/* 纸纤维(可选 overlay,5% opacity) */
.paper-fiber {
  background-image: url("data:image/svg+xml;utf8,<svg ...feTurbulence baseFrequency='0.65'/>");
  opacity: 0.05;
  mix-blend-mode: multiply;
}
```

## 组件规范 · Component Specs

### 卡片(默认)

```css
.card {
  background: var(--color-cream-light);
  border: 1px solid rgba(167,124,82,0.22);
  border-radius: var(--radius-wobbly-a);
  padding: var(--space-lg);
  box-shadow: var(--shadow-paper);
  transform: rotate(-0.4deg);                    /* ← 微旋 */
  transition: transform var(--duration-med) var(--ease-gentle),
              box-shadow var(--duration-med) var(--ease-gentle);
}
.card:hover {
  transform: rotate(0deg) translateY(-3px);      /* ← hover 平正+浮起 */
  box-shadow: var(--shadow-soft-lg);
}
```

### 按钮

```css
.btn-primary {
  background: linear-gradient(135deg, var(--color-accent-deep) 0%, #9a4a38 100%);
  color: #fdf5e8;
  font-family: 'Fraunces', 'Noto Serif SC', serif;
  font-weight: 500;
  padding: 14px 28px;
  border: none;
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-hard-md);             /* ← 硬阴影 */
  cursor: pointer;
  transition: all var(--duration-fast) var(--ease-gentle);
}
.btn-primary:hover {
  transform: translate(-1px, -1px);               /* ← 偏移让阴影"露出来" */
  box-shadow: 5px 5px 0 -1px rgba(58,66,56,0.22);
}
.btn-primary:active {
  transform: translate(2px, 2px);                 /* 按下去"盖住"阴影 */
  box-shadow: var(--shadow-hard-sm);
}
```

### 输入(下划线式)

```css
.input-underline {
  padding: 6px 2px 10px;
  border: none;
  border-bottom: 1.5px solid rgba(167,124,82,0.35);
  background: transparent;
  font-family: 'Fraunces', 'Noto Serif SC', serif;
  font-size: 19px;
  transition: border-color var(--duration-fast) ease;
}
.input-underline:focus {
  outline: none;
  border-bottom-color: var(--color-moss-deep);
}
```

## 不可出现 · Anti-Patterns

- ❌ **饱和果冻色 / 霓虹色** — 偏离吉卜力方向,让产品像 Duolingo
- ❌ **纯几何圆角(全一致 radius)** — 失去手作感,用 wobbly
- ❌ **blur 模糊阴影(单一)** — 只在 modal 用;卡片默认 hard offset
- ❌ **饱和红色满屏** — 红仅作 ink-mark / 校稿痕迹 / CTA 单点
- ❌ **机械 spring/bounce** — 动效应克制,偏向 sine 呼吸
- ❌ **纯色块无背景层次** — 必有水彩色雾或纸纤维底
- ❌ **emoji 当 icon** — 用定制 SVG
- ❌ **固定字号/行距** — 小字 15px 1.7 / 大字 40px+ 1.2

## 可访问性 · Accessibility

- 正文文本对比度 ≥ 4.5:1(WCAG AA)
- 所有交互元素 `cursor: pointer`
- Focus 状态必须可见: `outline: 2px solid var(--color-moss-deep); outline-offset: 2px`
- `prefers-reduced-motion` 时禁用 sway/breathe,只留 opacity transition
- 响应式断点: 375 / 768 / 1024 / 1440
- 所有图标 SVG 带 `aria-hidden` 或 `<title>`

## 环境叙事资产(鸟 IP 之外)

本产品区别于通用工具的关键:**环境叙事元素**。

| 元素 | 位置 | 用途 |
|------|------|------|
| 飘叶粒子 | 全页 fixed, 5 片错峰 | 空气感 |
| 水彩色雾 | body `::before / ::after` | 柔光背景 |
| 手写签名 | 投稿单 / 报告页底 | 人味 |
| 蜡封印章 | 主 CTA | 仪式感 |
| 树洞 / 萤火虫 | 登录 / Landing / Phase 0 scene | 童话氛围 |
| 别针钉 | 纸质卡片左上右上 | 物理感 |

## 外部插画资产

| 资产 | 来源 | 备注 |
|------|------|------|
| 10 只鸟插画 | Midjourney / Nano Banana / 插画师 | 不用 SVG 代码画,**从图像模型出** |
| icon 集 | Lucide(默认) + 6-8 个定制 SVG | 定制的部分要手绘感 |

## Pre-Delivery 检查表

- [ ] 卡片带 `.tilt-*` 微旋
- [ ] 卡片 border-radius 用 `--radius-wobbly-*` 之一
- [ ] 按钮用 hard offset shadow,非 blur
- [ ] 背景有水彩色雾
- [ ] 所有色符合 WCAG AA 对比度
- [ ] 动效带 `prefers-reduced-motion` 兜底
- [ ] Hover 平正(`rotate(0)`) + 上浮
- [ ] 飘叶粒子存在
- [ ] 中文 fallback 到 Noto Serif SC
- [ ] 响应式 375 / 768 / 1024 / 1440 验证
