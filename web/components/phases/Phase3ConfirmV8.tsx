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
 * - 键盘:j/k 上下 · y 接受 · n 拒绝 · e 编辑 · enter 确认生成报告
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
  ApiError,
  type ConfirmResponse,
  type ItemDecision,
  type RejectReason,
  type ReviewItem,
} from "@/lib/api";
import { BirdAvatar, type BirdId } from "@/components/birds/BirdAvatar";
import { BIRD_META } from "@/components/birds/BirdBadge";
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
  { value: "good_issue", label: "实际是好问题(手滑点错)", hint: "PM 改主意了, 不算规则锅 → EMA 正向微调" },
  { value: "false_positive", label: "误报", hint: "PRD 确实没这问题 → 规则精度差, 重惩罚" },
  { value: "known_tradeoff", label: "已知取舍, 不改", hint: "业务允许, 不改 → 弱惩罚 + 周报建议加 ignore" },
  { value: "wiki_missing", label: "知识库缺失", hint: "规则没错, 是 wiki 缺背景 → 弱惩罚 + 周报提示补 wiki" },
  { value: "rule_too_strict", label: "规则太严", hint: "规则 scope 问题 → 重惩罚 + 周报提示改写规则" },
  { value: "impl_detail", label: "实现细节, 不该 PRD 管", hint: "规则 scope 错 → 中等惩罚 + 收窄 rule" },
  { value: "model_noise", label: "模型噪音", hint: "无业务意义 → 中等惩罚, 进 prompt 迭代队列" },
];

const DEFAULT_REJECT_CATEGORY: RejectReason = "model_noise";

export function Phase3ConfirmV8() {
  const reviewResult = useReviewStore((s) => s.reviewResult);
  const decisions = useReviewStore((s) => s.decisions);
  const setDecision = useReviewStore((s) => s.setDecision);
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

  // 当前聚焦 item(给键盘导航用)
  const [focusedIdx, setFocusedIdx] = useState(0);
  // 进入 edit 态的 item id(每次只能编一条)
  const [editingId, setEditingId] = useState<string | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  // 当前 tab 下的 items(排序:pinned 优先 + 原顺序)
  const visibleItems = useMemo<ReviewItem[]>(() => {
    if (!reviewResult) return [];
    const items =
      currentTab === "all"
        ? Array.from(reviewResult.items)
        : Array.from(itemsByDim.get(currentTab) ?? []);
    return items.sort((a, b) => {
      const ap = a.pinned ? 0 : 1;
      const bp = b.pinned ? 0 : 1;
      return ap - bp;
    });
  }, [reviewResult, itemsByDim, currentTab]);

  // tab 切换时 focusedIdx 归零
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- tab 切换后重置键盘焦点,属纯派生 UI 状态
    setFocusedIdx(0);
  }, [currentTab]);

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
        `已确认 ${resp.accepted} 接受 · ${resp.edited} 改写 · ${resp.rejected} 拒绝`,
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
      setPhase(4);
    },
    onError: (e: ApiError) => {
      if (e.status === 403) {
        toast.error("签名验证失败 — 数据可能被篡改,请重新评审");
      } else {
        toast.error(`确认失败: ${e.detail ?? e.message}`);
      }
    },
  });

  // ── 快捷键动作 ──
  const focusedItem = visibleItems[focusedIdx];

  const handleAccept = useCallback(
    (itemId: string) => {
      setDecision(itemId, { action: "accept" });
      setEditingId(null);
    },
    [setDecision],
  );

  const handleReject = useCallback(
    (itemId: string) => {
      // P0 step 2: reject 进入态默认带 reason_category=model_noise (兜底, 与后端一致),
      // 让 PM 必须显式从 dropdown 选 7 选 1, 否则报告里 reason_category 留空也会被
      // ConfirmRequest validator 接受 (default model_noise) 但 EMA 信号失真 — 所以
      // dropdown 是 PM 的强 nudge, 不是 schema 强制.
      const existing = decisions[itemId];
      const reuseCat =
        existing?.action === "reject" && existing.reason_category
          ? existing.reason_category
          : DEFAULT_REJECT_CATEGORY;
      setDecision(itemId, {
        action: "reject",
        reason_category: reuseCat,
        reason: existing?.action === "reject" ? existing.reason : undefined,
      });
      setEditingId(null);
    },
    [decisions, setDecision],
  );

  const handleEdit = useCallback(
    (item: ReviewItem) => {
      const existing = decisions[item.id];
      setDecision(item.id, {
        action: "edit",
        edited_problem:
          existing?.action === "edit" && existing.edited_problem
            ? existing.edited_problem
            : (item.problem ?? ""),
      });
      setEditingId(item.id);
    },
    [decisions, setDecision],
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

  // ── 空态 guard ──
  if (!reviewResult) {
    return (
      <div style={emptyWrapStyle}>
        <h2 style={emptyTitleStyle}>没找到评审结果</h2>
        <p style={emptyDescStyle}>
          没有 Phase 2 的产出,请返回重新评审。
        </p>
        <button
          type="button"
          onClick={() => setPhase(2)}
          style={btnPrimaryStyle}
        >
          返回 Phase 2
        </button>
      </div>
    );
  }

  return (
    <div
      ref={containerRef}
      style={{
        maxWidth: 920,
        margin: "0 auto",
        padding: "28px 24px 120px", // 底部留空给 KeymapBar
        fontFamily: "var(--font-sans)",
      }}
    >
      {/* ── header ── */}
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
          逐条确认
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
            : `${stats.total} 条 · 待决 ${stats.pending} · 键盘 j/k 切换 · y/n 决策 · e 编辑`}
        </p>
      </header>

      {/* ── stat bar ── */}
      {stats.total > 0 && (
        <div style={statBarStyle}>
          <StatPill label="总计" value={stats.total} />
          <StatPill label="待决" value={stats.pending} tone="muted" />
          <StatPill label="接受" value={stats.accept} tone="done" />
          <StatPill label="驳回" value={stats.reject} tone="muted" />
          <StatPill label="改写" value={stats.edit} tone="warn" />
          <span style={{ flex: 1 }} />
          <span
            style={{
              fontSize: 11,
              fontFamily: "var(--font-mono)",
              color: "var(--text-muted)",
              fontVariantNumeric: "tabular-nums",
            }}
          >
            已决 {stats.decided} / {stats.total}
          </span>
        </div>
      )}

      {/* ── dim tabs ── */}
      {stats.total > 0 && (
        <div style={tabsStyle}>
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
                label={`${BIRD_META[birdId].label}鸟`}
                sublabel={role.responsibility}
                birdId={birdId}
                count={count}
              />
            );
          })}
        </div>
      )}

      {/* ── items list ── */}
      {stats.total > 0 && (
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            gap: 10,
            marginTop: 16,
          }}
        >
          {visibleItems.map((item, i) => (
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
                // 写自由文本备注时保留已选的 reason_category (默认 model_noise)
                const existing = decisions[item.id];
                setDecision(item.id, {
                  action: "reject",
                  reason_category:
                    existing?.action === "reject" && existing.reason_category
                      ? existing.reason_category
                      : DEFAULT_REJECT_CATEGORY,
                  reason: v,
                });
              }}
              onRejectCategoryChange={(cat) => {
                const existing = decisions[item.id];
                setDecision(item.id, {
                  action: "reject",
                  reason_category: cat,
                  reason:
                    existing?.action === "reject" ? existing.reason : undefined,
                });
              }}
              onEditDone={() => setEditingId(null)}
            />
          ))}
        </div>
      )}

      {/* ── 漏报反馈入口(harness 增量 P1⑦) ── */}
      {stats.total > 0 && (
        <div
          style={{
            marginTop: 18,
            display: "flex",
            justifyContent: "center",
          }}
        >
          <MissingReportButton
            onSubmit={(payload) => {
              // Sprint 5 接归因库接口;暂时 console log
              console.log("[harness · missing-report]", payload);
            }}
          />
        </div>
      )}

      {/* ── 底部 footer ── */}
      <footer
        style={{
          marginTop: 20,
          paddingTop: 18,
          borderTop: "1px solid var(--border-subtle)",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 12,
        }}
      >
        <button
          type="button"
          onClick={() => setPhase(2)}
          disabled={confirmMutation.isPending}
          style={
            confirmMutation.isPending ? btnGhostDisabledStyle : btnGhostStyle
          }
        >
          ← 返回 Phase 2
        </button>
        <button
          type="button"
          onClick={() => confirmMutation.mutate()}
          disabled={confirmMutation.isPending}
          style={
            confirmMutation.isPending
              ? btnPrimaryDisabledStyle
              : btnPrimaryStyle
          }
        >
          {confirmMutation.isPending ? "生成中…" : "生成报告 →"}
        </button>
      </footer>

      {/* ── 底部常驻 KeymapBar ── */}
      <div
        style={{
          position: "fixed",
          bottom: 16,
          left: "50%",
          transform: "translateX(-50%)",
          zIndex: "var(--z-toast)" as unknown as number,
          pointerEvents: "none",
        }}
      >
        <div style={{ pointerEvents: "auto" }}>
          <KeymapBar
            items={[
              { keys: ["j"], label: "下一条" },
              { keys: ["k"], label: "上一条" },
              { keys: ["y"], label: "接受" },
              { keys: ["n"], label: "驳回" },
              { keys: ["e"], label: "编辑" },
            ]}
          />
        </div>
      </div>
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
  onRejectCategoryChange: (cat: RejectReason) => void;
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
  onRejectCategoryChange,
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
    if (!item.gate_log) return "unverified" as const;
    const verifyGate = item.gate_log.find(
      (g) => g.type === "evidence_verify" || g.type === "evidence_validator",
    );
    if (!verifyGate) return "unverified" as const;
    return verifyGate.pass ? ("verified" as const) : ("failed" as const);
  })();

  const lowConf =
    typeof item.confidence === "number" && item.confidence < 0.7;
  const accepted =
    action === "accept" ? true : action === "reject" ? false : undefined;

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
        opacity: action === "reject" ? 0.55 : 1,
        cursor: "default",
        transition: "border-color var(--dur-fast) var(--ease-out)",
      }}
    >
      {/* top row */}
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <BirdAvatar id={birdId} size="md" />
        <div style={{ flex: 1, minWidth: 0 }}>
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 6,
              flexWrap: "wrap",
            }}
          >
            <span
              style={{
                fontSize: 13,
                fontWeight: 600,
                color: "var(--text-strong)",
              }}
            >
              {BIRD_META[birdId].label}鸟
            </span>
            {item.severity && <SeverityChip severity={item.severity} />}
            {eagleMark && <EagleMark kind={eagleMark} />}
            {action === "accept" && <DecisionChip kind="accept" />}
            {action === "reject" && <DecisionChip kind="reject" />}
            {action === "edit" && <DecisionChip kind="edit" />}
            {item.pinned && <PinChip />}
          </div>
        </div>
        <span
          style={{
            fontSize: 10,
            fontFamily: "var(--font-mono)",
            color: "var(--text-faint)",
            fontVariantNumeric: "tabular-nums",
          }}
        >
          {item.id.slice(0, 10)}
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

      {/* meta */}
      <div
        style={{
          display: "flex",
          flexWrap: "wrap",
          gap: "3px 12px",
          fontFamily: "var(--font-mono)",
          fontSize: 11,
          color: "var(--text-muted)",
          fontVariantNumeric: "tabular-nums",
        }}
      >
        {typeof item.confidence === "number" && (
          <MetaTag
            k="conf"
            v={item.confidence.toFixed(2)}
            emph={lowConf}
          />
        )}
        {item.cited_by_workers && item.cited_by_workers.length > 1 && (
          <MetaTag
            k="cited_by"
            v={`${item.cited_by_workers.length} workers`}
          />
        )}
        {Array.isArray(item.gate_log) && item.gate_log.length > 0 && (
          <MetaTag
            k="gate"
            v={`${item.gate_log.filter((g) => g.pass).length}/${item.gate_log.length}`}
          />
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
        }}
      >
        <div style={{ display: "flex", gap: 6 }}>
          <button
            type="button"
            style={btnAcceptStyle(accepted === true)}
            disabled={accepted === true}
            onClick={onAccept}
          >
            接受
          </button>
          <button
            type="button"
            style={btnRejectStyle(accepted === false)}
            disabled={accepted === false}
            onClick={onReject}
          >
            拒绝
          </button>
          <button type="button" style={btnEditStyle(editing)} onClick={onEdit}>
            编辑
          </button>
        </div>
        <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
          <ShortcutHint keys={["y"]} label="接受" />
          <ShortcutHint keys={["n"]} label="拒绝" />
          <ShortcutHint keys={["e"]} label="编辑" />
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

      {/* reject 原因 — 7 类下拉 (P0 step 2 必填) + 可选自由文本备注 */}
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
          {/* 顶栏: 7 类 dropdown + 当前选择提示 */}
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
              驳回原因
            </span>
            <select
              value={decision?.reason_category ?? DEFAULT_REJECT_CATEGORY}
              onChange={(e) =>
                onRejectCategoryChange(e.target.value as RejectReason)
              }
              style={rejectCategorySelectStyle}
              title={
                REJECT_CATEGORIES.find(
                  (c) =>
                    c.value ===
                    (decision?.reason_category ?? DEFAULT_REJECT_CATEGORY),
                )?.hint ?? ""
              }
            >
              {REJECT_CATEGORIES.map((cat) => (
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
            placeholder="备注(可选)— 例如规则太严的具体场景, 帮助后续 rule_lifecycle 决策"
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
      {birdId && <BirdAvatar id={birdId} size="sm" />}
      <span>{label}</span>
      <span
        style={{
          fontFamily: "var(--font-mono)",
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

function StatPill({
  label,
  value,
  tone,
}: {
  label: string;
  value: number;
  tone?: "done" | "warn" | "muted";
}) {
  const fg =
    tone === "done"
      ? "var(--status-done-fg)"
      : tone === "warn"
        ? "var(--status-warn-fg)"
        : tone === "muted"
          ? "var(--text-muted)"
          : "var(--text-strong)";
  return (
    <div
      style={{
        display: "flex",
        alignItems: "baseline",
        gap: 4,
      }}
    >
      <span
        style={{
          fontSize: 10,
          fontFamily: "var(--font-mono)",
          color: "var(--text-faint)",
          textTransform: "uppercase",
          letterSpacing: "0.08em",
        }}
      >
        {label}
      </span>
      <span
        style={{
          fontSize: 15,
          fontWeight: 600,
          color: fg,
          fontFamily: "var(--font-mono)",
          fontVariantNumeric: "tabular-nums",
        }}
      >
        {value}
      </span>
    </div>
  );
}

function DecisionChip({ kind }: { kind: "accept" | "reject" | "edit" }) {
  const map = {
    accept: {
      label: "已接受",
      bg: "var(--status-done-bg)",
      fg: "var(--status-done-fg)",
    },
    reject: {
      label: "已拒绝",
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
      ? { bg: "var(--status-failed-bg)", fg: "var(--status-failed-fg)", label: "must" }
      : severity === "should"
        ? { bg: "var(--status-warn-bg)", fg: "var(--status-warn-fg)", label: "should" }
        : { bg: "var(--neutral-100)", fg: "var(--text-muted)", label: severity };
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
        textTransform: "uppercase",
        letterSpacing: "0.04em",
      }}
    >
      {tone.label}
    </span>
  );
}

function PinChip() {
  return (
    <span
      style={{
        fontSize: 10,
        padding: "1px 6px",
        borderRadius: "var(--r-2)",
        background: "var(--accent-50)",
        color: "var(--accent-700)",
        fontWeight: 600,
      }}
    >
      pinned
    </span>
  );
}

function MetaTag({
  k,
  v,
  emph,
}: {
  k: string;
  v: string;
  emph?: boolean;
}) {
  return (
    <span
      style={{
        display: "inline-flex",
        gap: 3,
        color: emph ? "var(--status-warn-fg)" : "var(--text-muted)",
      }}
    >
      <span style={{ opacity: 0.6 }}>{k}=</span>
      <span
        style={{
          color: emph ? "var(--status-warn-fg)" : "var(--text-default)",
        }}
      >
        {v}
      </span>
    </span>
  );
}

// ============================================================
// styles

const statBarStyle: React.CSSProperties = {
  display: "flex",
  alignItems: "baseline",
  gap: 20,
  padding: "10px 14px",
  background: "var(--surface-raised)",
  border: "1px solid var(--border-default)",
  borderRadius: "var(--r-4)",
  marginBottom: 14,
};

const tabsStyle: React.CSSProperties = {
  display: "flex",
  gap: 6,
  flexWrap: "wrap",
  paddingBottom: 4,
  borderBottom: "1px solid var(--border-subtle)",
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
