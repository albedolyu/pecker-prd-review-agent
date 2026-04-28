import { afterEach, describe, expect, it } from "vitest";

import type { Draft, ReviewResult } from "@/lib/api";
import { useReviewStore } from "@/lib/store";

const reviewResult: ReviewResult = {
  review_id: "rev_test",
  created_at: 1,
  reviewer: "alice",
  workspace: "workspace-demo",
  prd_name: "demo.md",
  mode: "standard",
  items: [],
  workers: [],
  usage: {},
  goshawk_summary: null,
  signature: "sig",
};

describe("post-review report contract in store", () => {
  afterEach(() => {
    useReviewStore.setState({
      phase: 0,
      reviewer: "",
      workspace: "",
      prdName: "",
      prdContent: "",
      mode: "standard",
      userNotes: "",
      rawMaterials: [],
      precheckResult: null,
      wikiPages: {},
      reviewResult: null,
      decisions: {},
      confirmedReportMarkdown: "",
      reportFilenames: [],
    });
  });

  it("persists backend confirmed markdown in draft payload", () => {
    useReviewStore.setState({
      phase: 4,
      reviewer: "alice",
      workspace: "workspace-demo",
      prdName: "demo.md",
      prdContent: "# Demo",
      reviewResult,
      decisions: { "R-001": { action: "accept" } },
      confirmedReportMarkdown: "# 后端报告\n",
    });

    const payload = useReviewStore.getState().toDraftPayload();

    expect(payload.confirmed_report_markdown).toBe("# 后端报告\n");
    expect(payload.review_result?.review_id).toBe("rev_test");
  });

  it("hydrates backend confirmed markdown from draft", () => {
    const draft: Draft = {
      ts: "2026-04-28T10:00:00",
      reviewer: "alice",
      phase: 4,
      prd_name: "demo.md",
      prd_content: "# Demo",
      raw_materials: [],
      user_notes: "",
      review_result: reviewResult,
      item_decisions: {},
      confirmed_report_markdown: "# 后端报告\n",
      workspace: "workspace-demo",
    };

    useReviewStore.getState().hydrateFromDraft(draft);

    expect(useReviewStore.getState().confirmedReportMarkdown).toBe(
      "# 后端报告\n",
    );
  });
});
