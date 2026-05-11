import { describe, expect, it } from "vitest";
import type {
  GoshawkPatchEvent,
  PreliminaryResultEvent,
  ReviewStreamEvent,
} from "@/lib/useReviewStream";

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
});
