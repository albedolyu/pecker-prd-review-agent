import { afterEach, describe, expect, it, vi } from "vitest";
import { readFileSync } from "node:fs";
import { join } from "node:path";

import { answerReviewAssistantQuestionAsync } from "@/lib/review-assistant";
import type { ReviewResult } from "@/lib/api";

const goldenPath = join(
  __dirname,
  "..",
  "..",
  "eval",
  "golden",
  "review_assistant_customer_needs.json",
);

const golden = JSON.parse(readFileSync(goldenPath, "utf-8")) as GoldenSet;
const originalFetch = global.fetch;

interface GoldenSet {
  frontend_cases: FrontendCase[];
}

interface FrontendCase {
  id: string;
  question: string;
  context: {
    phase: 0 | 1 | 2 | 3 | 4;
    raw_materials: string[];
    review_items_count?: number;
  };
  mock_backend?: {
    answer: string;
  };
  expect: {
    backend_call: boolean;
    include_fact_layer?: boolean;
    must_include: string[];
    must_not_include?: string[];
  };
}

function fakeReviewResult(itemCount: number | undefined): ReviewResult | null {
  if (!itemCount) return null;
  return {
    review_id: "golden-review",
    created_at: 0,
    reviewer: "pm-golden",
    workspace: "workspace-golden",
    prd_name: "黄金测试 PRD",
    mode: "standard",
    items: Array.from({ length: itemCount }, (_, index) => ({
      id: `G-${index + 1}`,
      dimension: "quality",
      problem: `golden issue ${index + 1}`,
    })),
    workers: [],
    usage: {},
    goshawk_summary: null,
    signature: "golden-signature",
  };
}

describe("review assistant golden eval: customer needs", () => {
  afterEach(() => {
    global.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  for (const item of golden.frontend_cases) {
    it(`${item.id} answers the PM need`, async () => {
      const fetchMock = vi.fn().mockImplementation(async () => {
        if (!item.mock_backend) {
          throw new Error(`Unexpected backend call in ${item.id}`);
        }
        return {
          ok: true,
          status: 200,
          json: async () => ({
            answer: item.mock_backend?.answer,
            hits: [],
            include_fact_layer: item.expect.include_fact_layer ?? false,
          }),
        };
      });
      global.fetch = fetchMock as unknown as typeof fetch;

      const answer = await answerReviewAssistantQuestionAsync(item.question, {
        phase: item.context.phase,
        rawMaterials: item.context.raw_materials,
        reviewResult: fakeReviewResult(item.context.review_items_count),
      });

      for (const phrase of item.expect.must_include) {
        expect(answer, `${item.id} should include ${phrase}`).toContain(phrase);
      }
      for (const phrase of item.expect.must_not_include ?? []) {
        expect(answer, `${item.id} should not include ${phrase}`).not.toContain(phrase);
      }

      if (item.expect.backend_call) {
        expect(fetchMock, `${item.id} should call evidence backend`).toHaveBeenCalledTimes(1);
        const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
        const body = JSON.parse(String(init.body ?? "{}")) as { include_fact_layer?: boolean };
        expect(body.include_fact_layer).toBe(item.expect.include_fact_layer);
      } else {
        expect(fetchMock, `${item.id} should stay local`).not.toHaveBeenCalled();
      }
    });
  }
});
