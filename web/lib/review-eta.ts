import type { ReviewMode } from "@/lib/api";

export interface ReviewEtaInput {
  mode?: ReviewMode | string;
  prdContent?: string;
  rawMaterials?: readonly string[];
  wikiPageCount?: number;
}

const WIKI_PAGE_CONTEXT_WEIGHT = 1200;
const LONG_REVIEW_CHARS = 60_000;
const VERY_LONG_REVIEW_CHARS = 120_000;

export function reviewInputChars(input: ReviewEtaInput): number {
  const prdChars = input.prdContent?.length ?? 0;
  const rawChars =
    input.rawMaterials?.reduce((sum, material) => sum + material.length, 0) ??
    0;
  const workspaceChars = Math.max(0, input.wikiPageCount ?? 0) * WIKI_PAGE_CONTEXT_WEIGHT;
  return prdChars + rawChars + workspaceChars;
}

export function estimateReviewEtaLabel(input: ReviewEtaInput): string {
  const chars = reviewInputChars(input);

  if (input.mode === "quick") {
    if (chars >= LONG_REVIEW_CHARS) return "约 6-10 分钟";
    return "约 5 分钟";
  }

  if (chars >= VERY_LONG_REVIEW_CHARS) return "约 10-15 分钟";
  if (chars >= LONG_REVIEW_CHARS) return "约 6-10 分钟";
  return "通常 3-8 分钟";
}

export function estimateReviewEtaHint(input: ReviewEtaInput): string {
  const chars = reviewInputChars(input);
  if (chars >= LONG_REVIEW_CHARS) {
    return "材料较长或多人同时使用时可能排队，刷新或断网后可继续等待";
  }
  return "材料较长时会更久；多人同时使用时可能排队；刷新或断网后可继续等待";
}

export function reviewEtaSoftLimitSeconds(input: ReviewEtaInput): number {
  const chars = reviewInputChars(input);
  if (chars >= VERY_LONG_REVIEW_CHARS) return 900;
  if (chars >= LONG_REVIEW_CHARS) return 600;
  return input.mode === "quick" ? 360 : 480;
}
