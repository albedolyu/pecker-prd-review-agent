"use client";

/**
 * Phase 4 · v8 · 报告出口(工作文档气质)
 *
 * 数据契约和 v7 Phase4Report 保持一致(store + api + generateReport 零改动),
 * 只换 UI 层:
 * - 去封面纸片 / 意图散文 / colophon 署名
 * - 顶部元信息卡(meta 表格式)· 中段维度分组评审摘要(CommentThread 风格)
 * - 反馈回声 banner(harness 增量 P1④,本版占位文案,Sprint 4 接真数据)
 * - 底部 3 导出按钮一行排开:下载 md / 保存 wiki / 推送飞书 · 重新开始 secondary
 * - readonly 用户后 2 个 disabled
 * - 折叠预览完整 markdown
 */

import { useMemo, useState } from "react";
import { toast } from "sonner";
import { useMutation, useQuery } from "@tanstack/react-query";

import {
  authApi,
  reportsApi,
  feishuApi,
  draftsApi,
  auditApi,
  ApiError,
  type ReviewItem,
} from "@/lib/api";
import { useReviewStore } from "@/lib/store";
import { generateReportMarkdown, computeStats } from "@/lib/generateReport";
import { ROLES, normalizeDimensionKey, type RoleKey } from "@/lib/roles";
import { BirdAvatar, type BirdId } from "@/components/birds/BirdAvatar";
import { BirdBadge } from "@/components/birds/BirdBadge";
import { MissingReportButton } from "@/components/review/MissingReportButton";

// 把 RoleKey 映射到 BirdAvatar 的 birdId(v8 设计稿里 1-5 对应业务/数据/体验/风险/苍鹰)
// 后续可能重构 RoleKey 系统,暂时用这个映射保持视觉一致
const ROLE_TO_BIRD_ID: Record<RoleKey, BirdId> = {
  structure: 1, // 业务
  data_quality: 2, // 数据
  quality: 3, // 体验
  ai_coding: 4, // 风险
  "final-reviewer": 5, // 苍鹰
  "editor-in-chief": 6,
  "reader-feedback": 7,
  "sample-reader": 8,
  archivist: 9,
  "qa-gatekeeper": 10,
};

export function Phase4ReportV8() {
  const reviewResult = useReviewStore((s) => s.reviewResult);
  const decisions = useReviewStore((s) => s.decisions);
  const workspace = useReviewStore((s) => s.workspace);
  const prdName = useReviewStore((s) => s.prdName);
  const reviewer = useReviewStore((s) => s.reviewer);
  const mode = useReviewStore((s) => s.mode);
  const resetReview = useReviewStore((s) => s.resetReview);

  const [showPreview, setShowPreview] = useState(false);

  const { data: me } = useQuery({
    queryKey: ["me"],
    queryFn: () => authApi.me(),
    retry: false,
    staleTime: 60 * 1000,
  });
  const isReadonly = me?.readonly ?? false;

  const { markdown, stats } = useMemo(() => {
    if (!reviewResult) return { markdown: "", stats: null };
    return {
      markdown: generateReportMarkdown(reviewResult, decisions),
      stats: computeStats(reviewResult, decisions),
    };
  }, [reviewResult, decisions]);

  const itemsByDim = useMemo(() => {
    const map = new Map<RoleKey, ReviewItem[]>();
    if (!reviewResult) return map;
    for (const item of reviewResult.items) {
      const k = normalizeDimensionKey(item.dimension);
      const arr = map.get(k) ?? [];
      arr.push(item);
      map.set(k, arr);
    }
    return map;
  }, [reviewResult]);

  const handleDownload = () => {
    if (!markdown) return;
    const safeName = (prdName || "PRD").replace(/\.[^.]+$/, "");
    const dateTag = new Date().toISOString().slice(0, 10);
    const filename = `评审报告-${safeName}-${dateTag}.md`;
    const blob = new Blob([markdown], { type: "text/markdown;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
    toast.success(`已下载 ${filename}`);
    void auditApi
      .log({
        event: "downloaded_report",
        workspace,
        prd_name: prdName || "未命名",
        extra: { filename },
      })
      .catch(() => {});
  };

  const saveWikiMutation = useMutation({
    mutationFn: () => {
      if (!reviewResult || !stats) throw new Error("缺少评审结果");
      return reportsApi.saveToWiki(workspace, {
        prd_name: prdName || "未命名",
        report_markdown: markdown,
        items_count: stats.total,
        accepted_count: stats.accepted,
        rejected_count: stats.rejected,
        edited_count: stats.edited,
        peck_score: stats.peckScore,
        peck_label: stats.peckLabel,
      });
    },
    onSuccess: (resp) => {
      toast.success(
        `已保存到 wiki${resp.filename ? `: ${resp.filename}` : ""}`,
      );
      void auditApi
        .log({
          event: "saved_to_wiki",
          workspace,
          prd_name: prdName || "未命名",
          extra: { filename: resp.filename ?? "" },
        })
        .catch(() => {});
    },
    onError: (e: ApiError) => {
      if (e.status === 403) toast.error("只读用户不能保存 wiki");
      else toast.error(`保存失败: ${e.detail ?? e.message}`);
    },
  });

  const feishuMutation = useMutation({
    mutationFn: () =>
      feishuApi.send({
        prd_name: prdName || "未命名",
        report_markdown: markdown,
      }),
    onSuccess: (resp) => {
      toast.success(
        `已推送到飞书${resp.msg_id ? ` (msg_id=${resp.msg_id.slice(0, 12)}…)` : ""}`,
      );
      void auditApi
        .log({
          event: "pushed_feishu",
          workspace,
          prd_name: prdName || "未命名",
          extra: { msg_id: resp.msg_id ?? "" },
        })
        .catch(() => {});
    },
    onError: (e: ApiError) => {
      if (e.status === 503)
        toast.error("飞书未配置(需要 FEISHU_APP_ID/APP_SECRET/CHAT_ID)");
      else if (e.status === 403) toast.error("只读用户不能推送飞书");
      else toast.error(`推送失败: ${e.detail ?? e.message}`);
    },
  });

  const handleRestart = async () => {
    if (reviewer) {
      try {
        await draftsApi.delete(reviewer);
      } catch {
        /* ignore */
      }
    }
    resetReview();
  };

  // ── 无结果 guard ──
  if (!reviewResult || !stats) {
    return (
      <div style={emptyWrapStyle}>
        <h2 style={emptyTitleStyle}>没有找到评审数据</h2>
        <p style={emptyDescStyle}>请返回重新开始一次评审。</p>
        <button type="button" onClick={handleRestart} style={btnPrimaryStyle}>
          重新开始
        </button>
      </div>
    );
  }

  const today = new Date();
  const revNo = `${String(today.getMonth() + 1).padStart(2, "0")}${String(today.getDate()).padStart(2, "0")}-${String(today.getHours()).padStart(2, "0")}${String(today.getMinutes()).padStart(2, "0")}`;

  return (
    <div
      style={{
        maxWidth: 860,
        margin: "0 auto",
        padding: "32px 24px 80px",
        fontFamily: "var(--font-sans)",
      }}
    >
      {/* ── 顶部标题 ── */}
      <header style={{ marginBottom: 24 }}>
        <h1
          style={{
            fontSize: 22,
            fontWeight: 600,
            color: "var(--text-strong)",
            margin: 0,
            letterSpacing: "-0.015em",
          }}
        >
          评审报告
        </h1>
        <p
          style={{
            fontSize: 13,
            color: "var(--text-muted)",
            marginTop: 4,
          }}
        >
          {prdName || "未命名 PRD"}
        </p>
      </header>

      {/* ── 元信息卡 ── */}
      <section style={cardStyle}>
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(4, 1fr)",
            gap: 16,
            padding: "14px 18px",
            borderBottom: "1px solid var(--border-subtle)",
          }}
        >
          <MetaItem label="workspace" value={workspace.replace(/^workspace-/, "")} />
          <MetaItem label="reviewer" value={reviewer || "—"} />
          <MetaItem label="模式" value={mode === "quick" ? "简审" : "精审"} />
          <MetaItem label="run no." value={revNo} />
        </div>
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(5, 1fr)",
            gap: 0,
          }}
        >
          <StatBlock label="总条目" value={stats.total} />
          <StatBlock
            label="已接受"
            value={stats.accepted}
            tone="done"
          />
          <StatBlock
            label="已拒绝"
            value={stats.rejected}
            tone="muted"
          />
          <StatBlock
            label="已编辑"
            value={stats.edited}
            tone="warn"
          />
          <StatBlock
            label={`啄伤度 · ${stats.peckLabel}`}
            value={`${stats.peckScore} / 100`}
            tone={
              stats.peckScore >= 80
                ? "failed"
                : stats.peckScore >= 50
                  ? "warn"
                  : stats.peckScore >= 20
                    ? "info"
                    : "done"
            }
            mono
          />
        </div>
      </section>

      {/* ── 反馈回声(harness 增量 P1④ · 本版占位) ── */}
      <section
        style={{
          marginTop: 16,
          padding: "10px 14px",
          borderRadius: "var(--r-4)",
          border: "1px dashed var(--border-default)",
          background: "var(--surface-sunken)",
          fontSize: 12,
          color: "var(--text-muted)",
          lineHeight: 1.6,
          display: "flex",
          alignItems: "center",
          gap: 16,
          flexWrap: "wrap",
        }}
      >
        <span
          style={{
            display: "flex",
            alignItems: "center",
            gap: 8,
            flex: 1,
            minWidth: 240,
          }}
        >
          <span
            style={{
              fontFamily: "var(--font-mono)",
              fontWeight: 600,
              color: "var(--accent-600)",
            }}
          >
            反馈回声
          </span>
          <span>
            你本周的 accept / reject 将通过 EMA 反哺规则权重,详细统计接入 dashboard 后可见。
          </span>
        </span>
        <MissingReportButton
          onSubmit={(payload) => {
            console.log("[harness · missing-report · phase4]", payload);
          }}
        />
      </section>

      {/* ── 按维度分组的评审摘要 ── */}
      <section style={{ marginTop: 24 }}>
        <SectionHead title="评审摘要" hint="按维度分组,点条目看详情" />
        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          {Array.from(itemsByDim.entries()).map(([roleKey, items]) => (
            <DimGroup
              key={roleKey}
              roleKey={roleKey}
              items={items}
              decisions={decisions}
            />
          ))}
        </div>
      </section>

      {/* ── 完整 markdown 预览(折叠) ── */}
      <section style={{ marginTop: 24 }}>
        <button
          type="button"
          onClick={() => setShowPreview((v) => !v)}
          style={linkStyle}
        >
          {showPreview ? "收起完整 markdown ↑" : "展开完整 markdown ↓"}
        </button>
        {showPreview && (
          <pre
            style={{
              marginTop: 10,
              padding: 16,
              background: "var(--surface-sunken)",
              border: "1px solid var(--border-default)",
              borderRadius: "var(--r-4)",
              fontFamily: "var(--font-mono)",
              fontSize: 12,
              lineHeight: 1.65,
              color: "var(--text-default)",
              overflow: "auto",
              maxHeight: 520,
              whiteSpace: "pre-wrap",
              wordBreak: "break-word",
            }}
          >
            {markdown}
          </pre>
        )}
      </section>

      {/* ── 底部导出按钮行 ── */}
      <footer
        style={{
          marginTop: 32,
          paddingTop: 20,
          borderTop: "1px solid var(--border-subtle)",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 12,
          flexWrap: "wrap",
        }}
      >
        <button type="button" onClick={handleRestart} style={btnSecondaryStyle}>
          ← 重新开始
        </button>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <button
            type="button"
            onClick={handleDownload}
            style={btnSecondaryStyle}
          >
            下载 md
          </button>
          <button
            type="button"
            onClick={() => saveWikiMutation.mutate()}
            disabled={isReadonly || saveWikiMutation.isPending}
            style={
              isReadonly || saveWikiMutation.isPending
                ? btnSecondaryDisabledStyle
                : btnSecondaryStyle
            }
          >
            {saveWikiMutation.isPending ? "保存中…" : "保存到 wiki"}
          </button>
          <button
            type="button"
            onClick={() => feishuMutation.mutate()}
            disabled={isReadonly || feishuMutation.isPending}
            style={
              isReadonly || feishuMutation.isPending
                ? btnPrimaryDisabledStyle
                : btnPrimaryStyle
            }
          >
            {feishuMutation.isPending ? "推送中…" : "推送飞书"}
          </button>
        </div>
      </footer>
    </div>
  );
}

// ============================================================
// subcomponents

function MetaItem({ label, value }: { label: string; value: string }) {
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
          wordBreak: "break-all",
        }}
      >
        {value}
      </div>
    </div>
  );
}

type StatTone = "done" | "warn" | "failed" | "info" | "muted";

interface StatBlockProps {
  label: string;
  value: number | string;
  tone?: StatTone;
  mono?: boolean;
}

function StatBlock({ label, value, tone, mono }: StatBlockProps) {
  const fg =
    tone === "done"
      ? "var(--status-done-fg)"
      : tone === "warn"
        ? "var(--status-warn-fg)"
        : tone === "failed"
          ? "var(--status-failed-fg)"
          : tone === "info"
            ? "var(--status-info-fg)"
            : tone === "muted"
              ? "var(--text-muted)"
              : "var(--text-strong)";
  return (
    <div
      style={{
        padding: "12px 18px",
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
          fontSize: 18,
          fontWeight: 600,
          color: fg,
          marginTop: 4,
          fontFamily: mono ? "var(--font-mono)" : "var(--font-sans)",
          fontVariantNumeric: "tabular-nums",
        }}
      >
        {value}
      </div>
    </div>
  );
}

function SectionHead({ title, hint }: { title: string; hint?: string }) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "baseline",
        gap: 8,
        marginBottom: 12,
      }}
    >
      <h2
        style={{
          fontSize: 14,
          fontWeight: 600,
          color: "var(--text-strong)",
          margin: 0,
        }}
      >
        {title}
      </h2>
      {hint && (
        <span style={{ fontSize: 11, color: "var(--text-muted)" }}>{hint}</span>
      )}
    </div>
  );
}

interface DimGroupProps {
  roleKey: RoleKey;
  items: ReviewItem[];
  decisions: Record<string, import("@/lib/api").ItemDecision>;
}

function DimGroup({ roleKey, items, decisions }: DimGroupProps) {
  const role = ROLES[roleKey];
  const birdId = ROLE_TO_BIRD_ID[roleKey];
  const accepted = items.filter((it) => decisions[it.id]?.action === "accept")
    .length;
  const rejected = items.filter((it) => decisions[it.id]?.action === "reject")
    .length;
  const edited = items.filter((it) => decisions[it.id]?.action === "edit")
    .length;

  return (
    <div style={cardStyle}>
      <header
        style={{
          display: "flex",
          alignItems: "center",
          gap: 10,
          padding: "10px 14px",
          borderBottom: "1px solid var(--border-subtle)",
        }}
      >
        <BirdAvatar id={birdId} size="md" />
        <BirdBadge id={birdId} />
        <span
          style={{
            fontSize: 13,
            color: "var(--text-default)",
            fontWeight: 500,
          }}
        >
          {role.responsibility}
        </span>
        <span style={{ flex: 1 }} />
        <span
          style={{
            fontSize: 11,
            fontFamily: "var(--font-mono)",
            color: "var(--text-muted)",
            fontVariantNumeric: "tabular-nums",
          }}
        >
          {items.length} 条 · ✓{accepted} · ✗{rejected}
          {edited > 0 ? ` · ✎${edited}` : ""}
        </span>
      </header>
      <ul
        style={{
          listStyle: "none",
          margin: 0,
          padding: "6px 14px 10px",
          display: "flex",
          flexDirection: "column",
          gap: 6,
        }}
      >
        {items.map((it) => {
          const decision = decisions[it.id];
          return (
            <li
              key={it.id}
              style={{
                display: "flex",
                alignItems: "flex-start",
                gap: 10,
                padding: "8px 4px",
                borderRadius: "var(--r-2)",
                fontSize: 13,
                lineHeight: 1.55,
                color: "var(--text-default)",
                opacity: decision?.action === "reject" ? 0.55 : 1,
              }}
            >
              <DecisionChip action={decision?.action} />
              <span style={{ flex: 1 }}>
                {it.problem || it.suggestion || "(无摘要)"}
                {it.location && (
                  <span
                    style={{
                      marginLeft: 8,
                      fontSize: 11,
                      fontFamily: "var(--font-mono)",
                      color: "var(--text-faint)",
                    }}
                  >
                    ↳ {it.location}
                  </span>
                )}
              </span>
              {typeof it.confidence === "number" && (
                <span
                  style={{
                    fontSize: 11,
                    fontFamily: "var(--font-mono)",
                    color:
                      it.confidence < 0.7
                        ? "var(--status-warn-fg)"
                        : "var(--text-muted)",
                    fontVariantNumeric: "tabular-nums",
                  }}
                >
                  conf {it.confidence.toFixed(2)}
                </span>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function DecisionChip({ action }: { action?: "accept" | "reject" | "edit" }) {
  const map = {
    accept: { label: "✓", fg: "var(--status-done-fg)", bg: "var(--status-done-bg)" },
    reject: { label: "✗", fg: "var(--text-muted)", bg: "var(--neutral-100)" },
    edit: { label: "✎", fg: "var(--status-warn-fg)", bg: "var(--status-warn-bg)" },
  } as const;
  const tok = action ? map[action] : { label: "·", fg: "var(--text-faint)", bg: "transparent" };
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        width: 18,
        height: 18,
        borderRadius: "var(--r-2)",
        background: tok.bg,
        color: tok.fg,
        fontSize: 11,
        fontWeight: 600,
        flexShrink: 0,
        marginTop: 2,
      }}
    >
      {tok.label}
    </span>
  );
}

// ============================================================
// styles

const cardStyle: React.CSSProperties = {
  background: "var(--surface-raised)",
  border: "1px solid var(--border-default)",
  borderRadius: "var(--r-4)",
  overflow: "hidden",
};

const btnPrimaryStyle: React.CSSProperties = {
  height: 34,
  padding: "0 14px",
  border: 0,
  borderRadius: "var(--r-3)",
  background: "var(--accent-500)",
  color: "var(--accent-fg)",
  fontSize: 13,
  fontWeight: 600,
  cursor: "pointer",
  fontFamily: "var(--font-sans)",
};

const btnPrimaryDisabledStyle: React.CSSProperties = {
  ...btnPrimaryStyle,
  background: "var(--neutral-200)",
  color: "var(--text-muted)",
  cursor: "not-allowed",
};

const btnSecondaryStyle: React.CSSProperties = {
  height: 34,
  padding: "0 14px",
  border: "1px solid var(--border-default)",
  borderRadius: "var(--r-3)",
  background: "var(--surface-raised)",
  color: "var(--text-default)",
  fontSize: 13,
  fontWeight: 500,
  cursor: "pointer",
  fontFamily: "var(--font-sans)",
};

const btnSecondaryDisabledStyle: React.CSSProperties = {
  ...btnSecondaryStyle,
  opacity: 0.5,
  cursor: "not-allowed",
};

const linkStyle: React.CSSProperties = {
  background: "transparent",
  border: 0,
  color: "var(--text-link)",
  fontSize: 12,
  cursor: "pointer",
  padding: 0,
  fontFamily: "var(--font-sans)",
  fontWeight: 500,
};

const emptyWrapStyle: React.CSSProperties = {
  maxWidth: 520,
  margin: "80px auto",
  padding: "24px",
  textAlign: "center",
  fontFamily: "var(--font-sans)",
};

const emptyTitleStyle: React.CSSProperties = {
  fontSize: 18,
  fontWeight: 600,
  color: "var(--text-strong)",
  margin: "0 0 6px",
};

const emptyDescStyle: React.CSSProperties = {
  fontSize: 13,
  color: "var(--text-muted)",
  marginBottom: 18,
};
