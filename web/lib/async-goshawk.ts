import type { Draft, ReviewResult } from "@/lib/api";

function normalizedText(value: string | null | undefined): string {
  return (value ?? "").trim();
}

export function isAsyncGoshawkPending(result: ReviewResult | null | undefined): boolean {
  const summary = result?.goshawk_summary;
  if (!summary || typeof summary !== "object") return false;
  return (
    summary["status"] === "pending" &&
    (summary["mode"] === "async_patch" || summary["source"] === "worker_draft")
  );
}

export function shouldApplyGoshawkPatchDraft(
  current: ReviewResult | null | undefined,
  draft: Draft | null | undefined,
): boolean {
  if (!isAsyncGoshawkPending(current)) return false;
  if (!draft?.review_result) return false;
  if (draft.phase < 3) return false;

  const next = draft.review_result;
  if (next.review_id === current?.review_id) return false;
  if (isAsyncGoshawkPending(next)) return false;
  if (normalizedText(draft.workspace) !== normalizedText(current?.workspace)) return false;
  if (normalizedText(draft.prd_name) !== normalizedText(current?.prd_name)) return false;
  if (normalizedText(draft.mode) !== normalizedText(current?.mode)) return false;
  if (normalizedText(next.workspace) !== normalizedText(current?.workspace)) return false;
  if (normalizedText(next.prd_name) !== normalizedText(current?.prd_name)) return false;
  if (normalizedText(next.mode) !== normalizedText(current?.mode)) return false;

  return true;
}
