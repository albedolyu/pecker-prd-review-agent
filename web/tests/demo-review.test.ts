import { describe, expect, it } from "vitest";

import {
  DEMO_DECISIONS,
  DEMO_PRECHECK,
  DEMO_PRD_CONTENT,
  DEMO_REVIEW_RESULT,
  DEMO_REPORT_MARKDOWN,
  DEMO_WIKI_PAGES,
} from "@/lib/demo-review";
import { buildPmFriendlySnapshot } from "@/lib/pm-friendly";

describe("demo review fixtures", () => {
  it("provides a complete no-backend review flow fixture", () => {
    expect(DEMO_PRD_CONTENT).toContain("#");
    expect(DEMO_PRECHECK.strong.length).toBeGreaterThan(0);
    expect(DEMO_PRECHECK.gaps.length).toBeGreaterThan(0);
    expect(Object.keys(DEMO_WIKI_PAGES).length).toBeGreaterThan(0);
    expect(DEMO_REVIEW_RESULT.items.length).toBeGreaterThanOrEqual(4);
    expect(DEMO_REVIEW_RESULT.signature).toBe("demo-signature-not-for-submit");
    expect(Object.keys(DEMO_DECISIONS)).toEqual(
      DEMO_REVIEW_RESULT.items.map((item) => item.id),
    );
    expect(DEMO_REPORT_MARKDOWN).toContain("演示模式");

    const snapshot = buildPmFriendlySnapshot(DEMO_REVIEW_RESULT);
    expect(snapshot.pmSummary.total_items).toBe(DEMO_REVIEW_RESULT.items.length);
    expect(snapshot.zhiquHandoff.review_id).toBe(DEMO_REVIEW_RESULT.review_id);
  });
});
