import { describe, expect, it } from "vitest";
import type {
  GoshawkPatchEvent,
  PreliminaryResultEvent,
  ReviewStreamEvent,
} from "@/lib/useReviewStream";
import {
  isAsyncGoshawkPending,
  shouldApplyGoshawkPatchDraft,
} from "@/lib/async-goshawk";

const RESULT = {
  review_id: "rev_async_1",
  created_at: 1,
  reviewer: "pm-a",
  workspace: "workspace-alpha",
  prd_name: "async-goshawk.md",
  mode: "standard",
  items: [],
  workers: [],
  usage: {},
  goshawk_summary: null,
  signature: "sig",
} as const;

describe("async goshawk stream events", () => {
  it("supports preliminary_result as a typed worker draft handle", () => {
    const ev = {
      event: "preliminary_result",
      progress: 75,
      label: "draft ready",
      stage: "worker_draft",
      goshawk_status: "pending",
      payload: {
        ...RESULT,
        goshawk_summary: { status: "pending", mode: "async_patch" },
      },
    } as ReviewStreamEvent;

    if (ev.event !== "preliminary_result") throw new Error("narrow failed");
    const narrowed: PreliminaryResultEvent = ev;
    expect(narrowed.stage).toBe("worker_draft");
    expect(narrowed.goshawk_status).toBe("pending");
    expect(narrowed.payload.goshawk_summary).toEqual({
      status: "pending",
      mode: "async_patch",
    });
  });

  it("supports goshawk_patch as a typed supplemental result handle", () => {
    const ev = {
      event: "goshawk_patch",
      progress: 98,
      label: "patch ready",
      stage: "goshawk_patch",
      goshawk_status: "completed",
      preliminary_review_id: "rev_async_1",
      payload: {
        ...RESULT,
        review_id: "rev_async_2",
        items: [{ id: "G-1", dimension: "risk", problem: "补充异常处理" }],
        goshawk_summary: { verdict: "REVIEWED", confidence: 0.92 },
      },
    } as ReviewStreamEvent;

    if (ev.event !== "goshawk_patch") throw new Error("narrow failed");
    const narrowed: GoshawkPatchEvent = ev;
    expect(narrowed.goshawk_status).toBe("completed");
    expect(narrowed.preliminary_review_id).toBe("rev_async_1");
    expect(narrowed.payload.items).toHaveLength(1);
  });

  it("detects pending worker drafts and applies only matching final drafts", () => {
    const pending = {
      ...RESULT,
      review_id: "rev_pre",
      goshawk_summary: { status: "pending", mode: "async_patch" },
    };
    const final = {
      ...RESULT,
      review_id: "rev_final",
      items: [{ id: "G-1", dimension: "risk", problem: "patched" }],
      goshawk_summary: { verdict: "REVIEWED", confidence: 0.9 },
    };

    expect(isAsyncGoshawkPending(pending)).toBe(true);
    expect(
      shouldApplyGoshawkPatchDraft(pending, {
        reviewer: "pm-a",
        phase: 3,
        prd_name: "async-goshawk.md",
        prd_content: "",
        mode: "standard",
        raw_materials: [],
        user_notes: "",
        workspace: "workspace-alpha",
        item_decisions: { "I-1": { action: "accept" } },
        confirmed_report_markdown: "",
        review_result: final,
        ts: "2026-05-11T00:00:00",
      }),
    ).toBe(true);
  });

  it("does not apply another PRD draft as a goshawk patch", () => {
    const pending = {
      ...RESULT,
      review_id: "rev_pre",
      goshawk_summary: { status: "pending", mode: "async_patch" },
    };

    expect(
      shouldApplyGoshawkPatchDraft(pending, {
        reviewer: "pm-a",
        phase: 3,
        prd_name: "other.md",
        prd_content: "",
        mode: "standard",
        raw_materials: [],
        user_notes: "",
        workspace: "workspace-alpha",
        item_decisions: {},
        confirmed_report_markdown: "",
        review_result: { ...RESULT, review_id: "rev_other" },
        ts: "2026-05-11T00:00:00",
      }),
    ).toBe(false);
  });

  it("does not apply a draft from another review mode as a goshawk patch", () => {
    const pending = {
      ...RESULT,
      review_id: "rev_pre",
      goshawk_summary: { status: "pending", mode: "async_patch" },
    };
    const final = {
      ...RESULT,
      review_id: "rev_final",
      mode: "quick",
      items: [{ id: "G-1", dimension: "risk", problem: "patched" }],
      goshawk_summary: { verdict: "REVIEWED", confidence: 0.9 },
    };

    expect(
      shouldApplyGoshawkPatchDraft(pending, {
        reviewer: "pm-a",
        phase: 3,
        prd_name: "async-goshawk.md",
        prd_content: "",
        mode: "quick",
        raw_materials: [],
        user_notes: "",
        workspace: "workspace-alpha",
        item_decisions: {},
        confirmed_report_markdown: "",
        review_result: final,
        ts: "2026-05-11T00:00:00",
      }),
    ).toBe(false);
  });
});
