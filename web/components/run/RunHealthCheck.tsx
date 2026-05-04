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
  // 不完整返回的评审员数量(给 PM 看的具体风险)
  const incompleteCount = birds.filter((b) => b.fails > 0).length;

  const classInfo: Record<
    SessionClass,
    {
      tone: "ok" | "warn" | "fail";
      fg: string;
      bg: string;
      label: string;
      headline: string;
      desc: string;
      // 技术 code,留作小字
      code: string;
    }
  > = {
    productive: {
      tone: "ok",
      fg: "var(--status-done-fg)",
      bg: "var(--status-done-bg)",
      label: "本次运行健康",
      headline: "本次运行健康,可进入逐条确认。",
      desc: "所有评审员都正常返回,意见可以放心处理。",
      code: "productive",
    },
    partial_silent: {
      tone: "warn",
      fg: "var(--status-warn-fg)",
      bg: "var(--status-warn-bg)",
      label: incompleteCount > 0
        ? `本次评审有 ${incompleteCount} 个评审员未完整返回`
        : "本次评审有评审员未完整返回",
      headline:
        incompleteCount > 0
          ? `本次评审有 ${incompleteCount} 个评审员未完整返回,继续确认可能遗漏问题。`
          : "本次评审有评审员未完整返回,继续确认可能遗漏问题。",
      desc: "建议先重跑异常评审员,再进入逐条确认。",
      code: "partial_silent",
    },
    quota_exhausted: {
      tone: "fail",
      fg: "var(--status-failed-fg)",
      bg: "var(--status-failed-bg)",
      label: "API 配额已用尽,评审被中断",
      headline: "API 配额已用尽,评审中途终止。",
      desc: "重跑前请确认 API 额度,否则会再次中断。",
      code: "quota_exhausted",
    },
    degraded: {
      tone: "warn",
      fg: "var(--status-warn-fg)",
      bg: "var(--status-warn-bg)",
      label: "部分评审员降级,结果仍可参考",
      headline: "部分评审员未完全返回,但结果仍可参考。",
      desc: "继续确认前可以快速看一眼是哪几只鸟出了状况。",
      code: "degraded",
    },
  };
  const info = classInfo[sessionClass];
  const isWarn = sessionClass !== "productive";
  const isPartialSilent = sessionClass === "partial_silent";

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
      {/* top banner · 头条直接告诉 PM 本次评审是否可信 */}
      <div
        style={{
          display: "flex",
          alignItems: "flex-start",
          gap: 14,
          padding: "16px 20px",
          background: info.bg,
          borderBottom: `1px solid ${info.fg}22`,
        }}
      >
        {info.tone === "ok" ? (
          <svg
            width="24"
            height="24"
            viewBox="0 0 24 24"
            style={{ color: info.fg, flexShrink: 0, marginTop: 1 }}
            aria-hidden
          >
            <circle cx="12" cy="12" r="10" fill="none" stroke="currentColor" strokeWidth="1.8" />
            <path
              d="M7 12.5 L10.5 16 L17 9"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
        ) : (
          <svg
            width="24"
            height="24"
            viewBox="0 0 24 24"
            style={{ color: info.fg, flexShrink: 0, marginTop: 1 }}
            aria-hidden
          >
            <path
              d="M12 3 L22 20 L2 20 Z"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.8"
              strokeLinejoin="round"
            />
            <rect x="11.2" y="9" width="1.6" height="6" fill="currentColor" />
            <circle cx="12" cy="17" r="1.1" fill="currentColor" />
          </svg>
        )}
        <div style={{ flex: 1, minWidth: 0 }}>
          <div
            style={{
              fontSize: 15,
              fontWeight: 600,
              color: info.fg,
              lineHeight: 1.45,
            }}
          >
            {info.headline}
          </div>
          <div
            style={{
              fontSize: 12,
              color: info.fg,
              opacity: 0.85,
              marginTop: 4,
              lineHeight: 1.55,
            }}
          >
            {info.desc}
          </div>
          <div
            style={{
              marginTop: 6,
              fontSize: 10,
              color: info.fg,
              opacity: 0.55,
              fontFamily: "var(--font-mono)",
            }}
            title={`运行分类 code · ${info.code}`}
          >
            {info.code}
          </div>
        </div>
      </div>

      {/* body */}
      <div className="pecker-health-body" style={healthBodyStyle}>
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
              fontSize: 12,
              color: "var(--text-muted)",
              textAlign: "center",
              lineHeight: 1.4,
            }}
          >
            评审员一致率
            <div
              style={{
                fontSize: 10,
                color: "var(--text-faint)",
                marginTop: 2,
              }}
              title="effective consistency · 同维度多评审员产出的相似度"
            >
              数值越高越可信
            </div>
          </div>
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
          {/* 评审员状态(原 5 鸟健康度) */}
          <div>
            <div
              style={{
                fontSize: 13,
                fontWeight: 600,
                color: "var(--text-strong)",
                marginBottom: 8,
              }}
            >
              评审员状态
            </div>
            <div
              className="pecker-health-grid"
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

          {/* 异常分类 — 展开式,PM 默认看到一句话总结 */}
          {Object.values(failures).some((n) => (n ?? 0) > 0) ? (
            <details
              style={{
                background: "var(--surface-sunken)",
                border: "1px solid var(--border-subtle)",
                borderRadius: "var(--r-3)",
                padding: "10px 12px",
              }}
            >
              <summary
                style={{
                  fontSize: 13,
                  fontWeight: 600,
                  color: "var(--text-strong)",
                  cursor: "pointer",
                  userSelect: "none",
                  display: "flex",
                  alignItems: "center",
                  gap: 8,
                  flexWrap: "wrap",
                }}
              >
                <span>异常分类</span>
                <span
                  style={{
                    fontSize: 11,
                    fontWeight: 500,
                    color: "var(--text-muted)",
                  }}
                >
                  {summarizeFailures(failures)}
                </span>
              </summary>
              <div
                className="pecker-health-grid"
                style={{
                  display: "grid",
                  gridTemplateColumns: "repeat(5, 1fr)",
                  gap: 10,
                  marginTop: 10,
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
            </details>
          ) : null}
        </div>
      </div>

      {/* CTA · 强二选一(partial_silent / quota_exhausted)/ 轻提示(productive) */}
      <div
        className="pecker-health-cta"
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 12,
          padding: "14px 20px",
          borderTop: "1px solid var(--border-default)",
          background: "var(--surface-sunken)",
          flexWrap: "wrap",
        }}
      >
        <div
          style={{
            fontSize: 12,
            color: "var(--text-muted)",
            flex: 1,
            minWidth: 220,
            lineHeight: 1.5,
          }}
        >
          {isPartialSilent
            ? "继续确认会在不完整结果上决策,有遗漏问题的风险。"
            : sessionClass === "quota_exhausted"
              ? "重跑前请确认 API 额度,否则会再次中断。"
              : sessionClass === "degraded"
                ? "可以直接进入逐条确认;如果想看到完整结果,也可以重跑。"
                : "本次运行健康,可放心进入逐条确认。"}
        </div>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          {isPartialSilent ? (
            <>
              <button type="button" onClick={onRetry} style={btnPrimary}>
                重跑异常评审员
              </button>
              <button
                type="button"
                onClick={onContinue}
                style={{ ...btnSecondary, color: "var(--text-muted)" }}
              >
                仍继续确认
              </button>
            </>
          ) : sessionClass === "quota_exhausted" ? (
            <>
              <button type="button" onClick={onRetry} style={btnPrimary}>
                重新评审
              </button>
              <button
                type="button"
                onClick={onContinue}
                style={{ ...btnSecondary, color: "var(--text-muted)" }}
              >
                查看现有意见
              </button>
            </>
          ) : (
            <>
              <button type="button" onClick={onRetry} style={btnSecondary}>
                重新评审
              </button>
              <button type="button" onClick={onContinue} style={btnPrimary}>
                进入逐条确认 →
              </button>
            </>
          )}
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
  { code: "quota_exhausted", token: "--fail-quota", label: "配额用尽" },
  { code: "tool_call_failed", token: "--fail-tool", label: "工具异常" },
  { code: "json_parse_error", token: "--fail-json", label: "格式异常" },
  { code: "empty_submission", token: "--fail-empty", label: "未返回意见" },
  { code: "timeout", token: "--fail-timeout", label: "运行超时" },
];

const FAILURE_LABEL_MAP: Record<FailureCategory, string> = Object.fromEntries(
  FAILURE_CATEGORIES.map((f) => [f.code, f.label]),
) as Record<FailureCategory, string>;

function summarizeFailures(
  failures: Partial<Record<FailureCategory, number>>,
): string {
  const parts: string[] = [];
  for (const f of FAILURE_CATEGORIES) {
    const n = failures[f.code] ?? 0;
    if (n > 0) parts.push(`${FAILURE_LABEL_MAP[f.code]} ${n}`);
  }
  if (parts.length === 0) return "未发现异常";
  return parts.join(" · ");
}

const healthBodyStyle: React.CSSProperties = {
  padding: "18px 20px",
  display: "grid",
  gridTemplateColumns: "200px 1fr",
  gap: 28,
};

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
  const dim = n === 0;
  return (
    <div
      title={`分类 code · ${code}`}
      style={{
        padding: "10px 12px",
        background: dim
          ? "var(--surface-canvas)"
          : `color-mix(in oklch, var(${token}) 10%, var(--surface-sunken))`,
        border: `1px solid ${
          dim
            ? "var(--border-subtle)"
            : `color-mix(in oklch, var(${token}) 24%, var(--border-subtle))`
        }`,
        borderRadius: "var(--r-3)",
        opacity: dim ? 0.55 : 1,
      }}
    >
      <div
        style={{
          fontSize: 22,
          fontWeight: 600,
          color: dim ? "var(--text-faint)" : `var(${token})`,
          fontVariantNumeric: "tabular-nums",
          lineHeight: 1,
        }}
      >
        {n}
      </div>
      <div
        style={{
          fontSize: 12,
          color: "var(--text-default)",
          marginTop: 4,
        }}
      >
        {label}
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
      title={`运行 ${runs} · 异常 ${fails} · 提交 ${submissions} 条意见`}
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
          fontSize: 11,
          color: healthy ? "var(--text-muted)" : "var(--status-failed-fg)",
          fontWeight: healthy ? 400 : 600,
        }}
      >
        {healthy
          ? runs === 0
            ? "未运行"
            : `已提交 ${submissions} 条`
          : "未完整返回"}
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
