"use client";

/**
 * /runs/diff · v8 harness 增量 P1⑥
 *
 * Run 对比管理页 · 左右分栏 diff 两次 run。
 * 当前是 UI 壳 · 用 sample 数据演示。
 * 接 scripts/shadow_run.py 的产出在 Sprint 5(GET /api/runs/summary?id=...)。
 */

import Link from "next/link";
import { useState, type CSSProperties } from "react";
import { useQuery } from "@tanstack/react-query";

import {
  RunDiff,
  type RunSummary,
} from "@/components/run/RunDiff";
import {
  ApiError,
  reviewHistoryApi,
  type UsageAction,
  type UsageRun,
} from "@/lib/api";

const SHOW_INTERNAL_RUNS = process.env.NEXT_PUBLIC_ENABLE_INTERNAL_RUNS === "1";

const BASELINE_RUN: RunSummary = {
  label: "原始评审 · 用户等级 PRD v0.3",
  subtitle: "评审编号 r_20260417_1425 · 常规模式",
  sessionClass: "productive",
  consistency: 0.88,
  totalTokens: 42300,
  costUsd: 0.187,
  durationSec: 62.4,
  items: [
    {
      id: "it-1",
      problem: "MAU 目标缺具体数字",
      birdId: 1,
      confidence: 0.9,
      severity: "should",
    },
    {
      id: "it-2",
      problem: "user_level 跨表口径不一致",
      birdId: 2,
      confidence: 0.85,
      severity: "must",
    },
    {
      id: "it-3",
      problem: "注册第 2 步文案歧义",
      birdId: 3,
      confidence: 0.62,
      severity: "suggest",
    },
    {
      id: "it-4",
      problem: "补偿逻辑未定义",
      birdId: 2,
      confidence: 0.58,
      severity: "should",
    },
    {
      id: "it-5",
      problem: "事件埋点命名不规范",
      birdId: 1,
      confidence: 0.7,
      severity: "suggest",
    },
  ],
};

const SHADOW_RUN: RunSummary = {
  label: "规则调整后 · 规则集 v2.1",
  subtitle: "评审编号 r_20260418_1042 · 常规模式",
  sessionClass: "productive",
  consistency: 0.92,
  totalTokens: 48900,
  costUsd: 0.21,
  durationSec: 58.1,
  items: [
    // 相同 problem,conf 变了
    {
      id: "s-1",
      problem: "MAU 目标缺具体数字",
      birdId: 1,
      confidence: 0.95,
      severity: "should",
    },
    {
      id: "s-2",
      problem: "user_level 跨表口径不一致",
      birdId: 2,
      confidence: 0.82,
      severity: "must",
    },
    // conf 变化大
    {
      id: "s-3",
      problem: "注册第 2 步文案歧义",
      birdId: 3,
      confidence: 0.88,
      severity: "should",
    },
    // 只在 shadow:苍鹰漏报补充
    {
      id: "s-6",
      problem: "下游 risk_service SLA 未声明",
      birdId: 4,
      confidence: 0.78,
      severity: "must",
    },
    // 事件埋点保持
    {
      id: "s-5",
      problem: "事件埋点命名不规范",
      birdId: 1,
      confidence: 0.72,
      severity: "suggest",
    },
  ],
  // 注意:it-4 补偿逻辑 只在 baseline,shadow 没出
};

export default function RunsDiffPage() {
  if (!SHOW_INTERNAL_RUNS) {
    return <PersonalReviewHistoryPage />;
  }

  return (
    <div
      style={{
        maxWidth: 1120,
        margin: "0 auto",
        padding: "32px 24px 80px",
        fontFamily: "var(--font-sans)",
        background: "var(--surface-canvas)",
        minHeight: "100vh",
      }}
    >
      {/* header */}
      <header
        style={{
          marginBottom: 24,
          display: "flex",
          alignItems: "baseline",
          justifyContent: "space-between",
          gap: 16,
          flexWrap: "wrap",
        }}
      >
        <div>
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
            历史评审 · 结果对比
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
            两次评审对比
          </h1>
          <p
            style={{
              fontSize: 13,
              color: "var(--text-muted)",
              marginTop: 4,
              lineHeight: 1.55,
            }}
          >
            对比同一 PRD 两次评审之间的意见变化:新增、减少和可信度变化
          </p>
        </div>
        <Link
          href="/review?v=8"
          style={{
            fontSize: 12,
            color: "var(--text-link)",
            textDecoration: "none",
            fontFamily: "var(--font-sans)",
          }}
        >
          ← 返回评审
        </Link>
      </header>

      {/* WIP 提示 */}
      <div
        style={{
          marginBottom: 20,
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
          当前展示样例评审结果,后续接入真实评审记录后可用于口径调整前后对比。
        </span>
      </div>

      <RunDiff left={BASELINE_RUN} right={SHADOW_RUN} />
    </div>
  );
}

function PersonalReviewHistoryPage() {
  const [days, setDays] = useState(30);
  const { data, error, isLoading, isFetching } = useQuery({
    queryKey: ["review-history", days],
    queryFn: () => reviewHistoryApi.get(days),
    retry: false,
    staleTime: 30 * 1000,
  });
  const apiError = error instanceof ApiError ? error : null;
  const runs = data?.runs ?? [];
  const actions = data?.recent_actions ?? [];

  return (
    <div
      style={{
        maxWidth: 980,
        margin: "0 auto",
        padding: "32px 24px 80px",
        fontFamily: "var(--font-sans)",
        background: "var(--surface-canvas)",
        minHeight: "100vh",
      }}
    >
      <header
        style={{
          display: "flex",
          alignItems: "flex-start",
          justifyContent: "space-between",
          gap: 16,
          marginBottom: 20,
        }}
      >
        <div>
          <div
            style={{
              color: "var(--accent-600)",
              fontSize: 11,
              fontWeight: 700,
              marginBottom: 5,
            }}
          >
            评审记录
          </div>
          <h1
            style={{
              margin: 0,
              color: "var(--text-strong)",
              fontSize: 24,
              fontWeight: 650,
              letterSpacing: 0,
            }}
          >
            我的评审记录
          </h1>
          <p
            style={{
              margin: "6px 0 0",
              color: "var(--text-muted)",
              fontSize: 13,
              lineHeight: 1.6,
            }}
          >
            只展示你自己的材料名、资料库、处理结果和关键动作，不展示 PRD 正文。
          </p>
        </div>
        <label
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 8,
            color: "var(--text-muted)",
            fontSize: 12,
          }}
        >
          时间范围
          <select
            value={days}
            onChange={(e) => setDays(Number(e.target.value))}
            style={{
              height: 34,
              border: "1px solid var(--border-default)",
              borderRadius: "var(--r-3)",
              background: "var(--surface-raised)",
              color: "var(--text-default)",
              padding: "0 10px",
              fontFamily: "var(--font-sans)",
            }}
          >
            {[7, 30, 90].map((value) => (
              <option key={value} value={value}>
                最近 {value} 天
              </option>
            ))}
          </select>
        </label>
      </header>

      {isFetching && (
        <div style={{ marginBottom: 12, color: "var(--text-faint)", fontSize: 12 }}>
          正在刷新...
        </div>
      )}
      {isLoading && <EmptyState title="正在读取记录" desc="稍等一下，马上就好。" />}
      {apiError && (
        <EmptyState
          title={apiError.status === 401 ? "请先登录" : "读取失败"}
          desc={
            apiError.status === 401
              ? "登录后可以查看自己的评审记录。"
              : (apiError.detail ?? apiError.message)
          }
        />
      )}

      {data && (
        <div style={{ display: "grid", gap: 16 }}>
          <section style={cardStyle}>
            <SectionHead
              title="最近评审"
              hint="已完成、部分完成和异常记录都会显示；这里不保存正文"
            />
            {runs.length ? (
              <div style={{ display: "flex", flexDirection: "column" }}>
                {runs.map((run, index) => (
                  <HistoryRunRow key={`${run.ts_start}-${index}`} run={run} />
                ))}
              </div>
            ) : (
              <InlineEmpty text="最近还没有完整评审记录。完成一次评审后会出现在这里。" />
            )}
          </section>

          <section style={cardStyle}>
            <SectionHead
              title="最近动作"
              hint="开始评审、下载报告等关键动作；用于确认是否已经成功留痕"
            />
            {actions.length ? (
              <div style={{ display: "flex", flexDirection: "column" }}>
                {actions.map((action, index) => (
                  <HistoryActionRow key={`${action.ts}-${action.event}-${index}`} action={action} />
                ))}
              </div>
            ) : (
              <InlineEmpty text="暂无动作记录。" />
            )}
          </section>
        </div>
      )}
    </div>
  );
}

function HistoryRunRow({ run }: { run: UsageRun }) {
  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "1fr 96px 92px",
        gap: 12,
        alignItems: "center",
        padding: "12px 18px",
        borderTop: "1px solid var(--border-subtle)",
        fontSize: 13,
      }}
    >
      <div>
        <div style={{ color: "var(--text-default)", fontWeight: 650 }}>
          {run.prd_name || "未命名材料"}
        </div>
        <div style={{ color: "var(--text-muted)", marginTop: 3, fontSize: 12 }}>
          {formatWorkspace(run.workspace)} · {modeLabel(run.mode)} · {formatTime(run.ts_start)}
        </div>
      </div>
      <StatusPill status={run.status} />
      <div style={{ color: "var(--text-muted)", textAlign: "right", fontSize: 12 }}>
        <div>{run.items_count ?? 0} 条意见</div>
        <div style={{ color: "var(--text-faint)", marginTop: 2 }}>
          {formatDuration(run.duration_ms)}
        </div>
      </div>
    </div>
  );
}

function HistoryActionRow({ action }: { action: UsageAction }) {
  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "1fr 120px",
        gap: 12,
        padding: "11px 18px",
        borderTop: "1px solid var(--border-subtle)",
        fontSize: 12,
      }}
    >
      <div>
        <div style={{ color: "var(--text-default)", fontWeight: 650 }}>
          {actionLabel(action.event)}
        </div>
        <div style={{ color: "var(--text-muted)", marginTop: 3 }}>
          {action.prd_name || "未命名材料"} · {formatWorkspace(action.workspace)}
        </div>
      </div>
      <div style={{ color: "var(--text-faint)", textAlign: "right" }}>
        {formatTime(action.ts)}
      </div>
    </div>
  );
}

function SectionHead({ title, hint }: { title: string; hint: string }) {
  return (
    <header
      style={{
        padding: "13px 18px",
        borderBottom: "1px solid var(--border-subtle)",
      }}
    >
      <div style={{ color: "var(--text-strong)", fontSize: 14, fontWeight: 650 }}>
        {title}
      </div>
      <div style={{ color: "var(--text-muted)", fontSize: 11, marginTop: 2 }}>
        {hint}
      </div>
    </header>
  );
}

function EmptyState({ title, desc }: { title: string; desc: string }) {
  return (
    <div
      style={{
        ...cardStyle,
        padding: "36px 24px",
        color: "var(--text-muted)",
        textAlign: "center",
      }}
    >
      <h2 style={{ margin: 0, color: "var(--text-strong)", fontSize: 18 }}>
        {title}
      </h2>
      <p style={{ margin: "8px 0 0", fontSize: 13 }}>{desc}</p>
    </div>
  );
}

function InlineEmpty({ text }: { text: string }) {
  return <div style={{ padding: 18, color: "var(--text-muted)", fontSize: 12 }}>{text}</div>;
}

function StatusPill({ status }: { status?: string }) {
  const tone = statusTone(status);
  return (
    <span
      style={{
        justifySelf: "start",
        borderRadius: "var(--r-pill)",
        padding: "2px 8px",
        background: tone.bg,
        color: tone.fg,
        fontWeight: 650,
        fontSize: 11,
        whiteSpace: "nowrap",
      }}
    >
      {statusLabel(status)}
    </span>
  );
}

function statusLabel(status?: string) {
  return {
    completed: "已完成",
    failed: "失败",
    degraded: "部分完成",
    unknown: "未确认",
  }[status ?? "unknown"] ?? "未确认";
}

function statusTone(status?: string) {
  if (status === "completed") {
    return { bg: "var(--status-done-bg)", fg: "var(--status-done-fg)" };
  }
  if (status === "failed") {
    return { bg: "var(--status-failed-bg)", fg: "var(--status-failed-fg)" };
  }
  return { bg: "var(--status-warn-bg)", fg: "var(--status-warn-fg)" };
}

function actionLabel(event?: string) {
  return {
    review_started: "开始评审",
    report_downloaded: "下载报告",
    wiki_saved: "存入资料库",
    feishu_pushed: "推送飞书",
    item_feedback: "处理评审意见",
  }[event ?? ""] ?? (event || "记录动作");
}

function modeLabel(mode?: string) {
  return mode === "quick" ? "轻评审" : "深评审";
}

function formatWorkspace(workspace?: string) {
  return workspace?.replace(/^workspace-/, "") || "未选资料库";
}

function formatDuration(ms?: number) {
  const value = Number(ms ?? 0);
  if (!value) return "未记录耗时";
  const minutes = Math.max(1, Math.round(value / 60000));
  return `${minutes} 分钟`;
}

function formatTime(ts?: string) {
  if (!ts) return "暂无时间";
  const match = ts.match(/^\d{4}-(\d{2})-(\d{2})T(\d{2}):(\d{2})/);
  return match ? `${match[1]}-${match[2]} ${match[3]}:${match[4]}` : ts;
}

const cardStyle: CSSProperties = {
  background: "var(--surface-raised)",
  border: "1px solid var(--border-default)",
  borderRadius: "var(--r-4)",
  overflow: "hidden",
};
