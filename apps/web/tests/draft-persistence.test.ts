import fs from "node:fs";
import path from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";

import { draftsApi, type ItemDecision, type ReviewResult } from "@/lib/api";
import {
  buildDraftPayloadFromSnapshot,
  saveReviewDraftSnapshot,
} from "@/lib/draft-persistence";

const reviewResult: ReviewResult = {
  review_id: "rev_resume",
  created_at: 1,
  reviewer: "pm-a",
  workspace: "workspace-demo",
  prd_name: "demo.md",
  mode: "standard",
  items: [],
  workers: [],
  usage: {},
  goshawk_summary: null,
  signature: "signed",
};

describe("review draft persistence", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("stores review result at phase 3 so refresh can resume confirmation", () => {
    const payload = buildDraftPayloadFromSnapshot({
      reviewer: "pm-a",
      phase: 3,
      prdName: "demo.md",
      prdContent: "# Demo PRD",
      workspace: "workspace-demo",
      mode: "quick",
      userNotes: "focus data",
      rawMaterials: ["material"],
      reviewResult,
      decisions: {},
      confirmedReportMarkdown: "",
    });

    expect(payload.phase).toBe(3);
    expect(payload.mode).toBe("quick");
    expect(payload.review_result?.review_id).toBe("rev_resume");
    expect(payload.prd_content).toBe("# Demo PRD");
    expect(payload.workspace).toBe("workspace-demo");
  });

  it("keeps PM item decisions in the draft", () => {
    const decisions: Record<string, ItemDecision> = {
      "R-001": { action: "reject", reason_category: "false_positive" },
      "R-002": { action: "edit", edited_problem: "补充字段口径" },
    };

    const payload = buildDraftPayloadFromSnapshot({
      reviewer: "pm-a",
      phase: 3,
      prdName: "demo.md",
      prdContent: "# Demo PRD",
      workspace: "workspace-demo",
      userNotes: "",
      rawMaterials: [],
      reviewResult,
      decisions,
      confirmedReportMarkdown: "",
    });

    expect(payload.item_decisions).toEqual(decisions);
  });

  it("clamps invalid phase values before saving", () => {
    const payload = buildDraftPayloadFromSnapshot({
      reviewer: "pm-a",
      phase: 99,
      prdName: "demo.md",
      prdContent: "# Demo PRD",
      workspace: "workspace-demo",
      userNotes: "",
      rawMaterials: [],
      reviewResult: null,
      decisions: {},
      confirmedReportMarkdown: "",
    });

    expect(payload.phase).toBe(4);
  });

  it("falls back to signed reviewResult reviewer when store reviewer is empty", async () => {
    const save = vi
      .spyOn(draftsApi, "save")
      .mockResolvedValue({ status: "ok", path: "pm-a_draft.json", ts: "now" });

    const result = await saveReviewDraftSnapshot({
      reviewer: "",
      phase: 3,
      prdName: "demo.md",
      prdContent: "# Demo PRD",
      workspace: "workspace-demo",
      userNotes: "",
      rawMaterials: [],
      reviewResult,
      decisions: {},
      confirmedReportMarkdown: "",
    });

    expect(result.skipped).toBe(false);
    expect(save).toHaveBeenCalledWith("pm-a", expect.any(Object));
  });

  it("phase 3 saves decisive PM actions immediately, not only on debounce", () => {
    const source = fs.readFileSync(
      path.join(process.cwd(), "components/phases/Phase3ConfirmV8.tsx"),
      "utf8",
    );

    expect(source).toContain("saveDraftNow");
    expect(source).toContain("void saveDraftNow(nextDecisions)");
    expect(source).toContain("void saveDraftNow(decisions)");
  });

  it("phase 3 exposes 2D rejection controls", () => {
    const source = fs.readFileSync(
      path.join(process.cwd(), "components/phases/Phase3ConfirmV8.tsx"),
      "utf8",
    );

    expect(source).toContain("CORRECTNESS_REASONS");
    expect(source).toContain("BUSINESS_DECISIONS");
    expect(source).toContain("correctness_reason");
    expect(source).toContain("business_decision");
  });
});
