"use client";

/**
 * RunDiff · v8 harness 增量 P1⑥
 *
 * 独立管理页组件:左右分栏 diff 两次 run。
 * 典型用法:baseline vs shadow(对齐 scripts/shadow_run.py 的产出),
 * 或 昨天 vs 今天(同一 PRD 重跑)。
 *
 * diff 维度:
 * - 评审条目差异(新增/缺失/conf 变化)
 * - session 分类差异
 * - consistency 分数差异
 * - token / 耗时差异
 *
 * 这是"UI 壳"版本,接 scripts/shadow_run.py 产出的接口在 Sprint 5。
 * 当前支持传入两个 RunSummary 对象做视觉 diff。
 */

import { useMemo } from "react";
import type { SessionClass } from "@/components/run/RunHealthCheck";
import type { BirdId } from "@/components/birds/BirdAvatar";
import { BIRD_META } from "@/components/birds/BirdBadge";
import { computeDiff, type DiffBuckets } from "@/lib/v8-run-helpers";

export interface RunItemSummary {
  id: string;
  problem: string;
  birdId: BirdId;
  confidence: number;
  severity?: string;
}

export interface RunSummary {
  /** run 标识(比如 "baseline 2026-04-17" / "shadow 2026-04-18") */
  label: string;
  /** 副标题(run_id / config) */
  subtitle?: string;
  /** session 分类 */
  sessionClass: SessionClass;
  consistency: number;
  totalTokens: number;
  costUsd: number;
  durationSec: number;
  items: RunItemSummary[];
}

interface RunDiffProps {
  left: RunSummary;
  right: RunSummary;
  className?: string;
  style?: React.CSSProperties;
}

export function RunDiff({ left, right, className, style }: RunDiffProps) {
  const buckets = useMemo<DiffBuckets>(
    () => computeDiff(left.items, right.items),
    [left.items, right.items],
  );

  return (
    <div
      className={className}
      style={{
        fontFamily: "var(--font-sans)",
        ...style,
      }}
    >
      {/* ── 顶部 summary 对比 ── */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "1fr 1fr",
          gap: 12,
          marginBottom: 16,
        }}
      >
        <RunHeaderCard side="left" run={left} />
        <RunHeaderCard side="right" run={right} />
      </div>

      {/* ── 指标对比条 ── */}
      <section
        style={{
          padding: "12px 16px",
          borderRadius: "var(--r-4)",
          border: "1px solid var(--border-default)",
          background: "var(--surface-raised)",
          marginBottom: 16,
        }}
      >
        <div
          style={{
            fontSize: 11,
            textTransform: "uppercase",
            letterSpacing: "0.08em",
            fontWeight: 600,
            color: "var(--text-muted)",
            marginBottom: 10,
          }}
        >
          指标对比
        </div>
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(4, 1fr)",
            gap: 14,
          }}
        >
          <MetricCompare
            label="一致率"
            leftValue={left.consistency}
            rightValue={right.consistency}
            format={(v) => `${(v * 100).toFixed(0)}%`}
            higherBetter
          />
          <MetricCompare
            label="意见数"
            leftValue={left.items.length}
            rightValue={right.items.length}
            format={(v) => String(v)}
          />
          <MetricCompare
            label="消耗"
            leftValue={left.totalTokens}
            rightValue={right.totalTokens}
            format={formatTokens}
            higherBetter={false}
          />
          <MetricCompare
            label="耗时"
            leftValue={left.durationSec}
            rightValue={right.durationSec}
            format={(v) => `${v.toFixed(1)}s`}
            higherBetter={false}
          />
        </div>
      </section>

      {/* ── items diff ── */}
      <section>
        <div
          style={{
            fontSize: 11,
            textTransform: "uppercase",
            letterSpacing: "0.08em",
            fontWeight: 600,
            color: "var(--text-muted)",
            marginBottom: 10,
          }}
        >
          评审意见变化
        </div>

        <DiffBucket
          title="原评审才有"
          count={buckets.onlyLeft.length}
          tone="left-only"
        >
          {buckets.onlyLeft.map((it) => (
            <ItemRow key={it.id} item={it} side="left" />
          ))}
        </DiffBucket>

        <DiffBucket
          title="调整后新增"
          count={buckets.onlyRight.length}
          tone="right-only"
        >
          {buckets.onlyRight.map((it) => (
            <ItemRow key={it.id} item={it} side="right" />
          ))}
        </DiffBucket>

        <DiffBucket
          title="判断强度变化"
          count={buckets.bothChanged.length}
          tone="changed"
        >
          {buckets.bothChanged.map(({ left: l, right: r }) => (
            <ItemRowChanged key={l.id} left={l} right={r} />
          ))}
        </DiffBucket>

        <DiffBucket
          title="两边一致"
          count={buckets.bothSame.length}
          tone="same"
          collapsible
        >
          {buckets.bothSame.slice(0, 10).map(({ left: l }) => (
            <ItemRow key={l.id} item={l} side="both" />
          ))}
          {buckets.bothSame.length > 10 && (
            <div
              style={{
                padding: "8px 12px",
                fontSize: 12,
                color: "var(--text-faint)",
                fontStyle: "italic",
              }}
            >
              还有 {buckets.bothSame.length - 10} 条一致项省略
            </div>
          )}
        </DiffBucket>
      </section>
    </div>
  );
}

// ============================================================
// subcomponents · computeDiff 已提取到 lib/v8-run-helpers.ts

function RunHeaderCard({
  side,
  run,
}: {
  side: "left" | "right";
  run: RunSummary;
}) {
  const sideColor = side === "left" ? "var(--bird-2)" : "var(--accent-500)";
  const sideLabel = side === "left" ? "A · 原评审" : "B · 调整后";

  return (
    <div
      style={{
        padding: "14px 16px",
        borderRadius: "var(--r-4)",
        border: `1px solid ${sideColor}`,
        borderLeftWidth: 3,
        background: "var(--surface-raised)",
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 8,
          marginBottom: 4,
        }}
      >
        <span
          style={{
            fontSize: 10,
            fontFamily: "var(--font-mono)",
            fontWeight: 600,
            color: sideColor,
            padding: "2px 6px",
            borderRadius: "var(--r-2)",
            background: `color-mix(in oklch, ${sideColor} 12%, var(--surface-sunken))`,
            letterSpacing: "0.04em",
          }}
        >
          {sideLabel}
        </span>
        <SessionClassChip sessionClass={run.sessionClass} />
      </div>
      <div
        style={{
          fontSize: 14,
          fontWeight: 600,
          color: "var(--text-strong)",
        }}
      >
        {run.label}
      </div>
      {run.subtitle && (
        <div
          style={{
            fontSize: 11,
            fontFamily: "var(--font-mono)",
            color: "var(--text-muted)",
            marginTop: 2,
          }}
        >
          {run.subtitle}
        </div>
      )}
    </div>
  );
}

function SessionClassChip({ sessionClass }: { sessionClass: SessionClass }) {
  const tone = {
    productive: { bg: "var(--status-done-bg)", fg: "var(--status-done-fg)" },
    partial_silent: {
      bg: "var(--status-warn-bg)",
      fg: "var(--status-warn-fg)",
    },
    quota_exhausted: {
      bg: "var(--status-failed-bg)",
      fg: "var(--status-failed-fg)",
    },
    degraded: { bg: "var(--status-warn-bg)", fg: "var(--status-warn-fg)" },
  }[sessionClass];
  return (
    <span
      style={{
        fontSize: 10,
        padding: "1px 6px",
        borderRadius: "var(--r-2)",
        background: tone.bg,
        color: tone.fg,
        fontWeight: 600,
        fontFamily: "var(--font-mono)",
      }}
    >
      {sessionClassLabel(sessionClass)}
    </span>
  );
}

function sessionClassLabel(sessionClass: SessionClass): string {
  return {
    productive: "正常完成",
    partial_silent: "结果不完整",
    quota_exhausted: "额度中断",
    degraded: "部分降级",
  }[sessionClass];
}

function MetricCompare({
  label,
  leftValue,
  rightValue,
  format,
  higherBetter,
}: {
  label: string;
  leftValue: number;
  rightValue: number;
  format: (v: number) => string;
  /** true=高=好 · false=低=好 · undefined=中性 */
  higherBetter?: boolean;
}) {
  const diff = rightValue - leftValue;
  const isImprovement =
    higherBetter === undefined
      ? null
      : higherBetter
        ? diff > 0
        : diff < 0;
  const isEqual = Math.abs(diff) < 1e-9;

  const deltaColor = isEqual
    ? "var(--text-muted)"
    : isImprovement === null
      ? "var(--text-muted)"
      : isImprovement
        ? "var(--status-done-fg)"
        : "var(--status-failed-fg)";

  return (
    <div>
      <div
        style={{
          fontSize: 10,
          fontFamily: "var(--font-mono)",
          color: "var(--text-faint)",
          textTransform: "uppercase",
          letterSpacing: "0.08em",
        }}
      >
        {label}
      </div>
      <div
        style={{
          display: "flex",
          alignItems: "baseline",
          gap: 6,
          marginTop: 4,
          fontFamily: "var(--font-mono)",
          fontVariantNumeric: "tabular-nums",
        }}
      >
        <span style={{ fontSize: 14, color: "var(--text-muted)" }}>
          {format(leftValue)}
        </span>
        <span style={{ color: "var(--text-faint)" }}>→</span>
        <span
          style={{
            fontSize: 14,
            fontWeight: 600,
            color: "var(--text-strong)",
          }}
        >
          {format(rightValue)}
        </span>
        {!isEqual && (
          <span
            style={{
              fontSize: 11,
              color: deltaColor,
              fontWeight: 600,
              marginLeft: 2,
            }}
          >
            {diff > 0 ? "+" : ""}
            {format(Math.abs(diff))}
          </span>
        )}
      </div>
    </div>
  );
}

function DiffBucket({
  title,
  count,
  tone,
  collapsible,
  children,
}: {
  title: string;
  count: number;
  tone: "left-only" | "right-only" | "changed" | "same";
  collapsible?: boolean;
  children: React.ReactNode;
}) {
  const accentColor = {
    "left-only": "var(--bird-2)",
    "right-only": "var(--accent-500)",
    changed: "var(--status-warn-dot)",
    same: "var(--text-muted)",
  }[tone];

  return (
    <details
      open={!collapsible || count > 0}
      style={{
        marginBottom: 10,
        border: "1px solid var(--border-default)",
        borderRadius: "var(--r-4)",
        background: "var(--surface-raised)",
        overflow: "hidden",
      }}
    >
      <summary
        style={{
          display: "flex",
          alignItems: "center",
          gap: 10,
          padding: "10px 14px",
          cursor: "pointer",
          borderBottom: count > 0 ? "1px solid var(--border-subtle)" : "none",
          listStyle: "none",
        }}
      >
        <span
          style={{
            width: 6,
            height: 6,
            borderRadius: "50%",
            background: accentColor,
          }}
        />
        <span
          style={{
            fontSize: 13,
            fontWeight: 600,
            color: "var(--text-strong)",
          }}
        >
          {title}
        </span>
        <span
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: 12,
            color: "var(--text-muted)",
            fontVariantNumeric: "tabular-nums",
          }}
        >
          {count}
        </span>
      </summary>
      {count > 0 && children}
    </details>
  );
}

function ItemRow({
  item,
  side,
}: {
  item: RunItemSummary;
  side: "left" | "right" | "both";
}) {
  const accent =
    side === "left"
      ? "var(--bird-2)"
      : side === "right"
        ? "var(--accent-500)"
        : "var(--neutral-300)";
  const meta = BIRD_META[item.birdId];
  return (
    <div
      style={{
        padding: "8px 14px",
        borderTop: "1px solid var(--border-subtle)",
        display: "flex",
        alignItems: "flex-start",
        gap: 10,
        fontSize: 13,
      }}
    >
      <span
        style={{
          width: 4,
          alignSelf: "stretch",
          background: accent,
          borderRadius: 2,
          marginTop: 2,
        }}
      />
      <span
        style={{
          fontSize: 10,
          fontFamily: "var(--font-mono)",
          fontWeight: 600,
          color: "var(--text-muted)",
          padding: "1px 5px",
          borderRadius: "var(--r-2)",
          background: "var(--surface-sunken)",
          alignSelf: "flex-start",
          marginTop: 2,
        }}
      >
        {meta.label}
      </span>
      <span
        style={{
          flex: 1,
          color: "var(--text-default)",
          lineHeight: 1.5,
        }}
      >
        {item.problem}
      </span>
      <span
        style={{
          fontFamily: "var(--font-mono)",
          fontSize: 11,
          color: "var(--text-muted)",
          fontVariantNumeric: "tabular-nums",
          flexShrink: 0,
        }}
      >
        置信度 {item.confidence.toFixed(2)}
      </span>
    </div>
  );
}

function ItemRowChanged({
  left,
  right,
}: {
  left: RunItemSummary;
  right: RunItemSummary;
}) {
  const delta = right.confidence - left.confidence;
  const deltaColor =
    delta > 0 ? "var(--status-done-fg)" : "var(--status-failed-fg)";
  const meta = BIRD_META[left.birdId];

  return (
    <div
      style={{
        padding: "8px 14px",
        borderTop: "1px solid var(--border-subtle)",
        display: "flex",
        alignItems: "flex-start",
        gap: 10,
        fontSize: 13,
      }}
    >
      <span
        style={{
          width: 4,
          alignSelf: "stretch",
          background: "var(--status-warn-dot)",
          borderRadius: 2,
          marginTop: 2,
        }}
      />
      <span
        style={{
          fontSize: 10,
          fontFamily: "var(--font-mono)",
          fontWeight: 600,
          color: "var(--text-muted)",
          padding: "1px 5px",
          borderRadius: "var(--r-2)",
          background: "var(--surface-sunken)",
          alignSelf: "flex-start",
          marginTop: 2,
        }}
      >
        {meta.label}
      </span>
      <span
        style={{
          flex: 1,
          color: "var(--text-default)",
          lineHeight: 1.5,
        }}
      >
        {left.problem}
      </span>
      <span
        style={{
          fontFamily: "var(--font-mono)",
          fontSize: 11,
          color: "var(--text-muted)",
          fontVariantNumeric: "tabular-nums",
          flexShrink: 0,
        }}
      >
        置信度 {left.confidence.toFixed(2)} →{" "}
        <span
          style={{
            color: deltaColor,
            fontWeight: 600,
          }}
        >
          {right.confidence.toFixed(2)}
        </span>
      </span>
    </div>
  );
}

function formatTokens(n: number): string {
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`;
  return String(n);
}
