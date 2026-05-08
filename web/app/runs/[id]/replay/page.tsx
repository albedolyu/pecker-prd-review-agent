"use client";

/**
 * /runs/[id]/replay · v8 Sprint 5(v2 预留)
 *
 * Audit trail replay · 某次 run 的完整 event 流回放。
 * 数据来源:event_store(后端 `api/routes/audit.py` 暴露,待 v2 接入)。
 * 当前用 sample data 演示 UI 壳。
 *
 * 功能:
 * - 顶部 run 摘要卡(reviewer / workspace / mode / session_class / duration)
 * - 中段 event timeline(复用 RunConsole 样式,但 live=false)
 * - 点事件行 → 右侧 drawer 展开完整 payload(JSON)
 * - 键盘 j/k 上下切换焦点事件
 */

import { use, useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import type { BirdId } from "@/components/birds/BirdAvatar";
import { BirdAvatar } from "@/components/birds/BirdAvatar";

interface ReplayEvent {
  seq: number;
  t: string; // elapsed 相对 run 开始,如 "0.0s"
  iso: string; // 绝对 UTC
  source: { name: string; bird?: BirdId };
  level: "info" | "ok" | "warn" | "error" | "accent";
  summary: string;
  payload: Record<string, unknown>;
}

interface RunMeta {
  id: string;
  reviewer: string;
  workspace: string;
  mode: string;
  prdName: string;
  sessionClass: string;
  consistency: number;
  durationSec: number;
  totalTokens: number;
  costUsd: number;
  itemsCount: number;
}

const SAMPLE_RUN: RunMeta = {
  id: "r_20260418_1042",
  reviewer: "晨舒",
  workspace: "workspace-对外投资",
  mode: "深评审",
  prdName: "用户等级体系改造 v0.3.md",
  sessionClass: "productive",
  consistency: 0.92,
  durationSec: 58.1,
  totalTokens: 48900,
  costUsd: 0.21,
  itemsCount: 24,
};

const SAMPLE_EVENTS: ReplayEvent[] = [
  {
    seq: 1,
    t: "0.0s",
    iso: "2026-04-18T10:42:00.123Z",
    source: { name: "进度" },
    level: "info",
    summary: "PRD 已接入 · 3487 字 · 42 段",
    payload: {
      event: "uploaded",
      prd_name: "用户等级体系改造 v0.3.md",
      size_bytes: 18432,
      block_count: 42,
    },
  },
  {
    seq: 2,
    t: "1.2s",
    iso: "2026-04-18T10:42:01.321Z",
    source: { name: "进度" },
    level: "info",
    summary: "资料库已加载 · 42 页",
    payload: {
      event: "wiki_scanned",
      page_count: 42,
      total_chars: 184321,
    },
  },
  {
    seq: 3,
    t: "1.4s",
    iso: "2026-04-18T10:42:01.521Z",
    source: { name: "进度" },
    level: "accent",
    summary: "四个检查方向开始并行处理",
    payload: {
      event: "workers_started",
      mode: "standard",
      workers: ["structure", "data_quality", "quality", "ai_coding"],
    },
  },
  {
    seq: 4,
    t: "8.3s",
    iso: "2026-04-18T10:42:08.421Z",
    source: { name: "业务完整性", bird: 1 },
    level: "ok",
    summary: "已完成 · 6 条意见 · 7.1 秒",
    payload: {
      event: "worker_done",
      dim_key: "structure",
      dim_name: "结构层",
      success: true,
      items_count: 6,
      telemetry: {
        duration_ms: 7100,
        tokens_in: 4821,
        tokens_out: 1203,
        cost_usd: 0.0042,
      },
    },
  },
  {
    seq: 5,
    t: "9.7s",
    iso: "2026-04-18T10:42:09.821Z",
    source: { name: "字段口径", bird: 2 },
    level: "ok",
    summary: "已完成 · 8 条意见 · 8.5 秒",
    payload: {
      event: "worker_done",
      dim_key: "data_quality",
      dim_name: "数据质量",
      success: true,
      items_count: 8,
      telemetry: {
        duration_ms: 8500,
        tokens_in: 3912,
        tokens_out: 1540,
        cost_usd: 0.0038,
      },
    },
  },
  {
    seq: 6,
    t: "11.4s",
    iso: "2026-04-18T10:42:11.521Z",
    source: { name: "使用体验", bird: 3 },
    level: "ok",
    summary: "已完成 · 4 条意见 · 10.2 秒",
    payload: {
      event: "worker_done",
      dim_key: "quality",
      dim_name: "质量层",
      success: true,
      items_count: 4,
    },
  },
  {
    seq: 7,
    t: "13.8s",
    iso: "2026-04-18T10:42:13.921Z",
    source: { name: "实现风险", bird: 4 },
    level: "warn",
    summary: "已完成 · 3 条意见 · 结果格式已自动修复",
    payload: {
      event: "worker_done",
      dim_key: "ai_coding",
      dim_name: "AI Coding 友好度",
      success: true,
      degraded: true,
      items_count: 3,
    },
  },
  {
    seq: 8,
    t: "14.0s",
    iso: "2026-04-18T10:42:14.121Z",
    source: { name: "意见收口", bird: 5 },
    level: "accent",
    summary: "开始合并意见,核对依据与遗漏",
    payload: {
      event: "final_reviewer_started",
      input_items: 21,
    },
  },
  {
    seq: 9,
    t: "52.3s",
    iso: "2026-04-18T10:42:52.421Z",
    source: { name: "意见收口", bird: 5 },
    level: "ok",
    summary: "意见合并完成 · 撤回 1 条 · 补充 2 条 · 最终 22 条",
    payload: {
      event: "final_reviewer_done",
      verdict: {
        passed: 19,
        revoked: 1,
        added: 2,
      },
      items_final: 22,
    },
  },
  {
    seq: 10,
    t: "52.6s",
    iso: "2026-04-18T10:42:52.721Z",
    source: { name: "进度" },
    level: "ok",
    summary: "评审完成 · 24 条 · 等待 PM 决策",
    payload: {
      event: "result",
      review_id: "r_20260418_1042",
      items_count: 24,
    },
  },
];

export default function RunReplayPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const [focusedSeq, setFocusedSeq] = useState<number>(SAMPLE_EVENTS[0].seq);
  const [drawerOpen, setDrawerOpen] = useState(false);

  const focusedEvent = useMemo(
    () => SAMPLE_EVENTS.find((e) => e.seq === focusedSeq) ?? SAMPLE_EVENTS[0],
    [focusedSeq],
  );

  // 键盘 j/k
  const handleKey = useCallback((e: KeyboardEvent) => {
    const target = e.target as HTMLElement | null;
    if (
      target &&
      (target.tagName === "TEXTAREA" ||
        target.tagName === "INPUT" ||
        target.isContentEditable)
    ) {
      return;
    }
    if (e.key === "j") {
      e.preventDefault();
      setFocusedSeq((prev) => {
        const idx = SAMPLE_EVENTS.findIndex((ev) => ev.seq === prev);
        return SAMPLE_EVENTS[Math.min(idx + 1, SAMPLE_EVENTS.length - 1)].seq;
      });
    } else if (e.key === "k") {
      e.preventDefault();
      setFocusedSeq((prev) => {
        const idx = SAMPLE_EVENTS.findIndex((ev) => ev.seq === prev);
        return SAMPLE_EVENTS[Math.max(idx - 1, 0)].seq;
      });
    } else if (e.key === "Enter") {
      setDrawerOpen((v) => !v);
    } else if (e.key === "Escape") {
      setDrawerOpen(false);
    }
  }, []);

  useEffect(() => {
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [handleKey]);

  return (
    <div
      style={{
        maxWidth: 1200,
        margin: "0 auto",
        padding: "28px 24px 80px",
        fontFamily: "var(--font-sans)",
        background: "var(--surface-canvas)",
        minHeight: "100vh",
      }}
    >
      {/* header */}
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
          评审记录 · 过程回放
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
          评审复盘 · {id}
        </h1>
        <p
          style={{
            fontSize: 13,
            color: "var(--text-muted)",
            marginTop: 4,
            lineHeight: 1.55,
          }}
        >
          回看这次评审的关键步骤,用于确认意见来源和处理过程
        </p>
      </header>

      {/* WIP banner */}
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
        <strong style={{ fontWeight: 600 }}>演示数据</strong> ·{" "}
        <span style={{ color: "var(--text-default)" }}>
          当前展示样例过程,后续接入真实评审记录后可用于复盘和排障。
        </span>
      </div>

      {/* run meta */}
      <section style={cardStyle}>
        <div
          style={{
            padding: "14px 18px",
            borderBottom: "1px solid var(--border-subtle)",
            display: "grid",
            gridTemplateColumns: "repeat(4, 1fr)",
            gap: 16,
          }}
        >
          <MetaItem label="评审人" value={SAMPLE_RUN.reviewer} />
          <MetaItem
            label="资料库"
            value={SAMPLE_RUN.workspace.replace(/^workspace-/, "")}
          />
          <MetaItem label="模式" value={SAMPLE_RUN.mode} mono />
          <MetaItem label="PRD" value={SAMPLE_RUN.prdName} />
        </div>
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(5, 1fr)",
            gap: 0,
          }}
        >
          <StatBlock
            label="状态"
            value={sessionClassLabel(SAMPLE_RUN.sessionClass)}
            mono
            tone={
              SAMPLE_RUN.sessionClass === "productive" ? "done" : "warn"
            }
          />
          <StatBlock
            label="一致率"
            value={`${Math.round(SAMPLE_RUN.consistency * 100)}%`}
            mono
            tone="done"
          />
          <StatBlock
            label="意见数"
            value={String(SAMPLE_RUN.itemsCount)}
            mono
          />
          <StatBlock
            label="耗时"
            value={`${SAMPLE_RUN.durationSec.toFixed(1)}s`}
            mono
          />
          <StatBlock
            label="处理量"
            value={`约 ${(SAMPLE_RUN.totalTokens / 1000).toFixed(1)}k`}
            mono
          />
        </div>
      </section>

      {/* events + drawer */}
      <div
        style={{
          marginTop: 16,
          display: "grid",
          gridTemplateColumns: drawerOpen ? "1fr 380px" : "1fr",
          gap: 16,
        }}
      >
        {/* timeline */}
        <div
          style={{
            background: "var(--surface-console)",
            borderRadius: "var(--r-4)",
            fontFamily: "var(--font-mono)",
            fontSize: 12,
            lineHeight: 1.55,
            overflow: "hidden",
          }}
        >
          <div
            style={{
              padding: "8px 14px",
              borderBottom: "1px solid rgba(255,255,255,0.06)",
              fontSize: 11,
              color: "rgba(255,255,255,0.6)",
              display: "flex",
              justifyContent: "space-between",
            }}
          >
            <span>评审过程 · {SAMPLE_EVENTS.length} 步</span>
            <span>
              <span style={{ opacity: 0.5 }}>seq </span>
              <span style={{ fontWeight: 600, color: "var(--accent-500)" }}>
                {focusedEvent.seq}
              </span>
              <span style={{ opacity: 0.5 }}>
                {" "}
                / {SAMPLE_EVENTS.length}
              </span>
            </span>
          </div>
          <div style={{ padding: "8px 0", maxHeight: 520, overflow: "auto" }}>
            {SAMPLE_EVENTS.map((ev) => (
              <EventRow
                key={ev.seq}
                event={ev}
                focused={ev.seq === focusedSeq}
                onClick={() => {
                  setFocusedSeq(ev.seq);
                  setDrawerOpen(true);
                }}
              />
            ))}
          </div>
        </div>

        {/* payload drawer */}
        {drawerOpen && (
          <aside style={payloadCardStyle}>
            <header
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                padding: "12px 14px",
                borderBottom: "1px solid var(--border-subtle)",
              }}
            >
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
                  过程明细 · 第 {focusedEvent.seq} 步
                </div>
                <div
                  style={{
                    fontSize: 13,
                    fontWeight: 600,
                    color: "var(--text-strong)",
                    marginTop: 2,
                  }}
                >
                  {focusedEvent.summary}
                </div>
              </div>
              <button
                type="button"
                onClick={() => setDrawerOpen(false)}
                style={btnGhost}
              >
                ×
              </button>
            </header>
            <div style={{ padding: "12px 14px" }}>
              <div
                style={{
                  fontSize: 10,
                  fontFamily: "var(--font-mono)",
                  color: "var(--text-faint)",
                  marginBottom: 6,
                }}
              >
                {focusedEvent.iso}
              </div>
              <details>
                <summary
                  style={{
                    fontSize: 12,
                    color: "var(--text-muted)",
                    cursor: "pointer",
                    userSelect: "none",
                  }}
                >
                  查看原始记录(排障用)
                </summary>
                <pre
                  style={{
                    margin: "8px 0 0",
                    padding: 12,
                    background: "var(--surface-sunken)",
                    border: "1px solid var(--border-default)",
                    borderRadius: "var(--r-3)",
                    fontFamily: "var(--font-mono)",
                    fontSize: 11,
                    lineHeight: 1.55,
                    color: "var(--text-default)",
                    overflow: "auto",
                    maxHeight: 420,
                    whiteSpace: "pre-wrap",
                    wordBreak: "break-word",
                  }}
                >
                  {JSON.stringify(focusedEvent.payload, null, 2)}
                </pre>
              </details>
            </div>
          </aside>
        )}
      </div>

      {/* footer */}
      <footer
        style={{
          marginTop: 20,
          display: "flex",
          justifyContent: "space-between",
          fontSize: 11,
          color: "var(--text-faint)",
          fontFamily: "var(--font-mono)",
        }}
      >
        <Link
          href="/runs/diff"
          style={{ color: "var(--text-muted)", textDecoration: "none" }}
        >
          ← 评审记录
        </Link>
        <span>Pecker · 评审复盘 · 演示数据</span>
      </footer>
    </div>
  );
}

// ============================================================

function sessionClassLabel(sessionClass: string): string {
  return {
    productive: "正常完成",
    degraded: "部分降级",
    partial_silent: "结果不完整",
    quota_exhausted: "额度中断",
  }[sessionClass] ?? sessionClass;
}

function EventRow({
  event,
  focused,
  onClick,
}: {
  event: ReplayEvent;
  focused: boolean;
  onClick: () => void;
}) {
  const levelColor = {
    info: "rgba(255,255,255,0.8)",
    warn: "#e9b450",
    error: "#ff8579",
    ok: "#5ec784",
    accent: "#ff8c4a",
  }[event.level];

  const birdColor = event.source.bird
    ? {
        1: "#ff8c4a",
        2: "#7aabee",
        3: "#5ec784",
        4: "#ff8579",
        5: "#b9a3ff",
      }[event.source.bird as 1 | 2 | 3 | 4 | 5] || "rgba(255,255,255,0.5)"
    : "rgba(255,255,255,0.5)";

  return (
    <button
      type="button"
      onClick={onClick}
      style={{
        display: "grid",
        gridTemplateColumns: "44px 70px 130px 1fr",
        gap: 10,
        width: "100%",
        padding: "3px 14px",
        border: 0,
        background: focused
          ? "rgba(232, 89, 12, 0.12)"
          : "transparent",
        borderLeft: focused
          ? "2px solid var(--accent-500)"
          : "2px solid transparent",
        cursor: "pointer",
        textAlign: "left",
        fontFamily: "var(--font-mono)",
        fontSize: 12,
        color: "var(--surface-console-fg)",
      }}
    >
      <span style={{ color: "rgba(255,255,255,0.3)" }}>
        #{String(event.seq).padStart(2, "0")}
      </span>
      <span
        style={{
          color: "rgba(255,255,255,0.35)",
          fontVariantNumeric: "tabular-nums",
        }}
      >
        {event.t}
      </span>
      <span
        style={{
          color: birdColor,
          fontWeight: 500,
          display: "flex",
          alignItems: "center",
          gap: 6,
        }}
      >
        {event.source.bird && (
          <BirdAvatar id={event.source.bird} size="sm" />
        )}
        [{event.source.name}]
      </span>
      <span
        style={{
          color: levelColor,
          whiteSpace: "nowrap",
          overflow: "hidden",
          textOverflow: "ellipsis",
        }}
      >
        {event.summary}
      </span>
    </button>
  );
}

function MetaItem({
  label,
  value,
  mono,
}: {
  label: string;
  value: string;
  mono?: boolean;
}) {
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
          fontSize: 13,
          color: "var(--text-default)",
          marginTop: 2,
          fontFamily: mono
            ? "var(--font-mono)"
            : "var(--font-sans)",
          wordBreak: "break-all",
        }}
      >
        {value}
      </div>
    </div>
  );
}

function StatBlock({
  label,
  value,
  tone,
  mono,
}: {
  label: string;
  value: string;
  tone?: "done" | "warn" | "failed";
  mono?: boolean;
}) {
  const fg =
    tone === "done"
      ? "var(--status-done-fg)"
      : tone === "warn"
        ? "var(--status-warn-fg)"
        : tone === "failed"
          ? "var(--status-failed-fg)"
          : "var(--text-strong)";
  return (
    <div
      style={{
        padding: "10px 16px",
        borderRight: "1px solid var(--border-subtle)",
      }}
    >
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
          fontSize: 15,
          fontWeight: 600,
          color: fg,
          marginTop: 2,
          fontFamily: mono ? "var(--font-mono)" : "var(--font-sans)",
          fontVariantNumeric: "tabular-nums",
        }}
      >
        {value}
      </div>
    </div>
  );
}

const cardStyle: React.CSSProperties = {
  background: "var(--surface-raised)",
  border: "1px solid var(--border-default)",
  borderRadius: "var(--r-4)",
  overflow: "hidden",
};

const payloadCardStyle: React.CSSProperties = {
  background: "var(--surface-raised)",
  border: "1px solid var(--border-default)",
  borderRadius: "var(--r-4)",
  overflow: "hidden",
  height: "fit-content",
  position: "sticky",
  top: 16,
};

const btnGhost: React.CSSProperties = {
  width: 28,
  height: 28,
  border: 0,
  background: "transparent",
  color: "var(--text-muted)",
  fontSize: 18,
  cursor: "pointer",
  fontFamily: "var(--font-sans)",
  lineHeight: 1,
};
