"use client";

/**
 * Phase 3 · v8 · 逐条确认(工作台气质 · PM 最高频场景)
 *
 * 数据契约和 v7 Phase3Confirm 一致:
 * - reviewResult.items(readonly)· 按 dimension 分组
 * - decisions 字典 · accept / reject / edit
 * - reviewApi.confirm + auditApi.log + setConfirmedReportMarkdown + setPhase(4)
 *
 * v8 UI 规则:
 * - 顶部 stat bar(总计 / 待决 / ✓ / ✗ / ✎)+ dim tabs(含"全部")
 * - 单列 CommentThread list(Sprint 3 再升左右分栏 + DocumentView 锚点联动)
 * - 键盘:j/k 上下 · y 采纳 · n 驳回 · e 改写 · enter 确认生成报告
 *   (focused item 外层 accent 左边框高亮)
 * - edit 态在 CommentThread 下方插 textarea
 * - 底部常驻 KeymapBar + 返回 / 生成报告按钮
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";
import { useMutation } from "@tanstack/react-query";

import { useReviewStore } from "@/lib/store";
import { ROLES, normalizeDimensionKey, type RoleKey } from "@/lib/roles";
import {
  reviewApi,
  auditApi,
  feedbackApi,
  draftsApi,
  ApiError,
  type ConfirmResponse,
  type BusinessDecision,
  type CorrectnessReason,
  type ItemDecision,
  type RejectReason,
  type ReviewItem,
} from "@/lib/api";
import {
  isAsyncGoshawkPending,
  shouldApplyGoshawkPatchDraft,
} from "@/lib/async-goshawk";
import { saveReviewDraftSnapshot } from "@/lib/draft-persistence";
import { explainReviewItemForPm } from "@/lib/pm-friendly";
import {
  findPrdAnchorMatch,
  getPrdAnchorLineLabel,
  getPrdAnchorSnippet,
  type PrdAnchorMatch,
} from "@/lib/prd-anchor";
import { BirdLabel, type BirdId } from "@/components/birds/BirdAvatar";
import { EagleMark } from "@/components/review/CommentThread";
import { EvidenceBlock } from "@/components/review/EvidenceBlock";
import { MissingReportButton } from "@/components/review/MissingReportButton";
import { KeymapBar, ShortcutHint } from "@/components/misc/ShortcutHint";

const ROLE_TO_BIRD_ID: Record<RoleKey, BirdId> = {
  structure: 1,
  data_quality: 2,
  quality: 3,
  ai_coding: 4,
  "final-reviewer": 5,
  "editor-in-chief": 6,
  "reader-feedback": 7,
  "sample-reader": 8,
  archivist: 9,
  "qa-gatekeeper": 10,
};

/**
 * PM 驳回原因 7 分类 (P0 step 2, 2026-04-28 接通)
 * value 必须与后端 models.py:RejectReason 一致 — 改这里要同步:
 *   - models.py / api/models.py / web/lib/api.ts / 测试 enum drift 守护
 * 默认值 = "model_noise" (与后端 _update_rule_perf_from_decisions 兜底一致)
 *
 * 上线前 reject 只发自由文本 reason → 后端按 model_noise 默认记账 →
 * EMA 反馈闭环吃错信号 (Pecker 持续学习承诺 dead). 现在 PM 必选 7 选 1.
 */
const REJECT_CATEGORIES: ReadonlyArray<{
  value: RejectReason;
  label: string;
  hint: string;
}> = [
  { value: "good_issue", label: "实际是好问题(手滑点错)", hint: "改主意了,这条仍然算有效意见" },
  { value: "false_positive", label: "误报", hint: "PRD 确实没这个问题,这条判断不成立" },
  { value: "known_tradeoff", label: "已知取舍,不改", hint: "业务上允许保留,不需要改动" },
  { value: "wiki_missing", label: "资料库缺背景", hint: "意见方向没错,是资料库里缺少背景信息" },
  { value: "rule_too_strict", label: "规则太严", hint: "规则适用范围太宽,误伤了正常情况" },
  { value: "impl_detail", label: "实现细节,不该 PRD 管", hint: "这是研发实现层面的事,PRD 不需要写" },
  { value: "model_noise", label: "判断不准", hint: "意见没有业务意义,不需要采纳" },
];

const DEFAULT_REJECT_CATEGORY: RejectReason = "model_noise";

const CORRECTNESS_REASONS: ReadonlyArray<{
  value: CorrectnessReason;
  label: string;
  hint: string;
}> = [
  { value: "false_positive", label: "误报", hint: "PRD 确实没有这个问题" },
  { value: "unsupported_evidence", label: "依据不足", hint: "当前资料不足以支持这条判断" },
  { value: "rule_too_strict", label: "规则过严", hint: "规则适用范围太宽,误伤了本次场景" },
];

const BUSINESS_DECISIONS: ReadonlyArray<{
  value: BusinessDecision;
  label: string;
  hint: string;
}> = [
  { value: "not_this_iteration", label: "本期不修", hint: "AI 判断成立,但本次迭代暂不处理" },
  { value: "risk_accepted", label: "风险接受", hint: "AI 判断成立,业务侧确认承担风险" },
  { value: "handled_elsewhere", label: "已有安排", hint: "AI 判断成立,已在其他任务或文档处理" },
];

const DEFAULT_BUSINESS_DECISION: BusinessDecision = "not_this_iteration";

const CORRECTNESS_REASON_TO_LEGACY: Record<CorrectnessReason, RejectReason> = {
  false_positive: "false_positive",
  unsupported_evidence: "wiki_missing",
  rule_too_strict: "rule_too_strict",
};

const BUSINESS_DECISION_TO_LEGACY: Record<BusinessDecision, RejectReason> = {
  not_this_iteration: "known_tradeoff",
  risk_accepted: "known_tradeoff",
  handled_elsewhere: "known_tradeoff",
};

function legacyRejectReason(
  correctnessReason?: CorrectnessReason,
  businessDecision?: BusinessDecision,
): RejectReason {
  if (correctnessReason) return CORRECTNESS_REASON_TO_LEGACY[correctnessReason];
  if (businessDecision) return BUSINESS_DECISION_TO_LEGACY[businessDecision];
  return REJECT_CATEGORIES.find((cat) => cat.value === DEFAULT_REJECT_CATEGORY)?.value ?? "model_noise";
}

type GateLogEntry = {
  type?: string;
  pass?: boolean;
  detail?: string;
  reason?: string;
};

function getGateLogEntries(gateLog: ReviewItem["gate_log"]): GateLogEntry[] {
  if (Array.isArray(gateLog)) return gateLog;
  if (
    gateLog &&
    typeof gateLog === "object" &&
    "gates" in gateLog &&
    Array.isArray((gateLog as { gates?: unknown }).gates)
  ) {
    return (gateLog as { gates: GateLogEntry[] }).gates;
  }
  return [];
}

export function Phase3ConfirmV8() {
  const reviewer = useReviewStore((s) => s.reviewer);
  const workspace = useReviewStore((s) => s.workspace);
  const reviewResult = useReviewStore((s) => s.reviewResult);
  const prdContent = useReviewStore((s) => s.prdContent);
  const prdName = useReviewStore((s) => s.prdName);
  const mode = useReviewStore((s) => s.mode);
  const rawMaterials = useReviewStore((s) => s.rawMaterials);
  const userNotes = useReviewStore((s) => s.userNotes);
  const decisions = useReviewStore((s) => s.decisions);
  const setDecision = useReviewStore((s) => s.setDecision);
  const setReviewResult = useReviewStore((s) => s.setReviewResult);
  const setConfirmedReportMarkdown = useReviewStore(
    (s) => s.setConfirmedReportMarkdown,
  );
  const setPhase = useReviewStore((s) => s.setPhase);

  // ── 分组 & tabs ──
  const itemsByDim = useMemo(() => {
    const map = new Map<RoleKey, ReviewItem[]>();
    if (!reviewResult) return map;
    for (const item of reviewResult.items) {
      const key = normalizeDimensionKey(item.dimension);
      const arr = map.get(key) ?? [];
      arr.push(item);
      map.set(key, arr);
    }
    return map;
  }, [reviewResult]);

  const activeDims = useMemo(
    () => Array.from(itemsByDim.keys()),
    [itemsByDim],
  );

  type Tab = "all" | RoleKey;
  const [currentTab, setCurrentTab] = useState<Tab>("all");
  // 严重度过滤(must / should / 其他 / 全部)
  type SevFilter = "all" | "must" | "should" | "other";
  const [sevFilter, setSevFilter] = useState<SevFilter>("all");
  // 状态过滤(待处理 / 已采纳 / 已驳回 / 低置信 / 全部)
  type StatusFilter = "all" | "pending" | "accepted" | "rejected" | "low_conf";
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");

  // 当前聚焦 item(给键盘导航用)
  const [focusedIdx, setFocusedIdx] = useState(0);
  // 进入 edit 态的 item id(每次只能编一条)
  const [editingId, setEditingId] = useState<string | null>(null);
  // 手机端评论抽屉是否展开
  const [drawerOpen, setDrawerOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const lastDraftFingerprintRef = useRef("");
  const draftAutosaveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(
    null,
  );

  const saveDraftNow = useCallback(
    (
      nextDecisions: Record<string, ItemDecision>,
      phase = 3,
      confirmedReportMarkdown = "",
    ) => {
      if (!reviewResult) return Promise.resolve();
      const fingerprint = JSON.stringify({
        review_id: reviewResult.review_id,
        phase,
        decisions: nextDecisions,
        confirmedReportMarkdown,
      });
      return saveReviewDraftSnapshot({
        reviewer,
        phase,
        prdName,
        prdContent,
        workspace: workspace || reviewResult.workspace,
        mode,
        userNotes,
        rawMaterials,
        reviewResult,
        decisions: nextDecisions,
        confirmedReportMarkdown,
      })
        .then(() => {
          lastDraftFingerprintRef.current = fingerprint;
        })
        .catch(() => {});
    },
    [
      reviewResult,
      reviewer,
      prdName,
      prdContent,
      workspace,
      mode,
      userNotes,
      rawMaterials,
    ],
  );

  // 当前 tab 下的 items(过滤后,pinned 优先 + 原顺序)
  const visibleItems = useMemo<ReviewItem[]>(() => {
    if (!reviewResult) return [];
    const base =
      currentTab === "all"
        ? Array.from(reviewResult.items)
        : Array.from(itemsByDim.get(currentTab) ?? []);

    const sevPass = (item: ReviewItem) => {
      if (sevFilter === "all") return true;
      const s = item.severity;
      if (sevFilter === "must") return s === "must";
      if (sevFilter === "should") return s === "should";
      return s !== "must" && s !== "should";
    };
    const statusPass = (item: ReviewItem) => {
      if (statusFilter === "all") return true;
      const action = decisions[item.id]?.action;
      if (statusFilter === "pending") return !action;
      if (statusFilter === "accepted") return action === "accept" || action === "edit";
      if (statusFilter === "rejected") return action === "reject";
      if (statusFilter === "low_conf") {
        const lc = typeof item.confidence === "number" && item.confidence < 0.7;
        const evFailed = getGateLogEntries(item.gate_log).some(
          (g) => (g.type === "evidence_verify" || g.type === "evidence_validator") && !g.pass,
        );
        return lc || evFailed;
      }
      return true;
    };

    return base
      .filter((item) => sevPass(item) && statusPass(item))
      .sort((a, b) => {
        const ap = a.pinned ? 0 : 1;
        const bp = b.pinned ? 0 : 1;
        return ap - bp;
      });
  }, [reviewResult, itemsByDim, currentTab, sevFilter, statusFilter, decisions]);

  // tab / 过滤切换时 focusedIdx 归零
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- 过滤切换后重置键盘焦点,属纯派生 UI 状态
    setFocusedIdx(0);
  }, [currentTab, sevFilter, statusFilter]);

  useEffect(() => {
    if (!reviewResult) return;
    const fingerprint = JSON.stringify({
      review_id: reviewResult.review_id,
      phase: 3,
      decisions,
    });
    if (fingerprint === lastDraftFingerprintRef.current) return;
    if (draftAutosaveTimerRef.current) {
      clearTimeout(draftAutosaveTimerRef.current);
    }
    draftAutosaveTimerRef.current = setTimeout(() => {
      void saveDraftNow(decisions);
    }, 700);
    return () => {
      if (draftAutosaveTimerRef.current) {
        clearTimeout(draftAutosaveTimerRef.current);
        draftAutosaveTimerRef.current = null;
      }
    };
  }, [
    reviewResult,
    decisions,
    saveDraftNow,
  ]);

  // 选中的意见(右栏锚点联动用)
  const focusedItem = useMemo(
    () => visibleItems[focusedIdx],
    [visibleItems, focusedIdx],
  );
  const focusedAnchor = focusedItem?.location ?? undefined;
  const focusedPrdMatch = useMemo(
    () =>
      prdContent
        ? findPrdAnchorMatch(prdContent, focusedAnchor, focusedItem?.evidence)
        : null,
    [prdContent, focusedAnchor, focusedItem?.evidence],
  );
  const focusedPrdSnippet = useMemo(
    () => getPrdAnchorSnippet(prdContent, focusedPrdMatch, 96),
    [prdContent, focusedPrdMatch],
  );
  const focusedPrdLineLabel = useMemo(
    () => getPrdAnchorLineLabel(prdContent, focusedPrdMatch),
    [prdContent, focusedPrdMatch],
  );

  // ── stats ──
  const stats = useMemo(() => {
    const total = reviewResult?.items.length ?? 0;
    const counts = { accept: 0, reject: 0, edit: 0 };
    for (const d of Object.values(decisions)) {
      counts[d.action] = (counts[d.action] ?? 0) + 1;
    }
    const decided = counts.accept + counts.reject + counts.edit;
    return { total, decided, pending: total - decided, ...counts };
  }, [reviewResult, decisions]);

  const goshawkPatchPending = isAsyncGoshawkPending(reviewResult);

  useEffect(() => {
    if (!goshawkPatchPending || !reviewResult || !reviewer) return;
    let stopped = false;
    let timer: ReturnType<typeof setTimeout> | null = null;

    const pollDraftPatch = async () => {
      try {
        const draft = await draftsApi.get(reviewer);
        if (stopped) return;
        if (shouldApplyGoshawkPatchDraft(reviewResult, draft)) {
          setReviewResult(draft.review_result);
          toast.success("终审补充已同步");
          return;
        }
      } catch {
        // Draft refresh is best-effort; the PM can keep reviewing the worker draft.
      }
      if (!stopped) {
        timer = setTimeout(pollDraftPatch, 6000);
      }
    };

    timer = setTimeout(pollDraftPatch, 2500);
    return () => {
      stopped = true;
      if (timer) clearTimeout(timer);
    };
  }, [goshawkPatchPending, reviewResult, reviewer, setReviewResult]);

  // ── confirm mutation(提交到后端 → Phase 4) ──
  const confirmMutation = useMutation({
    mutationFn: () => {
      if (!reviewResult) throw new Error("缺少 reviewResult");
      return reviewApi.confirm({
        review_result: reviewResult,
        decisions: { ...decisions },
      });
    },
    onSuccess: (resp: ConfirmResponse) => {
      toast.success(
        `本次评审已确认 · 采纳 ${resp.accepted} · 改写 ${resp.edited} · 驳回 ${resp.rejected}`,
      );
      void auditApi
        .log({
          event: "review_confirmed",
          workspace: reviewResult?.workspace ?? "",
          prd_name: reviewResult?.prd_name ?? "",
          extra: {
            accepted: resp.accepted,
            rejected: resp.rejected,
            edited: resp.edited,
            total: resp.total ?? 0,
          },
        })
        .catch(() => {});
      setConfirmedReportMarkdown(resp.report_markdown ?? "");
      void saveReviewDraftSnapshot({
        reviewer,
        phase: 4,
        prdName,
        prdContent,
        workspace: workspace || reviewResult?.workspace || "",
        mode,
        userNotes,
        rawMaterials,
        reviewResult,
        decisions,
        confirmedReportMarkdown: resp.report_markdown ?? "",
      }).catch(() => {});
      setPhase(4);
    },
    onError: (e: ApiError) => {
      if (e.status === 403) {
        toast.error("数据校验失败,请重新评审一遍");
      } else {
        toast.error(`确认失败: ${e.detail ?? e.message}`);
      }
    },
  });

  const confirmDisabled = confirmMutation.isPending || goshawkPatchPending;

  // ── 快捷键动作 ──

  const handleAccept = useCallback(
    (itemId: string) => {
      const nextDecision: ItemDecision = { action: "accept" };
      const nextDecisions = { ...decisions, [itemId]: nextDecision };
      setDecision(itemId, nextDecision);
      void saveDraftNow(nextDecisions);
      setEditingId(null);
    },
    [decisions, saveDraftNow, setDecision],
  );

  const handleReject = useCallback(
    (itemId: string) => {
      const existing = decisions[itemId];
      const correctnessReason =
        existing?.action === "reject" ? existing.correctness_reason : undefined;
      const businessDecision =
        existing?.action === "reject" && existing.business_decision
          ? existing.business_decision
          : DEFAULT_BUSINESS_DECISION;
      const nextDecision: ItemDecision = {
        action: "reject",
        reason_category: legacyRejectReason(correctnessReason, businessDecision),
        correctness_reason: correctnessReason,
        business_decision: businessDecision,
        reason: existing?.action === "reject" ? existing.reason : undefined,
      };
      const nextDecisions = { ...decisions, [itemId]: nextDecision };
      setDecision(itemId, nextDecision);
      void saveDraftNow(nextDecisions);
      setEditingId(null);
    },
    [decisions, saveDraftNow, setDecision],
  );

  const handleEdit = useCallback(
    (item: ReviewItem) => {
      const existing = decisions[item.id];
      const nextDecision: ItemDecision = {
        action: "edit",
        edited_problem:
          existing?.action === "edit" && existing.edited_problem
            ? existing.edited_problem
            : (item.problem ?? ""),
      };
      const nextDecisions = { ...decisions, [item.id]: nextDecision };
      setDecision(item.id, nextDecision);
      void saveDraftNow(nextDecisions);
      setEditingId(item.id);
    },
    [decisions, saveDraftNow, setDecision],
  );

  // ── 键盘监听 ──
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      // 在 textarea / input 里打字时不触发
      const target = e.target as HTMLElement | null;
      if (
        target &&
        (target.tagName === "TEXTAREA" ||
          target.tagName === "INPUT" ||
          target.isContentEditable)
      ) {
        return;
      }
      if (!focusedItem) return;

      if (e.key === "j") {
        e.preventDefault();
        setFocusedIdx((i) => Math.min(i + 1, visibleItems.length - 1));
      } else if (e.key === "k") {
        e.preventDefault();
        setFocusedIdx((i) => Math.max(i - 1, 0));
      } else if (e.key === "y") {
        e.preventDefault();
        handleAccept(focusedItem.id);
      } else if (e.key === "n") {
        e.preventDefault();
        handleReject(focusedItem.id);
      } else if (e.key === "e") {
        e.preventDefault();
        handleEdit(focusedItem);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [focusedItem, visibleItems.length, handleAccept, handleReject, handleEdit]);

  // ── focusedItem 改变时滚动到视口 ──
  useEffect(() => {
    if (!focusedItem || !containerRef.current) return;
    const el = containerRef.current.querySelector<HTMLElement>(
      `[data-item-id="${CSS.escape(focusedItem.id)}"]`,
    );
    el?.scrollIntoView({ behavior: "smooth", block: "center" });
  }, [focusedItem]);

  // 严重度计数
  const sevCounts = useMemo(() => {
    if (!reviewResult) return { must: 0, should: 0, other: 0 };
    let must = 0;
    let should = 0;
    let other = 0;
    for (const it of reviewResult.items) {
      if (it.severity === "must") must += 1;
      else if (it.severity === "should") should += 1;
      else other += 1;
    }
    return { must, should, other };
  }, [reviewResult]);

  // 状态计数(待处理 / 已采纳+已改写 / 已驳回 / 低置信)
  const statusCounts = useMemo(() => {
    if (!reviewResult)
      return { pending: 0, accepted: 0, rejected: 0, low_conf: 0 };
    let pending = 0;
    let accepted = 0;
    let rejected = 0;
    let lowConf = 0;
    for (const it of reviewResult.items) {
      const action = decisions[it.id]?.action;
      if (!action) pending += 1;
      else if (action === "accept" || action === "edit") accepted += 1;
      else if (action === "reject") rejected += 1;
      const lc =
        typeof it.confidence === "number" && it.confidence < 0.7;
      const evFailed = getGateLogEntries(it.gate_log).some(
        (g) =>
          (g.type === "evidence_verify" || g.type === "evidence_validator") &&
          !g.pass,
      );
      if (lc || evFailed) lowConf += 1;
    }
    return { pending, accepted, rejected, low_conf: lowConf };
  }, [reviewResult, decisions]);

  // ── 空态 guard ──
  if (!reviewResult) {
    return (
      <div style={emptyWrapStyle}>
        <h2 style={emptyTitleStyle}>没找到评审结果</h2>
        <p style={emptyDescStyle}>
          没有评审运行的产出,请返回重新评审。
        </p>
        <button
          type="button"
          onClick={() => setPhase(2)}
          style={btnPrimaryStyle}
        >
          返回评审运行
        </button>
      </div>
    );
  }

  // 渲染单条意见卡(避免嵌套大量 props 的重复书写)
  const renderItem = (item: ReviewItem, i: number) => (
    <ItemCardV8
      key={item.id}
      item={item}
      focused={i === focusedIdx}
      decision={decisions[item.id]}
      editing={editingId === item.id}
      onFocus={() => setFocusedIdx(i)}
      onAccept={() => handleAccept(item.id)}
      onReject={() => handleReject(item.id)}
      onEdit={() => handleEdit(item)}
      onEditChange={(v) =>
        setDecision(item.id, {
          action: "edit",
          edited_problem: v,
        })
      }
      onRejectReasonChange={(v) => {
        const existing = decisions[item.id];
        const correctnessReason =
          existing?.action === "reject" ? existing.correctness_reason : undefined;
        const businessDecision =
          existing?.action === "reject" ? existing.business_decision : undefined;
        setDecision(item.id, {
          action: "reject",
          reason_category: legacyRejectReason(correctnessReason, businessDecision),
          correctness_reason: correctnessReason,
          business_decision: businessDecision,
          reason: v,
        });
      }}
      onRejectCorrectnessChange={(reason) => {
        const existing = decisions[item.id];
        const businessDecision = reason
          ? undefined
          : existing?.action === "reject" && existing.business_decision
            ? existing.business_decision
            : DEFAULT_BUSINESS_DECISION;
        const nextDecision: ItemDecision = {
          action: "reject",
          reason_category: legacyRejectReason(reason || undefined, businessDecision),
          correctness_reason: reason || undefined,
          business_decision: businessDecision,
          reason: existing?.action === "reject" ? existing.reason : undefined,
        };
        const nextDecisions = { ...decisions, [item.id]: nextDecision };
        setDecision(item.id, nextDecision);
        void saveDraftNow(nextDecisions);
      }}
      onRejectBusinessDecisionChange={(businessDecision) => {
        const existing = decisions[item.id];
        const correctnessReason =
          existing?.action === "reject" ? existing.correctness_reason : undefined;
        const nextDecision: ItemDecision = {
          action: "reject",
          reason_category: legacyRejectReason(
            correctnessReason,
            businessDecision || undefined,
          ),
          correctness_reason: correctnessReason,
          business_decision: businessDecision || undefined,
          reason: existing?.action === "reject" ? existing.reason : undefined,
        };
        const nextDecisions = { ...decisions, [item.id]: nextDecision };
        setDecision(item.id, nextDecision);
        void saveDraftNow(nextDecisions);
      }}
      onEditDone={() => {
        setEditingId(null);
        void saveDraftNow(decisions);
      }}
    />
  );

  // 右栏:意见列表 + 过滤工具条
  const commentColumn = (
    <div
      className="pecker-phase3-comments"
      style={{
        display: "flex",
        flexDirection: "column",
        minWidth: 0,
      }}
    >
      {/* 工具条:维度 tabs */}
      {stats.total > 0 && (
        <div
          style={{
            display: "flex",
            gap: 6,
            flexWrap: "wrap",
            paddingBottom: 8,
            borderBottom: "1px solid var(--border-subtle)",
            overflowX: "auto",
          }}
        >
          <TabBtn
            active={currentTab === "all"}
            onClick={() => setCurrentTab("all")}
            label="全部"
            count={stats.total}
          />
          {activeDims.map((dim) => {
            const role = ROLES[dim];
            const birdId = ROLE_TO_BIRD_ID[dim];
            const count = itemsByDim.get(dim)?.length ?? 0;
            return (
              <TabBtn
                key={dim}
                active={currentTab === dim}
                onClick={() => setCurrentTab(dim)}
                label={role.label}
                sublabel={role.responsibility}
                birdId={birdId}
                count={count}
              />
            );
          })}
        </div>
      )}

      {/* 状态过滤(处理进度) */}
      {stats.total > 0 && (
        <div
          style={{
            display: "flex",
            gap: 6,
            flexWrap: "wrap",
            padding: "10px 0 4px",
            fontSize: 12,
          }}
        >
          <SevFilterBtn
            active={statusFilter === "all"}
            onClick={() => setStatusFilter("all")}
            label="全部"
            count={stats.total}
          />
          <SevFilterBtn
            active={statusFilter === "pending"}
            onClick={() => setStatusFilter("pending")}
            label="待处理"
            count={statusCounts.pending}
            tone="warn"
          />
          <SevFilterBtn
            active={statusFilter === "accepted"}
            onClick={() => setStatusFilter("accepted")}
            label="已采纳"
            count={statusCounts.accepted}
          />
          <SevFilterBtn
            active={statusFilter === "rejected"}
            onClick={() => setStatusFilter("rejected")}
            label="已驳回"
            count={statusCounts.rejected}
          />
          {statusCounts.low_conf > 0 && (
            <SevFilterBtn
              active={statusFilter === "low_conf"}
              onClick={() => setStatusFilter("low_conf")}
              label="依据不足"
              count={statusCounts.low_conf}
            />
          )}
        </div>
      )}

      {/* 严重度过滤 */}
      {stats.total > 0 && (
        <div
          style={{
            display: "flex",
            gap: 6,
            flexWrap: "wrap",
            padding: "4px 0 6px",
            fontSize: 12,
          }}
        >
          <SevFilterBtn
            active={sevFilter === "all"}
            onClick={() => setSevFilter("all")}
            label="所有严重度"
            count={stats.total}
          />
          <SevFilterBtn
            active={sevFilter === "must"}
            onClick={() => setSevFilter("must")}
            label="必须修"
            count={sevCounts.must}
            tone="fail"
          />
          <SevFilterBtn
            active={sevFilter === "should"}
            onClick={() => setSevFilter("should")}
            label="建议修"
            count={sevCounts.should}
            tone="warn"
          />
          {sevCounts.other > 0 && (
            <SevFilterBtn
              active={sevFilter === "other"}
              onClick={() => setSevFilter("other")}
              label="参考"
              count={sevCounts.other}
            />
          )}
        </div>
      )}

      {/* items list */}
      {stats.total > 0 ? (
        visibleItems.length === 0 ? (
          <div
            style={{
              padding: "32px 12px",
              textAlign: "center",
              color: "var(--text-muted)",
              fontSize: 13,
            }}
          >
            当前过滤条件下没有意见
          </div>
        ) : (
          <div
            style={{
              display: "flex",
              flexDirection: "column",
              gap: 10,
              marginTop: 12,
            }}
          >
            {visibleItems.map(renderItem)}
          </div>
        )
      ) : (
        <EmptyClearState />
      )}

      {/* 漏报反馈入口 */}
      {stats.total > 0 && (
        <div
          style={{
            marginTop: 18,
            display: "flex",
            justifyContent: "center",
          }}
        >
          <MissingReportButton
            onSubmit={async (payload) => {
              await feedbackApi.reportMissing({
                problem: payload.problem,
                location: payload.location,
                responsible_bird_id: payload.responsibleBirdId,
                workspace: workspace || reviewResult?.workspace || "",
                prd_name: prdName || reviewResult?.prd_name || "",
                pm_name: reviewer,
              });
            }}
          />
        </div>
      )}
    </div>
  );

  // 左栏:PRD 原文(简单 markdown-ish 渲染 + 锚点高亮)
  const docColumn = (
    <div
      className="pecker-phase3-doc"
      style={{
        background: "var(--surface-raised)",
        border: "1px solid var(--border-default)",
        borderRadius: "var(--r-4)",
        display: "flex",
        flexDirection: "column",
        minHeight: 0,
        overflow: "hidden",
      }}
    >
      <div
        style={{
          padding: "12px 16px",
          borderBottom: "1px solid var(--border-default)",
          display: "flex",
          alignItems: "baseline",
          justifyContent: "space-between",
          gap: 10,
          flexWrap: "wrap",
        }}
      >
        <div style={{ minWidth: 0 }}>
          <div
            style={{
              fontSize: 13,
              fontWeight: 600,
              color: "var(--text-strong)",
            }}
          >
            PRD 原文
          </div>
          {prdName && (
            <div
              style={{
                fontSize: 11,
                color: "var(--text-faint)",
                marginTop: 2,
              }}
            >
              {prdName}
            </div>
          )}
        </div>
        {focusedAnchor && (
          <>
            <span
              title="当前选中意见所引用的位置"
              style={{
                fontSize: 11,
                padding: "2px 8px",
                borderRadius: "var(--r-pill)",
                background: "var(--accent-50)",
                color: "var(--accent-700)",
                fontWeight: 600,
              }}
            >
              ↳ {focusedAnchor}
            </span>
            <span
              title={
                focusedPrdMatch
                  ? "已在原文中定位并高亮"
                  : "没有找到完全匹配的位置，仍保留完整原文供核对"
              }
              style={{
                fontSize: 11,
                padding: "2px 8px",
                borderRadius: "var(--r-pill)",
                background: focusedPrdMatch
                  ? "var(--status-success-bg)"
                  : "var(--status-warn-bg)",
                color: focusedPrdMatch
                  ? "var(--status-success-fg)"
                  : "var(--status-warn-fg)",
                fontWeight: 600,
              }}
            >
              {focusedPrdMatch ? "已定位原文" : "未精确定位"}
            </span>
          </>
        )}
      </div>
      {focusedAnchor && (
        <div
          style={{
            borderBottom: "1px solid var(--border-subtle)",
            background: focusedPrdMatch
              ? "color-mix(in oklch, var(--accent-500) 7%, var(--surface-raised))"
              : "var(--status-warn-bg)",
            padding: "10px 16px",
          }}
        >
          <div
            style={{
              fontSize: 11,
              fontWeight: 700,
              color: focusedPrdMatch
                ? "var(--accent-700)"
                : "var(--status-warn-fg)",
              marginBottom: 4,
            }}
          >
            {focusedPrdMatch
              ? `定位摘录${focusedPrdLineLabel ? ` · ${focusedPrdLineLabel}` : ""}`
              : "未找到精确位置"}
          </div>
          <div
            style={{
              fontSize: 12,
              lineHeight: 1.65,
              color: "var(--text-default)",
            }}
          >
            {focusedPrdSnippet ||
              "这条意见没有匹配到原文片段,请对照右侧的位置与依据人工确认。"}
          </div>
        </div>
      )}
      <div
        style={{
          flex: 1,
          overflow: "auto",
          padding: "14px 18px",
          fontSize: 13,
          lineHeight: 1.7,
          color: "var(--text-default)",
          whiteSpace: "pre-wrap",
          wordBreak: "break-word",
        }}
      >
        {prdContent ? (
          renderPrdDocument(prdContent, focusedPrdMatch)
        ) : (
          <span
            style={{
              color: "var(--text-faint)",
              fontStyle: "italic",
            }}
          >
            (PRD 原文未加载)
          </span>
        )}
      </div>
    </div>
  );

  return (
    <div
      ref={containerRef}
      className="pecker-phase3"
      style={{
        maxWidth: 1480,
        margin: "0 auto",
        padding: "20px 24px 140px", // 底部留空给 sticky 批量栏
        fontFamily: "var(--font-sans)",
      }}
    >
      {/* ── header ── */}
      <header
        style={{
          marginBottom: 14,
          display: "flex",
          alignItems: "baseline",
          justifyContent: "space-between",
          gap: 16,
          flexWrap: "wrap",
        }}
      >
        <div>
          <h1
            style={{
              fontSize: 22,
              fontWeight: 600,
              color: "var(--text-strong)",
              margin: 0,
              letterSpacing: "-0.015em",
            }}
          >
            待确认意见
          </h1>
          <p
            style={{
              fontSize: 13,
              color: "var(--text-muted)",
              marginTop: 4,
            }}
          >
            {stats.total === 0
              ? "本次评审没有发现问题"
              : "左侧对照 PRD 原文,右侧逐条处理每条意见"}
          </p>
        </div>
        {stats.total > 0 && (
          <div
            style={{
              display: "flex",
              gap: 6,
              alignItems: "center",
              flexWrap: "wrap",
            }}
          >
            <KeymapBar
              items={[
                { keys: ["j"], label: "下一条" },
                { keys: ["k"], label: "上一条" },
                { keys: ["y"], label: "采纳" },
                { keys: ["n"], label: "驳回" },
                { keys: ["e"], label: "改写" },
              ]}
            />
          </div>
        )}
      </header>

      {/* ── 双栏工作台:左 PRD 原文 / 右 意见列表 ── */}
      <div
        className="pecker-phase3-grid"
        style={{
          display: "grid",
          gridTemplateColumns:
            stats.total === 0 ? "1fr" : "minmax(0, 1fr) minmax(0, 1.1fr)",
          gap: 16,
          minHeight: "calc(100vh - 280px)",
          alignItems: "start",
        }}
      >
        {stats.total > 0 && (
          <div
            className="pecker-phase3-doc-wrap"
            style={{
              position: "sticky",
              top: 16,
              maxHeight: "calc(100vh - 200px)",
              display: "flex",
              flexDirection: "column",
              minHeight: 0,
            }}
          >
            {docColumn}
          </div>
        )}
        {commentColumn}
      </div>

      {/* ── sticky 批量操作栏(底部) ── */}
      {stats.total > 0 && (
        <div
          className="pecker-phase3-batchbar"
          style={{
            position: "fixed",
            bottom: 0,
            left: 0,
            right: 0,
            zIndex: 30,
            background: "var(--surface-raised)",
            borderTop: "1px solid var(--border-default)",
            boxShadow: "var(--shadow-sm)",
            padding: "10px 24px",
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            gap: 12,
            flexWrap: "wrap",
          }}
        >
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 16,
              flexWrap: "wrap",
              fontSize: 13,
              color: "var(--text-muted)",
            }}
          >
            <BatchStat
              label="已采纳"
              value={stats.accept}
              tone="done"
            />
            <BatchStat
              label="已驳回"
              value={stats.reject}
            />
            <BatchStat
              label="待处理"
              value={stats.pending}
              tone="warn"
            />
            <span
              style={{
                fontSize: 12,
                color: "var(--text-faint)",
                fontVariantNumeric: "tabular-nums",
              }}
            >
              共 {stats.decided} / {stats.total} 条已决
            </span>
          </div>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            <button
              type="button"
              onClick={() => setPhase(2)}
              disabled={confirmMutation.isPending}
              style={
                confirmMutation.isPending ? btnGhostDisabledStyle : btnGhostStyle
              }
            >
              ← 返回上一步
            </button>
            <button
              type="button"
              onClick={() => confirmMutation.mutate()}
              disabled={confirmDisabled}
              style={
                confirmDisabled
                  ? btnPrimaryDisabledStyle
                  : btnPrimaryStyle
              }
            >
              {confirmMutation.isPending
                ? "生成中…"
                : goshawkPatchPending
                  ? "终审补充中"
                : `导出报告（${stats.decided}/${stats.total}）`}
            </button>
          </div>
        </div>
      )}

      {/* ── 移动端浮动按钮:展开评论抽屉 ── */}
      {stats.total > 0 && (
        <button
          type="button"
          className="pecker-phase3-drawer-fab"
          onClick={() => setDrawerOpen(true)}
          aria-label="展开评论列表"
          style={{
            position: "fixed",
            bottom: 76,
            right: 16,
            zIndex: 35,
            display: "none",
            alignItems: "center",
            gap: 6,
            padding: "10px 14px",
            borderRadius: "var(--r-pill)",
            border: 0,
            background: "var(--accent-500)",
            color: "var(--accent-fg)",
            fontSize: 13,
            fontWeight: 600,
            cursor: "pointer",
            boxShadow: "var(--shadow-md)",
          }}
        >
          {stats.pending > 0
            ? `还有 ${stats.pending} 条待处理`
            : "查看意见列表"}
        </button>
      )}

      {/* ── 移动端评论抽屉(底部 sheet) ── */}
      {stats.total > 0 && drawerOpen && (
        <div
          className="pecker-phase3-drawer"
          role="dialog"
          aria-label="意见列表"
          style={{
            position: "fixed",
            inset: 0,
            zIndex: 40,
            display: "none",
            flexDirection: "column",
            background: "var(--surface-canvas)",
          }}
        >
          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              padding: "10px 16px",
              borderBottom: "1px solid var(--border-default)",
              background: "var(--surface-raised)",
            }}
          >
            <span style={{ fontSize: 14, fontWeight: 600 }}>
              意见列表({stats.pending} 待处理)
            </span>
            <button
              type="button"
              onClick={() => setDrawerOpen(false)}
              style={{
                background: "transparent",
                border: 0,
                fontSize: 16,
                cursor: "pointer",
                color: "var(--text-muted)",
                padding: "4px 8px",
              }}
              aria-label="关闭"
            >
              ✕
            </button>
          </div>
          <div style={{ flex: 1, overflow: "auto", padding: "12px 16px 100px" }}>
            {commentColumn}
          </div>
        </div>
      )}
    </div>
  );
}

// ============================================================
// ItemCardV8 · 单条评审卡(CommentThread 简化版 + 嵌入 edit/reject textarea)

interface ItemCardV8Props {
  item: ReviewItem;
  focused: boolean;
  decision?: ItemDecision;
  editing: boolean;
  onFocus: () => void;
  onAccept: () => void;
  onReject: () => void;
  onEdit: () => void;
  onEditChange: (v: string) => void;
  onRejectReasonChange: (v: string) => void;
  onRejectCorrectnessChange: (reason: CorrectnessReason | "") => void;
  onRejectBusinessDecisionChange: (decision: BusinessDecision | "") => void;
  onEditDone: () => void;
}

function ItemCardV8({
  item,
  focused,
  decision,
  editing,
  onFocus,
  onAccept,
  onReject,
  onEdit,
  onEditChange,
  onRejectReasonChange,
  onRejectCorrectnessChange,
  onRejectBusinessDecisionChange,
  onEditDone,
}: ItemCardV8Props) {
  const roleKey = normalizeDimensionKey(item.dimension);
  const birdId = ROLE_TO_BIRD_ID[roleKey];
  const action = decision?.action;

  const eagleMark: "passed" | "added" | null =
    item.provenance === "meta_added"
      ? "added"
      : item.provenance === "worker" || item.provenance === "meta_dedup_kept"
        ? "passed"
        : null;

  // 从 gate_log 推断依据验证状态
  const evidenceVerification = (() => {
    const gateEntries = getGateLogEntries(item.gate_log);
    if (gateEntries.length === 0) return "unverified" as const;
    const verifyGate = gateEntries.find(
      (g) => g.type === "evidence_verify" || g.type === "evidence_validator",
    );
    if (!verifyGate) return "unverified" as const;
    return verifyGate.pass ? ("verified" as const) : ("failed" as const);
  })();

  const lowConf =
    typeof item.confidence === "number" && item.confidence < 0.7;
  const evidenceFailed = evidenceVerification === "failed";
  // 验证失败或低置信度且未决策时,默认弱化(让 PM 不会被噪音干扰)
  const fadedByQuality =
    !action && (lowConf || evidenceFailed);
  const accepted =
    action === "accept" ? true : action === "reject" ? false : undefined;
  const pmExplanation = explainReviewItemForPm(item);

  return (
    <article
      data-item-id={item.id}
      onClick={onFocus}
      style={{
        background: focused
          ? "color-mix(in oklch, var(--accent-500) 6%, var(--surface-raised))"
          : "var(--surface-raised)",
        border: `1px solid ${
          focused
            ? "color-mix(in oklch, var(--accent-500) 35%, var(--border-default))"
            : "var(--border-default)"
        }`,
        borderLeft: focused
          ? "3px solid var(--accent-500)"
          : "1px solid var(--border-default)",
        borderRadius: "var(--r-4)",
        padding: "12px 14px",
        display: "flex",
        flexDirection: "column",
        gap: 10,
        opacity:
          action === "reject" ? 0.55 : fadedByQuality && !focused ? 0.7 : 1,
        cursor: "default",
        transition: "border-color var(--dur-fast) var(--ease-out)",
      }}
    >
      {/* top row · BirdLabel(色点 + 文字)代替原 sm/md 头像 */}
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <BirdLabel id={birdId} size="md" />
        <div style={{ flex: 1, minWidth: 0 }}>
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 6,
              flexWrap: "wrap",
            }}
          >
            {item.severity && <SeverityChip severity={item.severity} />}
            {eagleMark && <EagleMark kind={eagleMark} />}
            {action === "accept" && <DecisionChip kind="accept" />}
            {action === "reject" && <DecisionChip kind="reject" />}
            {action === "edit" && <DecisionChip kind="edit" />}
            {item.pinned && <PinChip />}
          </div>
        </div>
        <span
          title={`意见编号 · ${item.id}`}
          style={{
            fontSize: 10,
            fontFamily: "var(--font-mono)",
            color: "var(--text-faint)",
            fontVariantNumeric: "tabular-nums",
            opacity: 0.55,
          }}
        >
          {item.id.slice(0, 6)}
        </span>
      </div>

      {/* 问题 */}
      <div
        style={{
          fontSize: 14,
          fontWeight: 500,
          color: "var(--text-strong)",
          lineHeight: 1.5,
          textDecoration: action === "reject" ? "line-through" : undefined,
        }}
      >
        {item.problem ?? "(无描述)"}
      </div>

      <div
        style={{
          border: "1px solid var(--border-subtle)",
          background: pmExplanation.is_engineering_context
            ? "color-mix(in oklch, var(--status-warn-bg) 55%, var(--surface-subtle))"
            : "var(--surface-subtle)",
          borderRadius: "var(--r-3)",
          padding: "9px 10px",
          display: "grid",
          gap: 6,
          fontSize: 12,
          lineHeight: 1.55,
          color: "var(--text-default)",
        }}
      >
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 8,
            flexWrap: "wrap",
          }}
        >
          <span
            style={{
              fontWeight: 700,
              color: "var(--text-strong)",
            }}
          >
            PM 要判断
          </span>
          <span
            style={{
              padding: "1px 6px",
              borderRadius: "var(--r-pill)",
              background: pmExplanation.is_engineering_context
                ? "var(--status-warn-bg)"
                : "var(--accent-50)",
              color: pmExplanation.is_engineering_context
                ? "var(--status-warn-fg)"
                : "var(--accent-700)",
              fontWeight: 600,
              fontSize: 11,
            }}
          >
            {pmExplanation.detail_label}
          </span>
        </div>
        <div style={{ color: "var(--text-strong)", fontWeight: 600 }}>
          {pmExplanation.plain_language_summary}
        </div>
        <div>{pmExplanation.pm_question}</div>
        <div style={{ color: "var(--text-muted)" }}>
          {pmExplanation.suggested_next_step}
        </div>
      </div>

      {/* 建议 */}
      {item.suggestion && (
        <div
          style={{
            fontSize: 13,
            color: "var(--text-default)",
            lineHeight: 1.6,
          }}
        >
          <span
            style={{
              fontWeight: 600,
              color: "var(--accent-600)",
              marginRight: 4,
            }}
          >
            建议
          </span>
          {item.suggestion}
        </div>
      )}

      {/* 依据 · harness 增量 P0-② */}
      {item.evidence && (
        <EvidenceBlock
          quote={item.evidence}
          source={item.location ?? "(未标注位置)"}
          verification={evidenceVerification}
        />
      )}

      {/* 主指标:可信度 + 多方向引用(PM 第一眼判断这条意见是否可信) */}
      <div
        style={{
          display: "flex",
          flexWrap: "wrap",
          alignItems: "center",
          gap: 10,
          fontSize: 12,
          color: "var(--text-muted)",
        }}
      >
        {typeof item.confidence === "number" && (
          <ConfidenceBadge value={item.confidence} />
        )}
        {item.cited_by_workers && item.cited_by_workers.length > 1 && (
          <span
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 4,
              fontSize: 11,
              color: "var(--text-muted)",
            }}
            title="多个检查方向都提到这条意见"
          >
            {item.cited_by_workers.length} 个方向同时提出
          </span>
        )}
        {getGateLogEntries(item.gate_log).length > 0 && (
          <details style={{ marginLeft: "auto" }}>
            <summary
              style={{
                fontSize: 11,
                color: "var(--text-faint)",
                cursor: "pointer",
                userSelect: "none",
                listStyle: "none",
              }}
            >
              检查详情
            </summary>
            <div
              style={{
                marginTop: 6,
                fontSize: 10,
                color: "var(--text-faint)",
                fontVariantNumeric: "tabular-nums",
                display: "flex",
                gap: 10,
                flexWrap: "wrap",
              }}
            >
              {(() => {
                const gateEntries = getGateLogEntries(item.gate_log);
                const passed = gateEntries.filter((g) => g.pass).length;
                return (
                  <>
                    <span title="该意见经过的检查项 / 总检查项">
                      检查通过 {passed}/{gateEntries.length}
                    </span>
                    {typeof item.confidence === "number" && (
                      <span>可信度 {item.confidence.toFixed(2)}</span>
                    )}
                  </>
                );
              })()}
            </div>
          </details>
        )}
      </div>

      {/* actions */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 8,
          marginTop: 2,
          flexWrap: "wrap",
        }}
      >
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
          <button
            type="button"
            style={btnAcceptStyle(accepted === true)}
            disabled={accepted === true}
            onClick={onAccept}
          >
            采纳
          </button>
          <button
            type="button"
            style={btnRejectStyle(accepted === false)}
            disabled={accepted === false}
            onClick={onReject}
          >
            驳回
          </button>
          <button type="button" style={btnEditStyle(editing)} onClick={onEdit}>
            改写
          </button>
          <CopySuggestionBtn item={item} />
        </div>
        <div
          className="pecker-shortcut-hints"
          style={{ display: "flex", gap: 10, alignItems: "center" }}
        >
          <ShortcutHint keys={["y"]} label="采纳" />
          <ShortcutHint keys={["n"]} label="驳回" />
          <ShortcutHint keys={["e"]} label="改写" />
        </div>
      </div>

      {/* edit 态 textarea */}
      {action === "edit" && editing && (
        <div style={{ marginTop: 2 }}>
          <textarea
            autoFocus
            rows={3}
            value={decision?.edited_problem ?? ""}
            onChange={(e) => onEditChange(e.target.value)}
            onBlur={onEditDone}
            placeholder="改写后的问题描述……"
            style={editTextareaStyle}
          />
        </div>
      )}

      {/* reject 原因 — correctness/business 二维拆分 + 可选自由文本备注 */}
      {action === "reject" && (
        <div
          style={{
            marginTop: 2,
            display: "flex",
            flexDirection: "column",
            gap: 8,
            padding: "8px 10px",
            background: "var(--surface-sunken)",
            borderRadius: "var(--r-3)",
            border: "1px dashed var(--border-default)",
          }}
        >
          {/* 顶栏: 判断准确性 + 业务取舍 */}
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 8,
              flexWrap: "wrap",
            }}
          >
            <span
              style={{
                fontSize: 11,
                fontFamily: "var(--font-mono)",
                color: "var(--text-faint)",
                letterSpacing: "0.04em",
                textTransform: "uppercase",
              }}
            >
              判断问题
            </span>
            <select
              value={decision?.correctness_reason ?? ""}
              onChange={(e) =>
                onRejectCorrectnessChange(e.target.value as CorrectnessReason | "")
              }
              style={rejectCategorySelectStyle}
              title={
                decision?.correctness_reason
                  ? CORRECTNESS_REASONS.find(
                      (c) => c.value === decision.correctness_reason,
                    )?.hint ?? ""
                  : "AI 判断成立时留空,只记录业务取舍"
              }
            >
              <option value="">AI 判断成立</option>
              {CORRECTNESS_REASONS.map((cat) => (
                <option key={cat.value} value={cat.value}>
                  {cat.label}
                </option>
              ))}
            </select>

            <span
              style={{
                fontSize: 11,
                fontFamily: "var(--font-mono)",
                color: "var(--text-faint)",
                letterSpacing: "0.04em",
                textTransform: "uppercase",
              }}
            >
              业务处理
            </span>
            <select
              value={decision?.business_decision ?? ""}
              onChange={(e) =>
                onRejectBusinessDecisionChange(e.target.value as BusinessDecision | "")
              }
              style={rejectCategorySelectStyle}
              title={
                decision?.business_decision
                  ? BUSINESS_DECISIONS.find(
                      (c) => c.value === decision.business_decision,
                    )?.hint ?? ""
                  : "AI 判断错误时可留空"
              }
            >
              <option value="">不记录业务取舍</option>
              {BUSINESS_DECISIONS.map((cat) => (
                <option key={cat.value} value={cat.value}>
                  {cat.label}
                </option>
              ))}
            </select>
          </div>

          {/* 自由文本备注 (对应后端 reason_note, 可选) */}
          <textarea
            rows={2}
            value={decision?.reason ?? ""}
            onChange={(e) => onRejectReasonChange(e.target.value)}
            placeholder="备注(可选)— 例如规则太严的具体场景, 帮助后续校准评审规则"
            style={rejectTextareaStyle}
          />
        </div>
      )}
    </article>
  );
}

// ============================================================
// small subcomponents

interface TabBtnProps {
  active: boolean;
  onClick: () => void;
  label: string;
  sublabel?: string;
  birdId?: BirdId;
  count: number;
}

function TabBtn({ active, onClick, label, sublabel, birdId, count }: TabBtnProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      style={{
        display: "flex",
        alignItems: "center",
        gap: 6,
        padding: "6px 12px",
        borderRadius: "var(--r-3)",
        border: `1px solid ${
          active ? "var(--accent-500)" : "var(--border-default)"
        }`,
        background: active ? "var(--accent-50)" : "var(--surface-raised)",
        color: active ? "var(--accent-700)" : "var(--text-default)",
        fontSize: 12,
        fontWeight: 500,
        cursor: "pointer",
        fontFamily: "var(--font-sans)",
        transition: "all var(--dur-fast) var(--ease-out)",
      }}
      title={sublabel}
    >
      {birdId && (
        <span
          aria-hidden
          style={{
            width: 6,
            height: 6,
            borderRadius: "50%",
            background: `var(--bird-${birdId})`,
            flexShrink: 0,
          }}
        />
      )}
      <span>{label}</span>
      <span
        style={{
          fontSize: 11,
          color: active ? "var(--accent-600)" : "var(--text-muted)",
          fontVariantNumeric: "tabular-nums",
        }}
      >
        {count}
      </span>
    </button>
  );
}

function DecisionChip({ kind }: { kind: "accept" | "reject" | "edit" }) {
  const map = {
    accept: {
      label: "已采纳",
      bg: "var(--status-done-bg)",
      fg: "var(--status-done-fg)",
    },
    reject: {
      label: "已驳回",
      bg: "var(--neutral-100)",
      fg: "var(--text-muted)",
    },
    edit: {
      label: "已改写",
      bg: "var(--status-warn-bg)",
      fg: "var(--status-warn-fg)",
    },
  } as const;
  const tok = map[kind];
  return (
    <span
      style={{
        fontSize: 10,
        padding: "1px 6px",
        borderRadius: "var(--r-2)",
        background: tok.bg,
        color: tok.fg,
        fontWeight: 600,
      }}
    >
      {tok.label}
    </span>
  );
}

function SeverityChip({ severity }: { severity: string }) {
  const tone =
    severity === "must"
      ? {
          bg: "var(--status-failed-bg)",
          fg: "var(--status-failed-fg)",
          label: "必须修",
        }
      : severity === "should"
        ? {
            bg: "var(--status-warn-bg)",
            fg: "var(--status-warn-fg)",
            label: "建议修",
          }
        : {
            bg: "var(--neutral-100)",
            fg: "var(--text-muted)",
            label: severity,
          };
  return (
    <span
      title={`严重度 · ${severity}`}
      style={{
        fontSize: 10,
        padding: "1px 6px",
        borderRadius: "var(--r-2)",
        background: tone.bg,
        color: tone.fg,
        fontWeight: 600,
      }}
    >
      {tone.label}
    </span>
  );
}

function PinChip() {
  return (
    <span
      title="本次收口后保留的重点意见"
      style={{
        fontSize: 10,
        padding: "1px 6px",
        borderRadius: "var(--r-2)",
        background: "var(--accent-50)",
        color: "var(--accent-700)",
        fontWeight: 600,
      }}
    >
      重点
    </span>
  );
}

function CopySuggestionBtn({ item }: { item: ReviewItem }) {
  const [copied, setCopied] = useState(false);
  const text = (() => {
    const parts: string[] = [];
    if (item.problem) parts.push(`【问题】${item.problem}`);
    if (item.suggestion) parts.push(`【建议】${item.suggestion}`);
    if (item.evidence) parts.push(`【依据】${item.evidence}`);
    if (item.location) parts.push(`【位置】${item.location}`);
    return parts.join("\n");
  })();
  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      toast.success("已复制建议到剪贴板");
      setTimeout(() => setCopied(false), 1500);
    } catch {
      toast.error("复制失败,请手动选中文本");
    }
  };
  return (
    <button
      type="button"
      onClick={handleCopy}
      title="复制问题 + 建议 + 依据,可直接粘回 PRD"
      style={{
        padding: "5px 12px",
        border: "1px solid var(--border-default)",
        borderRadius: "var(--r-3)",
        background: copied ? "var(--status-done-bg)" : "var(--surface-raised)",
        color: copied ? "var(--status-done-fg)" : "var(--text-muted)",
        fontSize: 12,
        fontWeight: 500,
        cursor: "pointer",
        fontFamily: "var(--font-sans)",
      }}
    >
      {copied ? "已复制" : "复制建议"}
    </button>
  );
}

function ConfidenceBadge({ value }: { value: number }) {
  // 高 ≥ 0.85 / 中 0.7-0.85 / 低 < 0.7
  const tier =
    value >= 0.85 ? "high" : value >= 0.7 ? "mid" : "low";
  const map = {
    high: {
      bg: "var(--status-done-bg)",
      fg: "var(--status-done-fg)",
      label: "依据充分",
    },
    mid: {
      bg: "var(--neutral-100)",
      fg: "var(--text-default)",
      label: "可参考",
    },
    low: {
      bg: "var(--status-warn-bg)",
      fg: "var(--status-warn-fg)",
      label: "依据不足",
    },
  } as const;
  const tok = map[tier];
  return (
    <span
      title={`可信度 ${value.toFixed(2)} · 数值越高越可信`}
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 4,
        padding: "2px 8px",
        borderRadius: "var(--r-pill)",
        background: tok.bg,
        color: tok.fg,
        fontSize: 11,
        fontWeight: 600,
      }}
    >
      {tok.label}
    </span>
  );
}

// ============================================================
// styles

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

const btnGhostStyle: React.CSSProperties = {
  height: 34,
  padding: "0 10px",
  border: 0,
  borderRadius: "var(--r-3)",
  background: "transparent",
  color: "var(--text-muted)",
  fontSize: 13,
  fontWeight: 500,
  cursor: "pointer",
  fontFamily: "var(--font-sans)",
};

const btnGhostDisabledStyle: React.CSSProperties = {
  ...btnGhostStyle,
  opacity: 0.5,
  cursor: "not-allowed",
};

const btnAcceptStyle = (active: boolean): React.CSSProperties => ({
  padding: "5px 12px",
  border: 0,
  borderRadius: "var(--r-3)",
  background: active ? "var(--status-done-dot)" : "var(--accent-500)",
  color: "var(--accent-fg)",
  fontSize: 12,
  fontWeight: 600,
  cursor: active ? "default" : "pointer",
  fontFamily: "var(--font-sans)",
  opacity: active ? 0.9 : 1,
});

const btnRejectStyle = (active: boolean): React.CSSProperties => ({
  padding: "5px 12px",
  border: `1px solid ${active ? "var(--status-failed-dot)" : "var(--border-default)"}`,
  borderRadius: "var(--r-3)",
  background: active ? "var(--status-failed-bg)" : "var(--surface-raised)",
  color: active ? "var(--status-failed-fg)" : "var(--text-default)",
  fontSize: 12,
  fontWeight: 500,
  cursor: active ? "default" : "pointer",
  fontFamily: "var(--font-sans)",
});

const btnEditStyle = (active: boolean): React.CSSProperties => ({
  padding: "5px 12px",
  border: `1px solid ${active ? "var(--status-warn-dot)" : "var(--border-default)"}`,
  borderRadius: "var(--r-3)",
  background: active ? "var(--status-warn-bg)" : "var(--surface-raised)",
  color: active ? "var(--status-warn-fg)" : "var(--text-muted)",
  fontSize: 12,
  fontWeight: 500,
  cursor: "pointer",
  fontFamily: "var(--font-sans)",
});

const editTextareaStyle: React.CSSProperties = {
  width: "100%",
  resize: "vertical",
  border: "1px solid var(--status-warn-dot)",
  borderRadius: "var(--r-3)",
  background: "var(--surface-raised)",
  padding: "8px 12px",
  fontFamily: "var(--font-sans)",
  fontSize: 13,
  lineHeight: 1.6,
  color: "var(--text-default)",
  outline: "none",
};

const rejectTextareaStyle: React.CSSProperties = {
  width: "100%",
  resize: "vertical",
  border: "1px solid var(--border-subtle)",
  borderRadius: "var(--r-2)",
  background: "var(--surface-raised)",
  padding: "6px 10px",
  fontFamily: "var(--font-sans)",
  fontSize: 12,
  lineHeight: 1.55,
  color: "var(--text-default)",
  outline: "none",
};

const rejectCategorySelectStyle: React.CSSProperties = {
  flex: 1,
  minWidth: 200,
  maxWidth: 360,
  padding: "5px 10px",
  borderRadius: "var(--r-2)",
  border: "1px solid var(--border-default)",
  background: "var(--surface-raised)",
  color: "var(--text-default)",
  fontSize: 12,
  fontFamily: "var(--font-sans)",
  cursor: "pointer",
  outline: "none",
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

// ============================================================
// 辅助:在 PRD 原文里高亮当前选中意见引用的位置。

function renderPrdDocument(
  prd: string,
  match: PrdAnchorMatch | null,
): React.ReactNode {
  let offset = 0;
  return (
    <>
      {prd.split(/\r?\n/).map((line, index) => {
        const start = offset;
        offset += line.length + 1;
        return (
          <PrdLine
            key={`${index}-${start}`}
            line={line}
            lineNo={index + 1}
            start={start}
            match={match}
          />
        );
      })}
    </>
  );
}

function PrdLine({
  line,
  lineNo,
  start,
  match,
}: {
  line: string;
  lineNo: number;
  start: number;
  match: PrdAnchorMatch | null;
}) {
  const trimmed = line.trim();
  const heading = trimmed.match(/^(#{1,6})\s+(.+)$/);
  const bullet = trimmed.match(/^([-*+]|\d+[.)])\s+(.+)$/);
  const isEmpty = trimmed.length === 0;
  const end = start + line.length;
  const overlaps = Boolean(match && match.end >= start && match.start <= end);

  const lineStyle: React.CSSProperties = {
    display: "grid",
    gridTemplateColumns: "40px minmax(0, 1fr)",
    gap: 10,
    alignItems: "start",
    minHeight: isEmpty ? 10 : 24,
    padding: heading ? "10px 0 4px" : "2px 0",
    borderRadius: "var(--r-2)",
    background: overlaps
      ? "color-mix(in oklch, var(--accent-500) 6%, transparent)"
      : "transparent",
  };
  const numberStyle: React.CSSProperties = {
    color: overlaps ? "var(--accent-700)" : "var(--text-faint)",
    fontSize: 11,
    lineHeight: isEmpty ? "10px" : "24px",
    textAlign: "right",
    userSelect: "none",
    fontVariantNumeric: "tabular-nums",
  };

  if (isEmpty) {
    return (
      <div style={lineStyle}>
        <span style={numberStyle}>{lineNo}</span>
        <span aria-hidden="true" />
      </div>
    );
  }

  let content: React.ReactNode = renderLineWithAnchor(line, start, match);
  let contentStyle: React.CSSProperties = {
    whiteSpace: "pre-wrap",
    wordBreak: "break-word",
  };

  if (heading) {
    const title = heading[2] ?? line;
    const level = heading[1]?.length ?? 1;
    content = renderLineWithAnchor(title, start + line.indexOf(title), match);
    contentStyle = {
      ...contentStyle,
      fontSize: level <= 2 ? 17 : 15,
      fontWeight: 700,
      color: "var(--text-strong)",
      lineHeight: 1.45,
    };
  } else if (bullet) {
    const body = bullet[2] ?? line;
    content = (
      <span>
        <span style={{ color: "var(--text-faint)", marginRight: 6 }}>
          {bullet[1]}
        </span>
        {renderLineWithAnchor(body, start + line.indexOf(body), match)}
      </span>
    );
  }

  return (
    <div style={lineStyle}>
      <span style={numberStyle}>{lineNo}</span>
      <div style={contentStyle}>{content}</div>
    </div>
  );
}

function renderLineWithAnchor(
  text: string,
  absoluteStart: number,
  match: PrdAnchorMatch | null,
): React.ReactNode {
  if (!match) return text;
  const lineStart = absoluteStart;
  const lineEnd = absoluteStart + text.length;
  const hitStart = Math.max(match.start, lineStart);
  const hitEnd = Math.min(match.end, lineEnd);
  if (hitStart >= hitEnd) return text;

  const localStart = hitStart - lineStart;
  const localEnd = hitEnd - lineStart;
  return (
    <>
      {text.slice(0, localStart)}
      <mark
        style={{
          background:
            "color-mix(in oklch, var(--accent-500) 22%, transparent)",
          borderBottom: "2px solid var(--accent-500)",
          padding: "0 2px",
          color: "inherit",
        }}
      >
        {text.slice(localStart, localEnd)}
      </mark>
      {text.slice(localEnd)}
    </>
  );
}

// ============================================================
// 严重度过滤按钮 + 批量统计 pill

function SevFilterBtn({
  active,
  onClick,
  label,
  count,
  tone,
}: {
  active: boolean;
  onClick: () => void;
  label: string;
  count: number;
  tone?: "fail" | "warn";
}) {
  const accentBg =
    tone === "fail"
      ? "var(--status-failed-bg)"
      : tone === "warn"
        ? "var(--status-warn-bg)"
        : "var(--accent-50)";
  const accentFg =
    tone === "fail"
      ? "var(--status-failed-fg)"
      : tone === "warn"
        ? "var(--status-warn-fg)"
        : "var(--accent-700)";
  return (
    <button
      type="button"
      onClick={onClick}
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 6,
        padding: "4px 10px",
        borderRadius: "var(--r-pill)",
        border: `1px solid ${active ? accentFg : "var(--border-default)"}`,
        background: active ? accentBg : "var(--surface-raised)",
        color: active ? accentFg : "var(--text-default)",
        fontSize: 12,
        fontWeight: active ? 600 : 500,
        cursor: "pointer",
        fontFamily: "var(--font-sans)",
      }}
    >
      <span>{label}</span>
      <span
        style={{
          fontSize: 11,
          color: active ? accentFg : "var(--text-muted)",
          fontVariantNumeric: "tabular-nums",
        }}
      >
        {count}
      </span>
    </button>
  );
}

function BatchStat({
  label,
  value,
  tone,
}: {
  label: string;
  value: number;
  tone?: "done" | "warn";
}) {
  const fg =
    tone === "done"
      ? "var(--status-done-fg)"
      : tone === "warn"
        ? "var(--status-warn-fg)"
        : "var(--text-default)";
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "baseline",
        gap: 6,
      }}
    >
      <span
        style={{
          fontSize: 18,
          fontWeight: 600,
          color: fg,
          fontVariantNumeric: "tabular-nums",
          lineHeight: 1,
        }}
      >
        {value}
      </span>
      <span style={{ fontSize: 12, color: "var(--text-muted)" }}>{label}</span>
    </span>
  );
}

// ============================================================
// EmptyClearState · "本次评审没有发现需要处理的问题" 庆祝时刻
//
// 用手绘 clear-state.png(啄木鸟趴在文档上 + 3 个 jade 对勾),情绪曲线
// 系列里"全部通过"那张。PNG 缺失时降级到纯文本(不影响功能)。

function EmptyClearState() {
  return (
    <div
      style={{
        padding: "40px 24px",
        textAlign: "center",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        gap: 8,
      }}
    >
      <img
        src="/illustrations/clear-state.png"
        alt=""
        aria-hidden
        width={280}
        height={188}
        style={{
          width: 280,
          height: "auto",
          maxWidth: "100%",
          marginBottom: 8,
          opacity: 0.95,
          userSelect: "none",
        }}
        onError={(e) => {
          (e.currentTarget as HTMLImageElement).style.display = "none";
        }}
      />
      <div
        style={{
          fontSize: 16,
          fontWeight: 600,
          color: "var(--text-strong)",
        }}
      >
        本次评审没有发现需要处理的问题
      </div>
      <div
        style={{
          fontSize: 13,
          color: "var(--text-muted)",
          lineHeight: 1.6,
          maxWidth: 340,
          margin: "0 auto",
        }}
      >
        四个检查方向都未提出意见,也没有补充项。
        <br />
        PRD 可以直接进入研发评审。
      </div>
    </div>
  );
}
