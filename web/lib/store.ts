/**
 * 啄木鸟评审 wizard 全局状态 — Zustand slice
 *
 * 覆盖 5 个 phase 的所有持久状态:
 *   Phase 0: 用户输入(reviewer/workspace/PRD 内容/mode/notes)
 *   Phase 1: precheck 结果(wiki hits)
 *   Phase 2: review 结果(Opaque Handle)
 *   Phase 3: 用户决定(accept/reject/edit)
 *   Phase 4: 报告文件列表
 *
 * 不持久化到 localStorage —— draft 持久化走后端 /api/drafts,浏览器崩溃
 * 恢复由 Phase 0 的 drafts.get 拉回。这样多 tab 不会互相覆盖。
 *
 * SSE 事件流本身**不放**在这里,由 useReviewStream hook 独立持有,
 * 评审完成后再把 result 写进 store。
 */

import { create } from "zustand";
import type {
  Draft,
  DraftPayload,
  ItemDecision,
  PrecheckResponse,
  ReviewResult,
} from "./api";

export type ReviewPhase = 0 | 1 | 2 | 3 | 4;

export type ReviewMode = "fast" | "strict";

// ============================================================
// State shape
// ============================================================

interface UserInputState {
  reviewer: string;
  workspace: string;
  prdName: string;
  prdContent: string;
  mode: ReviewMode;
  userNotes: string;
  rawMaterials: string[];
}

interface ReviewStore extends UserInputState {
  phase: ReviewPhase;

  /** Phase 1 预检结果 */
  precheckResult: PrecheckResponse | null;
  /** Phase 2 评审完成后的 Opaque Handle */
  reviewResult: ReviewResult | null;
  /** Phase 3 用户对每个 item 的决定 */
  decisions: Record<string, ItemDecision>;
  /** Phase 4 确认后后端生成的报告文件列表 */
  reportFilenames: ReadonlyArray<string>;

  // ---- actions ----
  setPhase: (phase: ReviewPhase) => void;
  setUserInput: (partial: Partial<UserInputState>) => void;
  setPrecheckResult: (r: PrecheckResponse | null) => void;
  setReviewResult: (r: ReviewResult | null) => void;
  setDecision: (itemId: string, decision: ItemDecision) => void;
  removeDecision: (itemId: string) => void;
  clearDecisions: () => void;
  setReportFilenames: (filenames: ReadonlyArray<string>) => void;

  /** 从后端返回的 Draft 恢复整个 wizard 状态 */
  hydrateFromDraft: (draft: Draft) => void;
  /** 构造 PUT /api/drafts 的 payload */
  toDraftPayload: () => DraftPayload;
  /** 重置评审相关状态(保留 reviewer 登录态) */
  resetReview: () => void;
}

// ============================================================
// Store
// ============================================================

const INITIAL_USER_INPUT: UserInputState = {
  reviewer: "",
  workspace: "",
  prdName: "",
  prdContent: "",
  mode: "strict",
  userNotes: "",
  rawMaterials: [],
};

export const useReviewStore = create<ReviewStore>((set, get) => ({
  ...INITIAL_USER_INPUT,
  phase: 0,
  precheckResult: null,
  reviewResult: null,
  decisions: {},
  reportFilenames: [],

  setPhase: (phase) => set({ phase }),

  setUserInput: (partial) => set(partial),

  setPrecheckResult: (r) => set({ precheckResult: r }),

  setReviewResult: (r) => set({ reviewResult: r }),

  setDecision: (itemId, decision) =>
    set((state) => ({
      decisions: { ...state.decisions, [itemId]: decision },
    })),

  removeDecision: (itemId) =>
    set((state) => {
      const next = { ...state.decisions };
      delete next[itemId];
      return { decisions: next };
    }),

  clearDecisions: () => set({ decisions: {} }),

  setReportFilenames: (filenames) => set({ reportFilenames: filenames }),

  hydrateFromDraft: (draft) =>
    set({
      phase: Math.max(0, Math.min(4, draft.phase)) as ReviewPhase,
      prdName: draft.prd_name,
      prdContent: draft.prd_content,
      workspace: draft.workspace,
      userNotes: draft.user_notes,
      rawMaterials: draft.raw_materials,
      reviewResult: draft.review_result,
      decisions: draft.item_decisions,
    }),

  toDraftPayload: () => {
    const s = get();
    return {
      phase: s.phase,
      prd_name: s.prdName,
      prd_content: s.prdContent,
      workspace: s.workspace,
      user_notes: s.userNotes,
      raw_materials: s.rawMaterials,
      review_result: s.reviewResult,
      item_decisions: s.decisions,
    };
  },

  resetReview: () =>
    set((state) => ({
      ...INITIAL_USER_INPUT,
      reviewer: state.reviewer, // 保留登录态
      phase: 0,
      precheckResult: null,
      reviewResult: null,
      decisions: {},
      reportFilenames: [],
    })),
}));

// ============================================================
// 选择器 — 防止 UI 重渲染范围过大
// ============================================================

export const selectPhase = (s: ReviewStore) => s.phase;
export const selectReviewer = (s: ReviewStore) => s.reviewer;
export const selectDecisionsCount = (s: ReviewStore) =>
  Object.keys(s.decisions).length;
export const selectItemsCount = (s: ReviewStore) =>
  s.reviewResult?.items.length ?? 0;
