import {
  draftsApi,
  type DraftPayload,
  type ItemDecision,
  type ReviewMode,
  type ReviewResult,
} from "@/lib/api";

export interface ReviewDraftSnapshot {
  reviewer: string;
  phase: number;
  prdName: string;
  prdContent: string;
  workspace: string;
  mode?: ReviewMode;
  userNotes: string;
  rawMaterials: string[];
  reviewResult: ReviewResult | null;
  decisions: Record<string, ItemDecision>;
  confirmedReportMarkdown: string;
}

export function buildDraftPayloadFromSnapshot(
  snapshot: ReviewDraftSnapshot,
): DraftPayload {
  return {
    phase: Math.max(0, Math.min(4, snapshot.phase)),
    prd_name: snapshot.prdName,
    prd_content: snapshot.prdContent,
    mode: snapshot.mode ?? "standard",
    raw_materials: snapshot.rawMaterials,
    user_notes: snapshot.userNotes,
    review_result: snapshot.reviewResult,
    item_decisions: snapshot.decisions,
    confirmed_report_markdown: snapshot.confirmedReportMarkdown,
    workspace: snapshot.workspace,
  };
}

export async function saveReviewDraftSnapshot(
  snapshot: ReviewDraftSnapshot,
): Promise<{ skipped: boolean; ts?: string }> {
  const reviewer = (
    snapshot.reviewer ||
    snapshot.reviewResult?.reviewer ||
    ""
  ).trim();
  if (!reviewer) return { skipped: true };
  const resp = await draftsApi.save(
    reviewer,
    buildDraftPayloadFromSnapshot(snapshot),
  );
  return { skipped: false, ts: resp.ts };
}
