/**
 * DocumentView · v8 PRD 原文渲染
 *
 * Phase 1(带 strong/weak/gap 高亮)和 Phase 3(带评论锚点)复用。
 *
 * - 行号左栏(mono)+ 主文区
 * - 顶部汇总条:已覆盖 / 薄弱 / 盲区 计数(Phase 1 专用)
 * - inline 高亮 3 色:strong(绿)· weak(黄)· gap(红)
 * - anchored(选中):accent 色背景 + 底条,用于锚点联动
 * - 点高亮触发 onAnchorClick(可选),实现原文 ↔ 评论双向跳转
 *
 * 规范源:design-system/Pecker-pecker-v8/components/document-view.jsx
 */

"use client";

import type { CSSProperties, ReactNode } from "react";

export type BlockType = "h" | "h2" | "p" | "li";
export type HighlightKind = "strong" | "weak" | "gap";

export interface BlockHighlight {
  kind: HighlightKind;
  /** 在 block.content 字符串里的起始位置 */
  start: number;
  /** 结束位置(exclusive) */
  end: number;
  /** 锚点 ID,点击时回调,也用于 selectedAnchor 匹配 */
  anchor?: string;
}

export interface DocBlock {
  type: BlockType;
  content: string;
  /** block id(给锚点 / 滚动定位用) */
  id?: string;
  highlights?: BlockHighlight[];
}

export interface DocSummary {
  strong: number;
  weak: number;
  gaps: number;
}

interface DocumentViewProps {
  title?: string;
  /** 副标题:版本号 / 元数据 (mono 字体) */
  subtitle?: string;
  /** 顶部汇总条(Phase 1 用,Phase 3 通常不传) */
  summary?: DocSummary;
  blocks: DocBlock[];
  /** 当前选中的锚点 ID,匹配的高亮块会强化显示 */
  selectedAnchor?: string;
  onAnchorClick?: (anchor: string) => void;
  className?: string;
  style?: CSSProperties;
}

export function DocumentView({
  title = "PRD",
  subtitle,
  summary,
  blocks,
  selectedAnchor,
  onAnchorClick,
  className,
  style,
}: DocumentViewProps) {
  return (
    <div
      className={className}
      style={{
        background: "var(--surface-raised)",
        border: "1px solid var(--border-default)",
        borderRadius: "var(--r-4)",
        overflow: "hidden",
        display: "flex",
        flexDirection: "column",
        ...style,
      }}
    >
      {/* ── header ── */}
      <div
        style={{
          padding: "14px 20px",
          borderBottom: "1px solid var(--border-default)",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 12,
        }}
      >
        <div style={{ minWidth: 0, flex: 1 }}>
          <div
            style={{
              fontSize: 14,
              fontWeight: 600,
              color: "var(--text-strong)",
            }}
          >
            {title}
          </div>
          {subtitle && (
            <div
              style={{
                fontSize: 11,
                color: "var(--text-muted)",
                marginTop: 2,
                fontFamily: "var(--font-mono)",
              }}
            >
              {subtitle}
            </div>
          )}
        </div>
        {summary && (
          <div style={{ display: "flex", gap: 6 }}>
            <SummaryChip kind="strong" n={summary.strong} />
            <SummaryChip kind="weak" n={summary.weak} />
            <SummaryChip kind="gap" n={summary.gaps} />
          </div>
        )}
      </div>

      {/* ── body ── */}
      <div
        style={{
          flex: 1,
          overflow: "auto",
          padding: "14px 0",
          fontSize: 14,
          lineHeight: 1.7,
          color: "var(--text-default)",
        }}
      >
        {blocks.map((b, i) => (
          <DocBlockRow
            key={b.id ?? i}
            line={i + 1}
            block={b}
            selectedAnchor={selectedAnchor}
            onAnchorClick={onAnchorClick}
          />
        ))}
      </div>
    </div>
  );
}

// ============================================================

interface SummaryChipProps {
  kind: HighlightKind;
  n: number;
}

function SummaryChip({ kind, n }: SummaryChipProps) {
  const map = {
    strong: {
      fg: "var(--status-done-fg)",
      bg: "var(--status-done-bg)",
      label: "已覆盖",
    },
    weak: {
      fg: "var(--status-warn-fg)",
      bg: "var(--status-warn-bg)",
      label: "薄弱",
    },
    gap: {
      fg: "var(--status-failed-fg)",
      bg: "var(--status-failed-bg)",
      label: "盲区",
    },
  }[kind];

  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 5,
        padding: "3px 9px",
        borderRadius: "var(--r-pill)",
        background: map.bg,
        color: map.fg,
        fontSize: 11,
        fontWeight: 600,
      }}
    >
      <span
        style={{
          fontFamily: "var(--font-mono)",
          fontVariantNumeric: "tabular-nums",
        }}
      >
        {n}
      </span>
      {map.label}
    </span>
  );
}

interface DocBlockRowProps {
  line: number;
  block: DocBlock;
  selectedAnchor?: string;
  onAnchorClick?: (anchor: string) => void;
}

function DocBlockRow({
  line,
  block,
  selectedAnchor,
  onAnchorClick,
}: DocBlockRowProps) {
  const Tag =
    block.type === "h" ? "h3" : block.type === "h2" ? "h4" : "p";
  const BLOCK_STYLES: Record<BlockType, CSSProperties> = {
    h: {
      fontSize: 17,
      fontWeight: 600,
      color: "var(--text-strong)",
      margin: "14px 0 6px",
    },
    h2: {
      fontSize: 14,
      fontWeight: 600,
      color: "var(--text-strong)",
      margin: "10px 0 4px",
    },
    p: { margin: "4px 0" },
    li: { margin: "2px 0", paddingLeft: 18, position: "relative" },
  };
  const tagStyle = BLOCK_STYLES[block.type];

  const content = renderHighlights(
    block.content,
    block.highlights ?? [],
    selectedAnchor,
    onAnchorClick,
  );

  return (
    <div
      id={block.id}
      style={{
        display: "grid",
        gridTemplateColumns: "48px 1fr",
        gap: 16,
        padding: "0 20px",
      }}
    >
      <span
        style={{
          fontFamily: "var(--font-mono)",
          fontSize: 10,
          color: "var(--text-faint)",
          textAlign: "right",
          paddingTop: 6,
          userSelect: "none",
        }}
      >
        {line}
      </span>
      <Tag style={tagStyle}>
        {block.type === "li" && (
          <span
            style={{
              position: "absolute",
              left: 0,
              color: "var(--text-muted)",
            }}
          >
            ·
          </span>
        )}
        {content}
      </Tag>
    </div>
  );
}

function renderHighlights(
  text: string,
  highlights: BlockHighlight[],
  selectedAnchor: string | undefined,
  onAnchorClick: ((anchor: string) => void) | undefined,
): ReactNode {
  if (!highlights.length) return text;

  const sorted = [...highlights].sort((a, b) => a.start - b.start);
  const out: ReactNode[] = [];
  let cursor = 0;

  sorted.forEach((h, i) => {
    if (h.start > cursor) out.push(text.slice(cursor, h.start));
    const inner = text.slice(h.start, h.end);
    const isSelected = Boolean(
      selectedAnchor && h.anchor === selectedAnchor,
    );
    out.push(
      <HighlightMark
        key={i}
        kind={h.kind}
        anchor={h.anchor}
        selected={isSelected}
        onClick={() => h.anchor && onAnchorClick?.(h.anchor)}
      >
        {inner}
      </HighlightMark>,
    );
    cursor = h.end;
  });

  if (cursor < text.length) out.push(text.slice(cursor));
  return out;
}

interface HighlightMarkProps {
  kind: HighlightKind;
  anchor?: string;
  selected: boolean;
  onClick: () => void;
  children: ReactNode;
}

function HighlightMark({
  kind,
  anchor,
  selected,
  onClick,
  children,
}: HighlightMarkProps) {
  const map = {
    strong: {
      bg: "color-mix(in oklch, var(--status-done-dot) 18%, transparent)",
      u: "var(--status-done-dot)",
    },
    weak: {
      bg: "color-mix(in oklch, var(--status-warn-dot) 18%, transparent)",
      u: "var(--status-warn-dot)",
    },
    gap: {
      bg: "color-mix(in oklch, var(--status-failed-dot) 18%, transparent)",
      u: "var(--status-failed-dot)",
    },
  }[kind];

  return (
    <mark
      onClick={onClick}
      style={{
        background: selected
          ? "color-mix(in oklch, var(--accent-500) 28%, transparent)"
          : map.bg,
        borderBottom: `2px solid ${selected ? "var(--accent-500)" : map.u}`,
        padding: "0 1px",
        cursor: anchor ? "pointer" : "default",
        color: "inherit",
        transition: "background var(--dur-fast) var(--ease-out)",
      }}
    >
      {children}
    </mark>
  );
}
