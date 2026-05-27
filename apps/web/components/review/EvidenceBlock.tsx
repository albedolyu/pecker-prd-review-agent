/**
 * EvidenceBlock · v8 评论依据区
 *
 * 左侧 2px accent 条 + 引用原文段 + 3 态验证徽章。
 * 这是 harness 增量 P0-② 的视觉承载:让 PM 看见"依据是否经过验证"。
 *
 * 三态:
 * - verified ✓(绿)   · 已通过 Side Query 验证
 * - failed   ✗(红)   · 验证失败,评审项默认折叠
 * - unverified ⊖(灰) · 未验证,视觉弱化
 *
 * 规范源:design-system/Pecker-pecker-v8/components/evidence-block.jsx
 */

export type EvidenceVerification = "verified" | "failed" | "unverified";

export interface EvidenceData {
  /** 引用原文段(从 PRD 摘录) */
  quote: string;
  /** 来源标识(如 §2.3 / line 42) */
  source: string;
  /** 验证状态 */
  verification: EvidenceVerification;
}

interface EvidenceBlockProps extends EvidenceData {
  /** 紧凑模式(小一号) */
  compact?: boolean;
  className?: string;
  style?: React.CSSProperties;
}

export function EvidenceBlock({
  quote,
  source,
  verification = "unverified",
  compact = false,
  className,
  style,
}: EvidenceBlockProps) {
  const v = {
    verified: {
      icon: "✓",
      bg: "var(--status-done-bg)",
      fg: "var(--status-done-fg)",
      label: "已验证",
    },
    failed: {
      icon: "✗",
      bg: "var(--status-failed-bg)",
      fg: "var(--status-failed-fg)",
      label: "验证失败",
    },
    unverified: {
      icon: "⊖",
      bg: "var(--status-queued-bg)",
      fg: "var(--status-queued-fg)",
      label: "未验证",
    },
  }[verification];

  return (
    <div
      className={className}
      style={{
        borderLeft: "2px solid var(--accent-500)",
        background: "var(--surface-sunken)",
        padding: compact ? "8px 12px" : "10px 14px",
        borderRadius: "0 var(--r-3) var(--r-3) 0",
        display: "flex",
        flexDirection: "column",
        gap: 6,
        ...style,
      }}
    >
      <div
        style={{
          fontSize: compact ? 12 : 13,
          color: "var(--text-default)",
          lineHeight: 1.55,
          fontStyle: "normal",
        }}
      >
        {quote}
      </div>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 8,
        }}
      >
        <span
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: 10,
            color: "var(--text-muted)",
          }}
        >
          ↳ {source}
        </span>
        <span
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 5,
            padding: "2px 8px",
            borderRadius: "var(--r-pill)",
            background: v.bg,
            color: v.fg,
            fontSize: 10,
            fontWeight: 600,
          }}
        >
          <span style={{ fontSize: 11, lineHeight: 1 }}>{v.icon}</span>
          {v.label}
        </span>
      </div>
    </div>
  );
}
