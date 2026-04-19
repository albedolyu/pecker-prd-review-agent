"use client";

/**
 * /system/health · v8 Sprint 5(v2 预留)
 *
 * 系统健康 tab · eval 回归 + 历史 run consistency 趋势 + rule 权重演化 + session 分类饼图
 * 数据来源:
 *   - GET /api/stability/daily(复用 scripts/stability_daily.py 输出)
 *   - GET /api/eval/regression(复用 eval/ 回归用例)
 *   - GET /api/feedback/rules/performance(rule hit / reject 历史)
 * 当前用 sample 数据演示 UI 壳。
 */

import Link from "next/link";

// ============================================================
// sample data

const LAST_30_DAYS_CONSISTENCY = [
  0.71, 0.68, 0.73, 0.7, 0.75, 0.72, 0.78, 0.76, 0.81, 0.79,
  0.74, 0.77, 0.8, 0.83, 0.82, 0.79, 0.85, 0.87, 0.84, 0.86,
  0.88, 0.85, 0.89, 0.9, 0.87, 0.91, 0.88, 0.92, 0.9, 0.92,
];

const SESSION_DISTRIBUTION = [
  { label: "productive", count: 142, color: "var(--status-done-dot)" },
  { label: "degraded", count: 18, color: "var(--status-warn-dot)" },
  {
    label: "partial_silent",
    count: 11,
    color: "var(--status-warn-fg)",
  },
  {
    label: "quota_exhausted",
    count: 3,
    color: "var(--status-failed-dot)",
  },
];

const TOP_RULES: {
  id: string;
  dim: string;
  weight: number;
  hits: number;
  rejects: number;
  trend: "up" | "down" | "flat";
}[] = [
  { id: "R042", dim: "业务", weight: 0.92, hits: 128, rejects: 8, trend: "up" },
  { id: "R203", dim: "数据", weight: 0.88, hits: 96, rejects: 6, trend: "up" },
  { id: "R109", dim: "风险", weight: 0.78, hits: 44, rejects: 15, trend: "flat" },
  { id: "R087", dim: "体验", weight: 0.62, hits: 22, rejects: 28, trend: "down" },
  { id: "R211", dim: "数据", weight: 0.58, hits: 18, rejects: 24, trend: "down" },
  { id: "R133", dim: "业务", weight: 0.84, hits: 72, rejects: 12, trend: "up" },
];

const EVAL_BASELINE = [
  { name: "worker-ground-truth(20 cases)", score: 0.88, delta: 0.03 },
  { name: "goshawk-cross-check(15 cases)", score: 0.91, delta: 0.01 },
  { name: "evidence-verify(12 cases)", score: 0.84, delta: -0.02 },
  { name: "rule-hit-recall(30 cases)", score: 0.79, delta: 0.05 },
];

const RECENT_RUNS = [
  { id: "r_20260418_1042", reviewer: "晨舒", sessionClass: "productive", consistency: 0.92 },
  { id: "r_20260418_0915", reviewer: "静宜", sessionClass: "productive", consistency: 0.89 },
  {
    id: "r_20260417_1425",
    reviewer: "晨舒",
    sessionClass: "degraded",
    consistency: 0.72,
  },
  {
    id: "r_20260417_1021",
    reviewer: "嘉文",
    sessionClass: "partial_silent",
    consistency: 0.58,
  },
  { id: "r_20260416_1756", reviewer: "晨舒", sessionClass: "productive", consistency: 0.88 },
];

export default function SystemHealthPage() {
  return (
    <div
      style={{
        maxWidth: 1120,
        margin: "0 auto",
        padding: "28px 24px 80px",
        fontFamily: "var(--font-sans)",
        background: "var(--surface-canvas)",
        minHeight: "100vh",
      }}
    >
      <header style={{ marginBottom: 20 }}>
        <div
          style={{
            fontSize: 10,
            fontFamily: "var(--font-mono)",
            fontWeight: 600,
            textTransform: "uppercase",
            letterSpacing: "0.1em",
            color: "var(--accent-600)",
            marginBottom: 4,
          }}
        >
          Harness · System Health
        </div>
        <h1
          style={{
            fontSize: 22,
            fontWeight: 600,
            color: "var(--text-strong)",
            margin: 0,
            letterSpacing: "-0.015em",
          }}
        >
          系统健康
        </h1>
        <p
          style={{
            fontSize: 13,
            color: "var(--text-muted)",
            marginTop: 4,
            lineHeight: 1.55,
          }}
        >
          近 30 天 consistency 趋势 · session 分类 · rule 权重演化 · eval 回归基线
        </p>
      </header>

      <div
        style={{
          marginBottom: 16,
          padding: "8px 14px",
          borderRadius: "var(--r-3)",
          border: "1px dashed var(--border-default)",
          background: "var(--status-warn-bg)",
          color: "var(--status-warn-fg)",
          fontSize: 12,
          fontFamily: "var(--font-sans)",
        }}
      >
        <strong style={{ fontWeight: 600 }}>Sprint 5 · v2 预留</strong> · sample 数据。真实接入{" "}
        <code style={{ fontFamily: "var(--font-mono)" }}>/api/stability/daily</code> +{" "}
        <code style={{ fontFamily: "var(--font-mono)" }}>/api/feedback/rules/performance</code>{" "}
        在 v2 做。
      </div>

      {/* top metrics */}
      <section
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(4, 1fr)",
          gap: 12,
          marginBottom: 20,
        }}
      >
        <MetricCard
          label="本周 consistency"
          value="90%"
          delta="+4%"
          tone="done"
        />
        <MetricCard
          label="近 30 日 run"
          value="174"
          delta="+18"
          tone="info"
        />
        <MetricCard
          label="partial_silent 率"
          value="6.3%"
          delta="-2.1%"
          tone="done"
        />
        <MetricCard
          label="平均 $/run"
          value="$0.18"
          delta="-$0.02"
          tone="done"
        />
      </section>

      {/* grid */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "1fr 320px",
          gap: 16,
        }}
      >
        {/* consistency 趋势 */}
        <section style={cardStyle}>
          <SectionHead
            title="Consistency 趋势"
            hint="近 30 日 effective_consistency · 阈值 0.8"
          />
          <div style={{ padding: "16px 20px 20px" }}>
            <TrendLine values={LAST_30_DAYS_CONSISTENCY} threshold={0.8} />
          </div>
        </section>

        {/* session 分类 */}
        <section style={cardStyle}>
          <SectionHead title="Session 分类" hint="近 174 次 run" />
          <div style={{ padding: "16px 20px 20px" }}>
            <SessionBars data={SESSION_DISTRIBUTION} />
          </div>
        </section>

        {/* rule 权重演化 */}
        <section style={{ ...cardStyle, gridColumn: "1 / -1" }}>
          <SectionHead
            title="Rule 权重 Top 6"
            hint="hover 低命中率规则考虑下线"
          />
          <div style={{ padding: "12px 20px 16px" }}>
            <RuleTable rules={TOP_RULES} />
          </div>
        </section>

        {/* eval 回归 */}
        <section style={{ ...cardStyle, gridColumn: "1 / -1" }}>
          <SectionHead
            title="Eval 回归基线"
            hint="预埋测试用例 · 每日 CI 跑一次"
          />
          <div style={{ padding: "12px 20px 16px" }}>
            <EvalTable rows={EVAL_BASELINE} />
          </div>
        </section>

        {/* 最近 runs */}
        <section style={{ ...cardStyle, gridColumn: "1 / -1" }}>
          <SectionHead title="最近 runs" hint="点 id 进 audit trail replay" />
          <ul
            style={{
              margin: 0,
              padding: 0,
              listStyle: "none",
            }}
          >
            {RECENT_RUNS.map((r) => (
              <li
                key={r.id}
                style={{
                  display: "grid",
                  gridTemplateColumns: "240px 140px 1fr 80px",
                  gap: 12,
                  padding: "10px 20px",
                  borderTop: "1px solid var(--border-subtle)",
                  fontSize: 13,
                  alignItems: "center",
                }}
              >
                <Link
                  href={`/runs/${r.id}/replay`}
                  style={{
                    fontFamily: "var(--font-mono)",
                    color: "var(--text-link)",
                    textDecoration: "none",
                    fontSize: 12,
                  }}
                >
                  {r.id} →
                </Link>
                <span style={{ color: "var(--text-default)" }}>
                  {r.reviewer}
                </span>
                <SessionChip sessionClass={r.sessionClass} />
                <span
                  style={{
                    fontFamily: "var(--font-mono)",
                    fontSize: 12,
                    color: "var(--text-muted)",
                    fontVariantNumeric: "tabular-nums",
                    textAlign: "right",
                  }}
                >
                  {Math.round(r.consistency * 100)}%
                </span>
              </li>
            ))}
          </ul>
        </section>
      </div>

      {/* footer */}
      <footer
        style={{
          marginTop: 20,
          paddingTop: 16,
          borderTop: "1px solid var(--border-subtle)",
          display: "flex",
          justifyContent: "space-between",
          fontSize: 11,
          color: "var(--text-faint)",
          fontFamily: "var(--font-mono)",
        }}
      >
        <span>
          <Link
            href="/system/prompts"
            style={{ color: "inherit", textDecoration: "none" }}
          >
            prompts & rules →
          </Link>
        </span>
        <span>pecker · harness v8 · system/health · sample</span>
      </footer>
    </div>
  );
}

// ============================================================

function MetricCard({
  label,
  value,
  delta,
  tone,
}: {
  label: string;
  value: string;
  delta: string;
  tone: "done" | "warn" | "failed" | "info";
}) {
  const deltaColor = {
    done: "var(--status-done-fg)",
    warn: "var(--status-warn-fg)",
    failed: "var(--status-failed-fg)",
    info: "var(--text-link)",
  }[tone];
  return (
    <div style={{ ...cardStyle, padding: "12px 16px" }}>
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
          gap: 8,
          marginTop: 4,
        }}
      >
        <span
          style={{
            fontSize: 22,
            fontWeight: 600,
            color: "var(--text-strong)",
            fontFamily: "var(--font-mono)",
            fontVariantNumeric: "tabular-nums",
          }}
        >
          {value}
        </span>
        <span
          style={{
            fontSize: 12,
            fontWeight: 600,
            color: deltaColor,
            fontFamily: "var(--font-mono)",
          }}
        >
          {delta}
        </span>
      </div>
    </div>
  );
}

function SectionHead({ title, hint }: { title: string; hint: string }) {
  return (
    <header
      style={{
        padding: "12px 20px",
        borderBottom: "1px solid var(--border-subtle)",
      }}
    >
      <div
        style={{
          fontSize: 14,
          fontWeight: 600,
          color: "var(--text-strong)",
        }}
      >
        {title}
      </div>
      <div
        style={{
          fontSize: 11,
          color: "var(--text-muted)",
          marginTop: 2,
        }}
      >
        {hint}
      </div>
    </header>
  );
}

function TrendLine({
  values,
  threshold,
}: {
  values: number[];
  threshold: number;
}) {
  const w = 640;
  const h = 140;
  const pad = { l: 30, r: 10, t: 12, b: 20 };
  const innerW = w - pad.l - pad.r;
  const innerH = h - pad.t - pad.b;
  const xFor = (i: number) =>
    pad.l + (i / (values.length - 1)) * innerW;
  const yFor = (v: number) => pad.t + (1 - v) * innerH;

  const d = values
    .map((v, i) => `${i === 0 ? "M" : "L"} ${xFor(i)} ${yFor(v)}`)
    .join(" ");

  const thresholdY = yFor(threshold);

  return (
    <svg
      viewBox={`0 0 ${w} ${h}`}
      style={{ width: "100%", height: "auto", maxHeight: 180 }}
      aria-hidden
    >
      {/* grid */}
      {[0.5, 0.7, 0.9].map((gv) => (
        <line
          key={gv}
          x1={pad.l}
          x2={w - pad.r}
          y1={yFor(gv)}
          y2={yFor(gv)}
          stroke="var(--border-subtle)"
          strokeDasharray="2 3"
        />
      ))}
      {/* threshold 线 */}
      <line
        x1={pad.l}
        x2={w - pad.r}
        y1={thresholdY}
        y2={thresholdY}
        stroke="var(--status-warn-dot)"
        strokeDasharray="4 4"
      />
      <text
        x={w - pad.r - 2}
        y={thresholdY - 4}
        fontSize="10"
        fontFamily="var(--font-mono)"
        fill="var(--status-warn-fg)"
        textAnchor="end"
      >
        threshold {threshold.toFixed(1)}
      </text>
      {/* data line */}
      <path
        d={d}
        fill="none"
        stroke="var(--accent-500)"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      {/* last point */}
      <circle
        cx={xFor(values.length - 1)}
        cy={yFor(values[values.length - 1])}
        r="4"
        fill="var(--accent-500)"
      />
      {/* x labels */}
      <text
        x={pad.l}
        y={h - 4}
        fontSize="10"
        fontFamily="var(--font-mono)"
        fill="var(--text-faint)"
      >
        -30d
      </text>
      <text
        x={w - pad.r}
        y={h - 4}
        fontSize="10"
        fontFamily="var(--font-mono)"
        fill="var(--text-faint)"
        textAnchor="end"
      >
        today
      </text>
    </svg>
  );
}

function SessionBars({
  data,
}: {
  data: { label: string; count: number; color: string }[];
}) {
  const total = data.reduce((s, d) => s + d.count, 0);
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      {data.map((d) => {
        const pct = (d.count / total) * 100;
        return (
          <div key={d.label}>
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                fontSize: 11,
                color: "var(--text-muted)",
                fontFamily: "var(--font-mono)",
                marginBottom: 4,
              }}
            >
              <span>{d.label}</span>
              <span style={{ fontVariantNumeric: "tabular-nums" }}>
                {d.count} · {pct.toFixed(1)}%
              </span>
            </div>
            <div
              style={{
                height: 6,
                background: "var(--neutral-100)",
                borderRadius: "var(--r-2)",
                overflow: "hidden",
              }}
            >
              <div
                style={{
                  width: `${pct}%`,
                  height: "100%",
                  background: d.color,
                }}
              />
            </div>
          </div>
        );
      })}
    </div>
  );
}

function RuleTable({
  rules,
}: {
  rules: typeof TOP_RULES;
}) {
  return (
    <table
      style={{
        width: "100%",
        borderCollapse: "collapse",
        fontSize: 12,
      }}
    >
      <thead>
        <tr>
          {["rule", "dim", "weight", "hits", "rejects", "trend"].map((h) => (
            <th
              key={h}
              style={{
                textAlign: "left",
                padding: "8px 0",
                fontSize: 10,
                fontFamily: "var(--font-mono)",
                color: "var(--text-faint)",
                textTransform: "uppercase",
                letterSpacing: "0.08em",
                borderBottom: "1px solid var(--border-subtle)",
                fontWeight: 600,
              }}
            >
              {h}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rules.map((r) => {
          const rejectRate = r.rejects / (r.hits + r.rejects);
          const highReject = rejectRate > 0.4;
          return (
            <tr key={r.id}>
              <td style={tdStyle}>
                <code
                  style={{
                    fontFamily: "var(--font-mono)",
                    fontSize: 12,
                    color: "var(--text-strong)",
                    fontWeight: 600,
                  }}
                >
                  {r.id}
                </code>
              </td>
              <td style={tdStyle}>{r.dim}</td>
              <td
                style={{
                  ...tdStyle,
                  fontFamily: "var(--font-mono)",
                  fontVariantNumeric: "tabular-nums",
                }}
              >
                {r.weight.toFixed(2)}
              </td>
              <td
                style={{
                  ...tdStyle,
                  fontFamily: "var(--font-mono)",
                  fontVariantNumeric: "tabular-nums",
                }}
              >
                {r.hits}
              </td>
              <td
                style={{
                  ...tdStyle,
                  fontFamily: "var(--font-mono)",
                  fontVariantNumeric: "tabular-nums",
                  color: highReject
                    ? "var(--status-failed-fg)"
                    : "var(--text-default)",
                }}
              >
                {r.rejects}
                {highReject && " ⚠"}
              </td>
              <td style={tdStyle}>
                <TrendChip trend={r.trend} />
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

function TrendChip({ trend }: { trend: "up" | "down" | "flat" }) {
  const cfg = {
    up: { icon: "↗", color: "var(--status-done-fg)" },
    down: { icon: "↘", color: "var(--status-failed-fg)" },
    flat: { icon: "→", color: "var(--text-muted)" },
  }[trend];
  return (
    <span
      style={{
        color: cfg.color,
        fontSize: 14,
        fontWeight: 600,
      }}
    >
      {cfg.icon}
    </span>
  );
}

function EvalTable({ rows }: { rows: typeof EVAL_BASELINE }) {
  return (
    <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
      <thead>
        <tr>
          {["test", "score", "Δ"].map((h) => (
            <th
              key={h}
              style={{
                textAlign: "left",
                padding: "8px 0",
                fontSize: 10,
                fontFamily: "var(--font-mono)",
                color: "var(--text-faint)",
                textTransform: "uppercase",
                letterSpacing: "0.08em",
                borderBottom: "1px solid var(--border-subtle)",
                fontWeight: 600,
              }}
            >
              {h}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.name}>
            <td style={tdStyle}>{r.name}</td>
            <td
              style={{
                ...tdStyle,
                fontFamily: "var(--font-mono)",
                fontVariantNumeric: "tabular-nums",
              }}
            >
              {r.score.toFixed(2)}
            </td>
            <td
              style={{
                ...tdStyle,
                fontFamily: "var(--font-mono)",
                fontVariantNumeric: "tabular-nums",
                color:
                  r.delta > 0
                    ? "var(--status-done-fg)"
                    : r.delta < 0
                      ? "var(--status-failed-fg)"
                      : "var(--text-muted)",
              }}
            >
              {r.delta > 0 ? "+" : ""}
              {r.delta.toFixed(2)}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function SessionChip({ sessionClass }: { sessionClass: string }) {
  const cfg: Record<string, { bg: string; fg: string }> = {
    productive: {
      bg: "var(--status-done-bg)",
      fg: "var(--status-done-fg)",
    },
    degraded: {
      bg: "var(--status-warn-bg)",
      fg: "var(--status-warn-fg)",
    },
    partial_silent: {
      bg: "var(--status-warn-bg)",
      fg: "var(--status-warn-fg)",
    },
    quota_exhausted: {
      bg: "var(--status-failed-bg)",
      fg: "var(--status-failed-fg)",
    },
  };
  const tok = cfg[sessionClass] || {
    bg: "var(--neutral-100)",
    fg: "var(--text-muted)",
  };
  return (
    <span
      style={{
        fontFamily: "var(--font-mono)",
        fontSize: 10,
        fontWeight: 600,
        padding: "2px 8px",
        borderRadius: "var(--r-pill)",
        background: tok.bg,
        color: tok.fg,
        justifySelf: "start",
      }}
    >
      {sessionClass}
    </span>
  );
}

const cardStyle: React.CSSProperties = {
  background: "var(--surface-raised)",
  border: "1px solid var(--border-default)",
  borderRadius: "var(--r-4)",
  overflow: "hidden",
};

const tdStyle: React.CSSProperties = {
  padding: "8px 8px 8px 0",
  borderBottom: "1px solid var(--border-subtle)",
  color: "var(--text-default)",
};
