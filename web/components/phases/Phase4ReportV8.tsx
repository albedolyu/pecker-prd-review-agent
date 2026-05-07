"use client";

/**
 * Phase 4 · v8 · 报告出口(工作文档气质)
 *
 * 数据契约和 v7 Phase4Report 保持一致,优先使用后端确认返回的同源 markdown,
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
import { Download } from "lucide-react";

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
import {
  generateReportMarkdown,
  generateRevisionAdviceMarkdown,
  generateRevisionDraftMarkdown,
  computeStats,
} from "@/lib/generateReport";
import {
  buildPmFriendlySnapshot,
  formatReviewModeLabel,
  type PmFriendlySnapshot,
} from "@/lib/pm-friendly";
import { ROLES, normalizeDimensionKey, type RoleKey } from "@/lib/roles";
import { BirdLabel, type BirdId } from "@/components/birds/BirdAvatar";
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
  const prdContent = useReviewStore((s) => s.prdContent);
  const reviewer = useReviewStore((s) => s.reviewer);
  const mode = useReviewStore((s) => s.mode);
  const confirmedReportMarkdown = useReviewStore(
    (s) => s.confirmedReportMarkdown,
  );
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
    const fallbackMarkdown = generateReportMarkdown(reviewResult, decisions);
    return {
      markdown: confirmedReportMarkdown || fallbackMarkdown,
      stats: computeStats(reviewResult, decisions),
    };
  }, [reviewResult, decisions, confirmedReportMarkdown]);

  const pmSnapshot = useMemo(() => {
    if (!reviewResult) return null;
    return buildPmFriendlySnapshot(reviewResult);
  }, [reviewResult]);

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

  // audit #5: 苍鹰 DAR (Diversified Aggregated Resampling) 简报
  // reviewResult.goshawk_summary 在多轮采样时带 retention_kind_dist + minority_kept,
  // 单轮 (n_samples=1) 走老路径无此字段, 此处静默 best-effort 显示.
  const darSummary = useMemo(() => {
    const g = reviewResult?.goshawk_summary;
    if (!g) return null;
    const nSamples = typeof g.n_samples === "number" ? g.n_samples : null;
    if (!nSamples || nSamples <= 1) return null;
    // retention_kind_dist 只有 summarize_resample_telemetry 走过才有, 此处兜底解构
    const dist = (g.retention_kind_dist as Record<string, number> | undefined) ?? {};
    const minorityKept =
      typeof g.minority_kept === "number" ? g.minority_kept : (dist.minority ?? 0);
    return {
      nSamples,
      nSamplesSucceeded:
        typeof g.n_samples_succeeded === "number" ? g.n_samples_succeeded : nSamples,
      unanimous: dist.unanimous ?? 0,
      majority: dist.majority ?? 0,
      minority: dist.minority ?? 0,
      minorityKept,
    };
  }, [reviewResult]);

  // cross_boundary 计数 (顶部统计用) — 从所有 item 聚合
  const crossBoundaryCount = useMemo(() => {
    if (!reviewResult) return 0;
    return reviewResult.items.filter((it) => it.cross_boundary).length;
  }, [reviewResult]);

  const downloadMarkdownFile = (filename: string, content: string) => {
    const blob = new Blob([content], { type: "text/markdown;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  const safePrdStem = () =>
    (prdName || "PRD").replace(/\.[^.]+$/, "").replace(/[\\/:*?"<>|\s]+/g, "_");

  const handleDownload = () => {
    if (!markdown) return;
    const safeName = safePrdStem();
    const dateTag = new Date().toISOString().slice(0, 10);
    const filename = `评审报告-${safeName}-${dateTag}.md`;
    downloadMarkdownFile(filename, markdown);
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

  const handleDownloadRevisionAdvice = () => {
    if (!reviewResult) return;
    const safeName = safePrdStem();
    const dateTag = new Date().toISOString().slice(0, 10);
    const filename = `修订建议包-${safeName}-${dateTag}.md`;
    const content = generateRevisionAdviceMarkdown(reviewResult, decisions);
    downloadMarkdownFile(filename, content);
    toast.success(`已下载 ${filename}`);
    void auditApi
      .log({
        event: "downloaded_revision_advice",
        workspace,
        prd_name: prdName || "未命名",
        extra: { filename, review_id: reviewResult.review_id },
      })
      .catch(() => {});
  };

  const handleDownloadRevisionDraft = () => {
    if (!reviewResult) return;
    const safeName = safePrdStem();
    const dateTag = new Date().toISOString().slice(0, 10);
    const filename = `修订稿草案-${safeName}-${dateTag}.md`;
    const content = generateRevisionDraftMarkdown(
      reviewResult,
      decisions,
      prdContent,
    );
    downloadMarkdownFile(filename, content);
    toast.success(`已下载 ${filename}`);
    void auditApi
      .log({
        event: "downloaded_revision_draft",
        workspace,
        prd_name: prdName || "未命名",
        extra: { filename, review_id: reviewResult.review_id },
      })
      .catch(() => {});
  };

  const handleDownloadZhiquHandoff = () => {
    if (!pmSnapshot) return;
    const safeName = safePrdStem();
    const dateTag = new Date().toISOString().slice(0, 10);
    const filename = `织雀交接包-${safeName}-${dateTag}.json`;
    const blob = new Blob(
      [JSON.stringify(pmSnapshot.zhiquHandoff, null, 2) + "\n"],
      { type: "application/json;charset=utf-8" },
    );
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
        event: "downloaded_zhiqu_handoff",
        workspace,
        prd_name: prdName || "未命名",
        extra: { filename, review_id: reviewResult?.review_id ?? "" },
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
        `已存入知识库${resp.filename ? `: ${resp.filename}` : ""}`,
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
      if (e.status === 403) toast.error("只读权限不能存入知识库");
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
        `已推送到飞书${resp.msg_id ? ` · 消息号 ${resp.msg_id.slice(0, 8)}` : ""}`,
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
        toast.error("飞书还未配置,请联系系统管理员");
      else if (e.status === 403) toast.error("只读权限不能推送到飞书");
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
      <header style={{ marginBottom: 16 }}>
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

      {/* ── 一句话给研发的结论 ── */}
      <section
        style={{
          marginBottom: 16,
          padding: "14px 18px",
          background:
            stats.peckScore >= 80
              ? "var(--status-failed-bg)"
              : stats.peckScore >= 50
                ? "var(--status-warn-bg)"
                : "var(--status-done-bg)",
          border: `1px solid ${
            stats.peckScore >= 80
              ? "var(--status-failed-dot)"
              : stats.peckScore >= 50
                ? "var(--status-warn-dot)"
                : "var(--status-done-dot)"
          }33`,
          borderRadius: "var(--r-4)",
          display: "flex",
          alignItems: "center",
          gap: 16,
        }}
      >
        <div style={{ flex: 1, minWidth: 0 }}>
          <div
            style={{
              fontSize: 11,
              fontWeight: 600,
              color:
                stats.peckScore >= 80
                  ? "var(--status-failed-fg)"
                  : stats.peckScore >= 50
                    ? "var(--status-warn-fg)"
                    : "var(--status-done-fg)",
              marginBottom: 4,
            }}
          >
            是否建议进入研发评审 · 苍鹰建议
          </div>
          <div
            style={{
              fontSize: 15,
              fontWeight: 600,
              color:
                stats.peckScore >= 80
                  ? "var(--status-failed-fg)"
                  : stats.peckScore >= 50
                    ? "var(--status-warn-fg)"
                    : "var(--status-done-fg)",
              lineHeight: 1.5,
            }}
          >
            {stats.peckScore >= 80
              ? "暂不建议直接发研发评审 — 必改项较多,建议先回炉调整。"
              : stats.peckScore >= 50
                ? "可以发研发评审,但请先确认必改项和建议项是否要补。"
                : "可以发研发评审 — 评审鸟未发现关键阻塞问题。"}
          </div>
          <div
            style={{
              fontSize: 12,
              color: "var(--text-muted)",
              marginTop: 6,
              lineHeight: 1.55,
            }}
          >
            共发现 {stats.total} 条意见 · 接受 {stats.accepted} 条 · 改写{" "}
            {stats.edited} 条 · 拒绝 {stats.rejected} 条
          </div>
        </div>
        {/* 右侧苍鹰头像 · 强化"苍鹰终审建议"的视觉权重 */}
        <img
          src="/birds/goshawk-lg.png"
          alt="苍鹰"
          width={64}
          height={64}
          style={{
            width: 64,
            height: 64,
            borderRadius: "50%",
            flexShrink: 0,
            display: "block",
          }}
          onError={(e) => {
            (e.currentTarget as HTMLImageElement).style.display = "none";
          }}
        />
      </section>

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
          <MetaItem
            label="资料库"
            value={workspace.replace(/^workspace-/, "")}
          />
          <MetaItem label="评审人" value={reviewer || "—"} />
          <MetaItem label="评审模式" value={formatReviewModeLabel(mode)} />
          <MetaItem label="本次运行" value={revNo} />
        </div>
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(5, 1fr)",
            gap: 0,
          }}
        >
          <StatBlock label="意见总数" value={stats.total} />
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
            label="已改写"
            value={stats.edited}
            tone="warn"
          />
          <StatBlock
            label={`PRD 健康度 · ${stats.peckLabel}`}
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

      <PmFriendlySummary
        snapshot={pmSnapshot}
        onDownloadHandoff={handleDownloadZhiquHandoff}
      />

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
              fontWeight: 600,
              color: "var(--accent-600)",
            }}
          >
            反馈回声
          </span>
          <span>
            你这周的接受 / 拒绝会反过来调整评审鸟的判断权重,完整统计在系统监控里可看。
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
        <SectionHead title="评审摘要" hint="按评审维度分组" />
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

      {/* ── 评审治理简报 (DAR + cross_boundary) ── */}
      {(darSummary || crossBoundaryCount > 0) && (
        <section
          style={{
            marginTop: 24,
            padding: "12px 16px",
            borderRadius: "var(--r-3)",
            background: "var(--surface-sunken)",
            border: "1px solid var(--border-subtle)",
            fontSize: 12,
            color: "var(--text-muted)",
            display: "flex",
            flexWrap: "wrap",
            gap: 16,
            alignItems: "center",
          }}
          data-testid="governance-summary"
        >
          <span
            style={{
              fontSize: 12,
              fontWeight: 600,
              color: "var(--accent-600)",
            }}
          >
            评审治理摘要
          </span>
          {darSummary && (
            <span
              data-testid="dar-summary"
              title={`苍鹰多轮交叉校验:${darSummary.nSamplesSucceeded}/${darSummary.nSamples} 轮成功 · 一致 ${darSummary.unanimous} / 多数 ${darSummary.majority} / 少数 ${darSummary.minority}`}
              style={{ fontVariantNumeric: "tabular-nums" }}
            >
              苍鹰多轮校验: {darSummary.nSamplesSucceeded}/{darSummary.nSamples} 轮 ·
              <span style={{ color: "var(--status-done-fg)", marginLeft: 4 }}>
                一致 {darSummary.unanimous}
              </span>{" "}
              ·{" "}
              <span style={{ color: "var(--text-default)" }}>
                多数 {darSummary.majority}
              </span>{" "}
              ·{" "}
              <span style={{ color: "var(--status-warn-fg)" }}>
                少数 {darSummary.minority}
              </span>
              {darSummary.minorityKept > 0 && (
                <span style={{ marginLeft: 4, color: "var(--accent-600)" }}>
                  (保留少数派 {darSummary.minorityKept})
                </span>
              )}
            </span>
          )}
          {crossBoundaryCount > 0 && (
            <span
              data-testid="cross-boundary-count"
              title="评审员引用了非本维度的规则,系统已自动降低权重后保留"
              style={{ fontVariantNumeric: "tabular-nums" }}
            >
              跨维度规则:{" "}
              <span style={{ color: "var(--text-default)" }}>{crossBoundaryCount}</span> 条
            </span>
          )}
        </section>
      )}

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
            导出 Markdown
          </button>
          <button
            type="button"
            onClick={handleDownloadRevisionAdvice}
            style={btnSecondaryStyle}
            title="只导出 PM 已确认采纳或改写的建议,不包含原 PRD 全文"
          >
            下载修订建议包
          </button>
          <button
            type="button"
            onClick={handleDownloadRevisionDraft}
            style={btnSecondaryStyle}
            title="包含原 PRD 全文和已确认建议附录,仅限内网流转"
          >
            下载修订稿草案
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
            title="保存到团队知识库"
          >
            {saveWikiMutation.isPending ? "保存中…" : "存入知识库"}
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
            {feishuMutation.isPending ? "推送中…" : "推送到飞书"}
          </button>
        </div>
        <p
          style={{
            flexBasis: "100%",
            margin: "4px 0 0",
            fontSize: 12,
            lineHeight: 1.6,
            color: "var(--text-muted)",
            textAlign: "right",
          }}
        >
          修订稿草案会包含原 PRD 全文,仅限内网试用流转;如要外发,请先由 PM 自行脱敏。
        </p>
      </footer>
    </div>
  );
}

// ============================================================
// subcomponents

function PmFriendlySummary({
  snapshot,
  onDownloadHandoff,
}: {
  snapshot: PmFriendlySnapshot | null;
  onDownloadHandoff: () => void;
}) {
  if (!snapshot) return null;
  const { pmSummary, pmView, testabilitySummary, zhiquHandoff } = snapshot;
  const riskTone =
    pmSummary.rework_risk === "高"
      ? "failed"
      : pmSummary.rework_risk === "中"
        ? "warn"
        : "done";

  return (
    <section style={{ ...cardStyle, marginTop: 16 }}>
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 280px), 1fr))",
        }}
      >
        <div style={{ padding: "14px 18px" }}>
          <div style={summaryEyebrowStyle}>PM 结论卡</div>
          <div
            style={{
              marginTop: 6,
              fontSize: 18,
              fontWeight: 600,
              color: "var(--text-strong)",
            }}
          >
            {pmSummary.verdict}
          </div>
          <div style={summaryMetricsStyle}>
            <SummaryMetric
              label="返工风险"
              value={pmSummary.rework_risk}
              tone={riskTone}
            />
            <SummaryMetric label="阻塞项" value={pmSummary.blocking_count} />
            <SummaryMetric label="PM 默认" value={`${pmView.pm_count} 条`} />
            <SummaryMetric
              label="工程展开"
              value={`${pmView.engineering_count} 条`}
            />
          </div>
          <div style={dimensionPillWrapStyle}>
            {pmSummary.top_risk_dimensions.length > 0 ? (
              pmSummary.top_risk_dimensions.map((dim) => (
                <span key={dim.dimension} style={dimensionPillStyle}>
                  {dim.dimension} {dim.count}
                </span>
              ))
            ) : (
              <span style={{ color: "var(--text-muted)", fontSize: 12 }}>
                暂无重点风险维度
              </span>
            )}
          </div>
        </div>

        <div style={{ padding: "14px 18px" }}>
          <div style={summaryEyebrowStyle}>织雀测试用例交接</div>
          <div style={summaryMetricsStyle}>
            <SummaryMetric
              label="可测性"
              value={testabilitySummary.testability_verdict}
              tone={
                testabilitySummary.testability_verdict === "blocked"
                  ? "failed"
                  : testabilitySummary.testability_verdict === "partial"
                    ? "warn"
                    : "done"
              }
            />
            <SummaryMetric
              label="覆盖度"
              value={testabilitySummary.estimated_case_coverage}
            />
            <SummaryMetric
              label="阻塞缺口"
              value={testabilitySummary.blocking_gap_count}
            />
            <SummaryMetric
              label="场景"
              value={zhiquHandoff.scenario_matrix.length}
            />
          </div>
          <p
            style={{
              margin: "10px 0 12px",
              fontSize: 12,
              lineHeight: 1.6,
              color: "var(--text-muted)",
            }}
          >
            交接包保留来源追踪和 PM 控制项；阻塞项需要补齐后再让织雀生成对应测试用例。
          </p>
          <button
            type="button"
            onClick={onDownloadHandoff}
            style={{
              ...btnSecondaryStyle,
              display: "inline-flex",
              alignItems: "center",
            }}
            title="下载织雀交接包"
          >
            <Download size={14} strokeWidth={2} style={{ marginRight: 6 }} />
            下载交接包
          </button>
        </div>
      </div>
    </section>
  );
}

function SummaryMetric({
  label,
  value,
  tone,
}: {
  label: string;
  value: number | string;
  tone?: StatTone;
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
    <span style={{ minWidth: 70 }}>
      <span
        style={{
          display: "block",
          fontSize: 10,
          color: "var(--text-faint)",
          fontFamily: "var(--font-mono)",
          textTransform: "uppercase",
          letterSpacing: "0.08em",
        }}
      >
        {label}
      </span>
      <span
        style={{
          display: "block",
          marginTop: 2,
          fontSize: 14,
          fontWeight: 600,
          color: fg,
          fontVariantNumeric: "tabular-nums",
        }}
      >
        {value}
      </span>
    </span>
  );
}

function MetaItem({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div
        style={{
          fontSize: 11,
          color: "var(--text-faint)",
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
          fontSize: 11,
          color: "var(--text-faint)",
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
        <BirdLabel id={birdId} size="md" />
        <span
          style={{
            fontSize: 13,
            color: "var(--text-muted)",
            fontWeight: 400,
          }}
        >
          · {role.responsibility}
        </span>
        <span style={{ flex: 1 }} />
        <span
          style={{
            fontSize: 11,
            color: "var(--text-muted)",
            fontVariantNumeric: "tabular-nums",
          }}
        >
          {items.length} 条 · 接受 {accepted} · 拒绝 {rejected}
          {edited > 0 ? ` · 改写 ${edited}` : ""}
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
                {it.cross_boundary && <CrossBoundaryChip />}
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
                  title={`置信度 ${it.confidence.toFixed(2)}`}
                  style={{
                    fontSize: 11,
                    color:
                      it.confidence < 0.7
                        ? "var(--status-warn-fg)"
                        : "var(--text-muted)",
                    fontVariantNumeric: "tabular-nums",
                  }}
                >
                  {it.confidence < 0.7
                    ? "低置信"
                    : it.confidence >= 0.85
                      ? "高置信"
                      : "中置信"}
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

/**
 * cross_boundary chip · 跨维度规则视觉标 (step 1c)
 *
 * 当 worker 引用的 rule_id 属于 schema_registry 但不在本维度时,
 * apply_advisor_result 保留 + 打 cross_boundary=true + confidence -0.3 降权.
 * 此 chip 让 PM 一眼看出"这条不是本维度核心规则,只是跨域引用".
 */
function CrossBoundaryChip() {
  return (
    <span
      data-testid="cross-boundary-chip"
      title="此规则不属于本维度核心范围,系统已自动降低权重"
      style={{
        display: "inline-flex",
        alignItems: "center",
        marginLeft: 6,
        padding: "1px 6px",
        borderRadius: "var(--r-2)",
        background: "var(--neutral-100)",
        color: "var(--text-muted)",
        fontSize: 10,
        fontWeight: 500,
        lineHeight: 1.4,
        verticalAlign: "middle",
        whiteSpace: "nowrap",
        cursor: "help",
      }}
    >
      跨维度规则
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

const summaryEyebrowStyle: React.CSSProperties = {
  fontSize: 10,
  fontFamily: "var(--font-mono)",
  fontWeight: 600,
  color: "var(--accent-600)",
  textTransform: "uppercase",
  letterSpacing: "0.08em",
};

const summaryMetricsStyle: React.CSSProperties = {
  display: "flex",
  flexWrap: "wrap",
  gap: 14,
  marginTop: 12,
};

const dimensionPillWrapStyle: React.CSSProperties = {
  display: "flex",
  flexWrap: "wrap",
  gap: 6,
  marginTop: 12,
};

const dimensionPillStyle: React.CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  minHeight: 22,
  padding: "0 8px",
  borderRadius: "var(--r-2)",
  background: "var(--surface-sunken)",
  color: "var(--text-default)",
  fontSize: 12,
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
