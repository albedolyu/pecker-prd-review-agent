/**
 * BirdAvatar · v8 头像组件
 *
 * 从"刊物署名插画"→"工作 Agent 成员"。三元组:身份(头像)+ 职能徽章 + 状态灯。
 *
 * - 3 尺寸:lg(32) / md(24) / sm(16)
 * - 10 只全集(id 1-10),内部复用 BirdArt-v2 现成线稿 SVG
 * - lg 尺寸 + 1-10 鸟 → hand-drawn PNG 大头像(放在 /public/birds/)
 *   PNG 加载失败时 onError 自动回退到原 SVG 线稿,无缝降级
 * - 四态状态灯(+warn):queued / running / done / failed / warn
 *   running 态用 dot-breathe 呼吸动画(1.4s infinite)
 * - 外层 pill 背景色用 --bird-{id} 的 color-mix,和徽章同源
 * - placeholder 模式可显式降级为虚线圆占位
 *
 * 规范源:design-system/Pecker-pecker-v8/components/bird-avatar.jsx
 */

"use client";

import { useState } from "react";
import {
  WoodpeckerArtV2,
  WeaverArtV2,
  OwlArtV2,
  RavenArtV2,
  CormorantArtV2,
  GoshawkArtV2,
  DoveArtV2,
  CuckooArtV2,
  KakapoArtV2,
  ShrikeArtV2,
} from "./BirdArt-v2";

export type BirdId = 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10;
export type BirdSize = "lg" | "md" | "sm";
export type BirdStatus = "queued" | "running" | "done" | "failed" | "warn";

const BIRD_SIZES: Record<BirdSize, number> = { lg: 32, md: 24, sm: 16 };

// v8 birdId → BirdArt-v2 SVG。
// 注:lg 尺寸默认切到 hand-drawn PNG 大头像(见 LG_PORTRAIT),BIRD_SVG 仅
// 用于 sm/md 尺寸 + placeholder / 图片加载失败兜底。
const BIRD_SVG: Record<
  BirdId,
  React.FC<{ size?: number; className?: string }>
> = {
  1: WeaverArtV2, // 业务(结构责编)
  2: CormorantArtV2, // 数据
  3: OwlArtV2, // 体验(审校)
  4: RavenArtV2, // 风险(技编)
  5: GoshawkArtV2, // 苍鹰交叉校验
  6: WoodpeckerArtV2, // 主编
  7: DoveArtV2,
  8: CuckooArtV2,
  9: KakapoArtV2,
  10: ShrikeArtV2,
};

// lg 尺寸 hand-drawn PNG 路径 · 1-10 全量上线
// 文件需存在于 /public/birds/ 下,详见 public/birds/README.md
const LG_PORTRAIT: Record<BirdId, string> = {
  1: "/birds/biz-lg.png",
  2: "/birds/data-lg.png",
  3: "/birds/ux-lg.png",
  4: "/birds/risk-lg.png",
  5: "/birds/goshawk-lg.png",
  6: "/birds/woodpecker-lg.png",
  7: "/birds/dove-lg.png",
  8: "/birds/cuckoo-lg.png",
  9: "/birds/kakapo-lg.png",
  10: "/birds/shrike-lg.png",
};

const BIRD_ALT_TEXT: Record<BirdId, string> = {
  1: "业务鸟",
  2: "数据鸟",
  3: "体验鸟",
  4: "风险鸟",
  5: "苍鹰",
  6: "主编",
  7: "读者反馈员",
  8: "试读员",
  9: "资料员",
  10: "质检员",
};

interface BirdAvatarProps {
  id: BirdId;
  size?: BirdSize;
  status?: BirdStatus;
  placeholder?: boolean;
  className?: string;
  style?: React.CSSProperties;
}

export function BirdAvatar({
  id,
  size = "md",
  status,
  placeholder = false,
  className,
  style,
}: BirdAvatarProps) {
  const px = BIRD_SIZES[size];
  const color = `var(--bird-${id})`;
  const dotSize = size === "sm" ? 6 : size === "md" ? 8 : 10;
  const Art = BIRD_SVG[id];

  // lg 尺寸 + 非 placeholder 模式 → 用 hand-drawn PNG 大头像
  // img onError 时 setPortraitFailed → 自动回退到原 SVG 线稿(无缝降级)
  const eligibleForPortrait =
    size === "lg" && !placeholder && id >= 1 && id <= 10;
  const [portraitFailed, setPortraitFailed] = useState(false);
  const useHandDrawnPortrait = eligibleForPortrait && !portraitFailed;

  return (
    <span
      className={className}
      style={{
        position: "relative",
        display: "inline-flex",
        width: px,
        height: px,
        flexShrink: 0,
        ...style,
      }}
    >
      {useHandDrawnPortrait ? (
        <img
          src={LG_PORTRAIT[id]}
          alt={BIRD_ALT_TEXT[id]}
          width={px}
          height={px}
          onError={() => setPortraitFailed(true)}
          style={{
            width: "100%",
            height: "100%",
            borderRadius: "50%",
            objectFit: "cover",
            display: "block",
          }}
        />
      ) : (
        <span
          style={{
            width: "100%",
            height: "100%",
            borderRadius: "var(--r-pill)",
            background: `color-mix(in oklch, ${color} 10%, var(--surface-raised))`,
            border: `1px solid color-mix(in oklch, ${color} 28%, var(--border-default))`,
            color,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            overflow: "hidden",
            opacity: placeholder ? 0.5 : 1,
            transition: "border-color var(--dur-base) var(--ease-out)",
          }}
        >
          {placeholder ? (
            <svg viewBox="0 0 36 36" style={{ width: "100%", height: "100%" }}>
              <circle
                cx="18"
                cy="18"
                r="10"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.2"
                strokeDasharray="2 2"
              />
            </svg>
          ) : (
            <Art size={px - 4} />
          )}
        </span>
      )}
      {status && <StatusDot status={status} size={dotSize} />}
    </span>
  );
}

// ============================================================
// BirdLabel · sm/md 场景的"色点 + 文字"标签
//
// 用在 tab nav / 评论卡顶行 / 列表项等位置 — PM 工作台审美里这些地方
// 不需要肖像感,文字 + 一个 6-8px 色点已经够识别。
// 大头像(/about 角色卡 / Phase 2 worker 卡 / hover tooltip)继续用 BirdAvatar size="lg"。

const BIRD_LABEL_TEXT: Record<BirdId, string> = {
  1: "业务鸟",
  2: "数据鸟",
  3: "体验鸟",
  4: "风险鸟",
  5: "苍鹰",
  6: "主编",
  7: "反馈",
  8: "试读",
  9: "资料",
  10: "质检",
};

interface BirdLabelProps {
  id: BirdId;
  /** sm = 12px / md = 13px。lg 别用,lg 走 BirdAvatar 大头像。 */
  size?: "sm" | "md";
  className?: string;
  style?: React.CSSProperties;
}

export function BirdLabel({
  id,
  size = "sm",
  className,
  style,
}: BirdLabelProps) {
  const fontSize = size === "sm" ? 12 : 13;
  const dotSize = size === "sm" ? 6 : 8;
  const fontWeight = size === "sm" ? 500 : 600;

  return (
    <span
      className={className}
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 6,
        fontFamily: "var(--font-sans)",
        ...style,
      }}
    >
      <span
        aria-hidden
        style={{
          width: dotSize,
          height: dotSize,
          borderRadius: "50%",
          background: `var(--bird-${id})`,
          flexShrink: 0,
        }}
      />
      <span
        style={{
          fontSize,
          fontWeight,
          color: "var(--text-strong)",
        }}
      >
        {BIRD_LABEL_TEXT[id]}
      </span>
    </span>
  );
}

interface StatusDotProps {
  status: BirdStatus;
  size?: number;
  /** 独立使用时关闭 absolute 定位(默认叠在头像右下角) */
  inline?: boolean;
}

/** 状态灯 · 四态(+warn) · running 用呼吸动画 */
export function StatusDot({
  status,
  size = 8,
  inline = false,
}: StatusDotProps) {
  const tokens: Record<BirdStatus, { bg: string; anim: string }> = {
    queued: { bg: "var(--status-queued-dot)", anim: "none" },
    running: {
      bg: "var(--status-running-dot)",
      anim: "dot-breathe 1.4s var(--ease-out) infinite",
    },
    done: { bg: "var(--status-done-dot)", anim: "none" },
    failed: { bg: "var(--status-failed-dot)", anim: "none" },
    warn: { bg: "var(--status-warn-dot)", anim: "none" },
  };
  const tok = tokens[status];

  return (
    <span
      aria-label={status}
      style={{
        ...(inline
          ? { display: "inline-block" }
          : {
              position: "absolute",
              right: -2,
              bottom: -2,
              display: "inline-block",
            }),
        width: size,
        height: size,
        borderRadius: "50%",
        background: tok.bg,
        animation: tok.anim,
        boxShadow: inline ? "none" : "0 0 0 2px var(--surface-raised)",
      }}
    />
  );
}
