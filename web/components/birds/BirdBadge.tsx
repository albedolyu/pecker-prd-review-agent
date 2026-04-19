/**
 * BirdBadge · v8 职能徽章
 *
 * pill 形状,<dot>+职能名的紧凑标签。
 * - 色源和 BirdAvatar 同:--bird-{id}
 * - 2 尺寸:md(12px 字号 · 默认) / sm(11px · 紧凑)
 * - meta 类型(id=5 苍鹰)额外带 "meta" 小字标识层级
 * - placeholder 类型(id 6-10)显示为占位标签,视觉弱化
 *
 * 规范源:design-system/啄木鸟-pecker-v8/components/bird-badge.jsx
 */

import type { BirdId } from "./BirdAvatar";

export type BirdType = "worker" | "meta" | "placeholder";

interface BirdMeta {
  code: string;
  label: string;
  type: BirdType;
}

/** birdId → 职能元数据(code / 中文 label / 层级类型) */
export const BIRD_META: Readonly<Record<BirdId, BirdMeta>> = Object.freeze({
  1: { code: "biz", label: "业务", type: "worker" },
  2: { code: "data", label: "数据", type: "worker" },
  3: { code: "ux", label: "体验", type: "worker" },
  4: { code: "risk", label: "风险", type: "worker" },
  5: { code: "eagle", label: "苍鹰", type: "meta" },
  6: { code: "bird-06", label: "bird-06", type: "placeholder" },
  7: { code: "bird-07", label: "bird-07", type: "placeholder" },
  8: { code: "bird-08", label: "bird-08", type: "placeholder" },
  9: { code: "bird-09", label: "bird-09", type: "placeholder" },
  10: { code: "bird-10", label: "bird-10", type: "placeholder" },
});

interface BirdBadgeProps {
  id: BirdId;
  size?: "md" | "sm";
  /** 覆盖默认 label(默认用 BIRD_META[id].label + "鸟") */
  label?: string;
  className?: string;
  style?: React.CSSProperties;
}

export function BirdBadge({
  id,
  size = "md",
  label,
  className,
  style,
}: BirdBadgeProps) {
  const meta = BIRD_META[id];
  const color = `var(--bird-${id})`;
  const compact = size === "sm";
  const displayLabel = label ?? `${meta.label}鸟`;

  return (
    <span
      className={className}
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: compact ? 4 : 6,
        padding: compact ? "2px 8px" : "3px 10px",
        borderRadius: "var(--r-pill)",
        background: `color-mix(in oklch, ${color} 12%, var(--surface-sunken))`,
        border: `1px solid color-mix(in oklch, ${color} 22%, var(--border-subtle))`,
        color: `color-mix(in oklch, ${color} 75%, var(--text-strong))`,
        fontSize: compact ? 11 : 12,
        fontWeight: 500,
        lineHeight: 1,
        whiteSpace: "nowrap",
        fontVariantNumeric: "tabular-nums",
        opacity: meta.type === "placeholder" ? 0.6 : 1,
        ...style,
      }}
    >
      <span
        style={{
          width: compact ? 5 : 6,
          height: compact ? 5 : 6,
          borderRadius: "50%",
          background: color,
          flexShrink: 0,
        }}
      />
      {displayLabel}
      {meta.type === "meta" && (
        <span
          style={{
            fontSize: 10,
            fontFamily: "var(--font-mono)",
            opacity: 0.7,
            marginLeft: 2,
          }}
        >
          meta
        </span>
      )}
    </span>
  );
}
