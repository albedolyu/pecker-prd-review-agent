/**
 * BirdAvatar · v8 头像组件
 *
 * 从"刊物署名插画"→"工作 Agent 成员"。三元组:身份(头像)+ 职能徽章 + 状态灯。
 *
 * - 3 尺寸:lg(32) / md(24) / sm(16)
 * - 10 只全集(id 1-10),内部复用 BirdArt-v2 现成线稿 SVG
 * - 四态状态灯(+warn):queued / running / done / failed / warn
 *   running 态用 dot-breathe 呼吸动画(1.4s infinite)
 * - 外层 pill 背景色用 --bird-{id} 的 color-mix,和徽章同源
 * - placeholder 模式:id 6-10 未上线鸟可用虚线圆占位
 *
 * 规范源:design-system/啄木鸟-pecker-v8/components/bird-avatar.jsx
 */

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

// v8 birdId → BirdArt-v2 SVG · 1-5 已上线(业务/数据/体验/风险/苍鹰),6-10 占位
const BIRD_SVG: Record<
  BirdId,
  React.FC<{ size?: number; className?: string }>
> = {
  1: WeaverArtV2, // 业务(结构责编)
  2: CormorantArtV2, // 数据
  3: OwlArtV2, // 体验(审校)
  4: RavenArtV2, // 风险(技编)
  5: GoshawkArtV2, // 苍鹰 meta
  6: WoodpeckerArtV2, // 占位
  7: DoveArtV2,
  8: CuckooArtV2,
  9: KakapoArtV2,
  10: ShrikeArtV2,
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
      {status && <StatusDot status={status} size={dotSize} />}
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
