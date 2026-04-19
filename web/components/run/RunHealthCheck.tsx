/**
 * RunHealthCheck · v8 Phase 1.5 核心
 *
 * Phase 2 结束 → Phase 3 开始之间必经的"运行质量检查"节点。
 * session 分类 + effective_consistency 环形 + 5 色失败矩阵 + 5 鸟健康度 + CTA。
 *
 * harness 增量 P0-③ 视觉承载:
 * - partial_silent 时不让 PM 直接继续,强制二选一
 * - productive 时提示健康,但仍然可选"重跑"或"继续"
 *
 * 规范源:design-system/啄木鸟-pecker-v8/components/run-health-check.jsx
 */

import { BirdAvatar, type BirdId } from "@/components/birds/BirdAvatar";
import { BIRD_META } from "@/components/birds/BirdBadge";

export type SessionClass =
  | "productive"
  | "partial_silent"
  | "quota_exhausted"
  | "degraded";

export type FailureCategory =
  | "quota_exhausted"
  | "tool_call_failed"
  | "json_parse_error"
  | "empty_submission"
  | "timeout";

export interface BirdHealthData {
  id: BirdId;
  runs: number;
  fails: number;
  submissions: number;
}

interface RunHealthCheckProps {
  sessionClass: SessionClass;
  /** 0-1 */
  consistency: number;
  /** 5 色失败分类计数 */
  failures?: Partial<Record<FailureCategory, number>>;
  /** 5 鸟健康度 · 一般传 4 worker + 1 苍鹰 = 5 只 */
  birds: BirdHealthData[];
  onContinue: () => void;
  onRetry: () => void;
  className?: string;
  style?: React.CSSProperties;
}

export function RunHealthCheck({
  sessionClass,
  consistency,
  failures = {},
  birds,
  onContinue,
  onRetry,
  className,
  style,
}: RunHealthCheckProps) {
  const classInfo: Record<
    SessionClass,
    { fg: string; bg: string; label: string; desc: string }
  > = {
    productive: {
      fg: "var(--status-done-fg)",
      bg: "var(--status-done-bg)",
      label: "productive",
      desc: "run 质量健康,可进入 Phase 3",
    },
    partial_silent: {
      fg: "var(--status-warn-fg)",
      bg: "var(--status-warn-bg)",
      label: "partial_silent",
      desc: "存在静默失败 · 在不完整结果上决策风险很高 · 建议重跑",
    },
    quota_exhausted: {
      fg: "var(--status-failed-fg)",
      bg: "var(--status-failed-bg)",
      label: "quota_exhausted",
      desc: "配额打满导致提前终止",
    },
    degraded: {
      fg: "var(--status-warn-fg)",
      bg: "var(--status-warn-bg)",
      label: "degraded",
      desc: "部分失败但结果仍可用",
    },
  };
  const info = classInfo[sessionClass];
  const isWarn = sessionClass !== "productive";

  return (
    <div
      className={className}
      style={{
        background: "var(--surface-raised)",
        border: `1px solid ${
          isWarn
            ? "color-mix(in oklch, var(--status-warn-dot) 30%, var(--border-default))"
            : "var(--border-default)"
        }`,
        borderRadius: "var(--r-4)",
        overflow: "hidden",
        ...style,
      }}
    >
      {/* top banner */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 14,
          padding: "14px 18px",
          background: info.bg,
          borderBottom: `1px solid ${info.fg}22`,
        }}
      >
        {isWarn && (
          <svg
            width="22"
            height="22"
            viewBox="0 0 22 22"
            style={{ color: info.fg, flexShrink: 0 }}
            aria-hidden
          >
            <path
              d="M11 3 L20 18 L2 18 Z"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.8"
              strokeLinejoin="round"
            />
            <rect x="10.2" y="8" width="1.6" height="5" fill="currentColor" />
            <circle cx="11" cy="15" r="1" fill="currentColor" />
          </svg>
        )}
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
            <span
              style={{
                fontFamily: "var(--font-mono)",
                fontSize: 13,
                fontWeight: 600,
                padding: "2px 8px",
                borderRadius: "var(--r-2)",
                background: info.fg,
                color: "var(--neutral-0)",
              }}
            >
              {info.label}
            </span>
            <span
              style={{
                fontSize: 13,
                color: info.fg,
                fontWeight: 500,
              }}
            >
              {info.desc}
            </span>
          </div>
        </div>
      </div>

      {/* body */}
      <div
        style={{
          padding: "18px 20px",
          display: "grid",
          gridTemplateColumns: "200px 1fr",
          gap: 28,
        }}
      >
        {/* consistency ring */}
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            gap: 8,
          }}
        >
          <ConsistencyRing value={consistency} />
          <div
            style={{
              fontSize: 11,
              color: "var(--text-muted)",
              textAlign: "center",
              lineHeight: 1.4,
            }}
          >
            effective
            <br />
            consistency
          </div>
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          {/* 5 色失败矩阵 */}
          <div>
            <div
              style={{
                fontSize: 11,
                textTransform: "uppercase",
                letterSpacing: 0.8,
                color: "var(--text-muted)",
                fontWeight: 600,
                marginBottom: 8,
              }}
            >
              失败分类 · 5 色
            </div>
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "repeat(5, 1fr)",
                gap: 10,
              }}
            >
              {FAILURE_CATEGORIES.map((f) => (
                <FailureCell
                  key={f.code}
                  code={f.code}
                  token={f.token}
                  label={f.label}
                  n={failures[f.code] ?? 0}
                />
              ))}
            </div>
          </div>

          {/* 5 鸟健康度 */}
          <div>
            <div
              style={{
                fontSize: 11,
                textTransform: "uppercase",
                letterSpacing: 0.8,
                color: "var(--text-muted)",
                fontWeight: 600,
                marginBottom: 8,
              }}
            >
              5 鸟健康度
            </div>
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "repeat(5, 1fr)",
                gap: 10,
              }}
            >
              {birds.map((b) => (
                <BirdHealth key={b.id} {...b} />
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* CTA */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 12,
          padding: "12px 18px",
          borderTop: "1px solid var(--border-default)",
          background: "var(--surface-sunken)",
          flexWrap: "wrap",
        }}
      >
        <div style={{ fontSize: 12, color: "var(--text-muted)", flex: 1, minWidth: 0 }}>
          {sessionClass === "partial_silent"
            ? "⚠ 必须二选一:继续会在不完整结果上决策,建议重跑失败 worker"
            : sessionClass === "quota_exhausted"
              ? "⚠ 配额已打满,重跑前请确认 API key 额度"
              : "两项操作可选,继续不会再次触发预检"}
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <button type="button" onClick={onRetry} style={btnSecondary}>
            重跑失败 worker
          </button>
          <button
            type="button"
            onClick={onContinue}
            style={{
              ...btnPrimary,
              opacity: sessionClass === "partial_silent" ? 0.85 : 1,
            }}
          >
            继续 Phase 3 →
          </button>
        </div>
      </div>
    </div>
  );
}

// ============================================================
// subcomponents

const FAILURE_CATEGORIES: {
  code: FailureCategory;
  token: string;
  label: string;
}[] = [
  { code: "quota_exhausted", token: "--fail-quota", label: "配额" },
  { code: "tool_call_failed", token: "--fail-tool", label: "工具" },
  { code: "json_parse_error", token: "--fail-json", label: "JSON" },
  { code: "empty_submission", token: "--fail-empty", label: "空提交" },
  { code: "timeout", token: "--fail-timeout", label: "超时" },
];

function FailureCell({
  code,
  token,
  label,
  n,
}: {
  code: FailureCategory;
  token: string;
  label: string;
  n: number;
}) {
  return (
    <div
      style={{
        padding: "10px 12px",
        background: `color-mix(in oklch, var(${token}) 10%, var(--surface-sunken))`,
        border: `1px solid color-mix(in oklch, var(${token}) 24%, var(--border-subtle))`,
        borderRadius: "var(--r-3)",
      }}
    >
      <div
        style={{
          fontSize: 22,
          fontWeight: 600,
          color: `var(${token})`,
          fontVariantNumeric: "tabular-nums",
          lineHeight: 1,
          fontFamily: "var(--font-mono)",
        }}
      >
        {n}
      </div>
      <div
        style={{
          fontSize: 11,
          color: "var(--text-default)",
          marginTop: 4,
        }}
      >
        {label}
      </div>
      <div
        style={{
          fontSize: 10,
          fontFamily: "var(--font-mono)",
          color: "var(--text-faint)",
          marginTop: 2,
        }}
      >
        {code}
      </div>
    </div>
  );
}

function ConsistencyRing({ value }: { value: number }) {
  const pct = Math.round(Math.max(0, Math.min(1, value)) * 100);
  const R = 54;
  const C = 2 * Math.PI * R;
  const offset = C * (1 - pct / 100);
  const color =
    pct >= 90
      ? "var(--status-done-dot)"
      : pct >= 70
        ? "var(--status-warn-dot)"
        : "var(--status-failed-dot)";
  return (
    <svg width="130" height="130" viewBox="0 0 130 130" aria-hidden>
      <circle
        cx="65"
        cy="65"
        r={R}
        fill="none"
        stroke="var(--neutral-150)"
        strokeWidth="8"
      />
      <circle
        cx="65"
        cy="65"
        r={R}
        fill="none"
        stroke={color}
        strokeWidth="8"
        strokeDasharray={C}
        strokeDashoffset={offset}
        strokeLinecap="round"
        transform="rotate(-90 65 65)"
        style={{ transition: "stroke-dashoffset var(--dur-slow) var(--ease-out)" }}
      />
      <text
        x="65"
        y="68"
        textAnchor="middle"
        fontSize="26"
        fontWeight="600"
        fill="var(--text-strong)"
        fontFamily="var(--font-mono)"
      >
        {pct}
        <tspan fontSize="14" fill="var(--text-muted)">
          %
        </tspan>
      </text>
    </svg>
  );
}

function BirdHealth({
  id,
  runs,
  fails,
  submissions,
}: BirdHealthData) {
  const healthy = fails === 0;
  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 6,
        padding: "10px 12px",
        background: "var(--surface-sunken)",
        border: `1px solid ${
          healthy
            ? "var(--border-subtle)"
            : "color-mix(in oklch, var(--status-failed-dot) 24%, var(--border-subtle))"
        }`,
        borderRadius: "var(--r-3)",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <BirdAvatar
          id={id}
          size="md"
          status={healthy ? "done" : "failed"}
        />
        <span
          style={{
            fontSize: 12,
            fontWeight: 600,
            color: "var(--text-strong)",
          }}
        >
          {BIRD_META[id].label}鸟
        </span>
      </div>
      <div
        style={{
          display: "flex",
          gap: 10,
          fontFamily: "var(--font-mono)",
          fontSize: 10,
          color: "var(--text-muted)",
          fontVariantNumeric: "tabular-nums",
        }}
      >
        <span>
          <span style={{ opacity: 0.6 }}>runs</span> {runs}
        </span>
        <span
          style={{
            color: fails ? "var(--status-failed-fg)" : "inherit",
          }}
        >
          <span style={{ opacity: 0.6 }}>fails</span> {fails}
        </span>
        <span>
          <span style={{ opacity: 0.6 }}>subs</span> {submissions}
        </span>
      </div>
    </div>
  );
}

// ============================================================
// styles

const btnPrimary: React.CSSProperties = {
  padding: "7px 14px",
  border: 0,
  borderRadius: "var(--r-3)",
  background: "var(--accent-500)",
  color: "var(--accent-fg)",
  fontSize: 12,
  fontWeight: 600,
  cursor: "pointer",
  fontFamily: "var(--font-sans)",
};

const btnSecondary: React.CSSProperties = {
  padding: "7px 14px",
  border: "1px solid var(--border-default)",
  borderRadius: "var(--r-3)",
  background: "var(--surface-raised)",
  color: "var(--text-default)",
  fontSize: 12,
  fontWeight: 500,
  cursor: "pointer",
  fontFamily: "var(--font-sans)",
};
