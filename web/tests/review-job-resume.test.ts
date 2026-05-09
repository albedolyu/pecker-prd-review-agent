import { afterEach, describe, expect, it, vi } from "vitest";
import { readFileSync } from "node:fs";
import { join } from "node:path";

import {
  ApiError,
} from "@/lib/api";
import {
  isBackgroundReviewJobModeEnabled,
  pmFacingReviewMessage,
  REVIEW_JOB_RESUME_LOST_MESSAGE,
  reviewJobEventToStreamEvent,
  reviewJobResumeKey,
  reviewStreamErrorMessage,
} from "@/lib/useReviewStream";
import type { ReviewJobEvent, ReviewRunRequest } from "@/lib/api";

function makeRequest(overrides: Partial<ReviewRunRequest> = {}): ReviewRunRequest {
  return {
    reviewer: "pm-a",
    workspace: "workspace-alpha",
    prd_name: "alpha.md",
    prd_content: "# Alpha\nbody",
    raw_materials: ["material-a"],
    user_notes: "note-a",
    mode: "standard",
    wiki_pages: {},
    ...overrides,
  };
}

describe("review job resume helpers", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it("enables reconnectable job mode by default with an explicit kill switch", () => {
    vi.stubEnv("NEXT_PUBLIC_REVIEW_JOB_MODE", "");
    expect(isBackgroundReviewJobModeEnabled()).toBe(true);
    vi.stubEnv("NEXT_PUBLIC_REVIEW_JOB_MODE", "0");
    expect(isBackgroundReviewJobModeEnabled()).toBe(false);
    vi.stubEnv("NEXT_PUBLIC_REVIEW_JOB_MODE", "1");
    expect(isBackgroundReviewJobModeEnabled()).toBe(true);
  });

  it("builds stable resume keys for the same review input", () => {
    expect(reviewJobResumeKey(makeRequest())).toBe(reviewJobResumeKey(makeRequest()));
  });

  it("changes resume key when the PRD content changes", () => {
    expect(reviewJobResumeKey(makeRequest({ prd_content: "# Alpha" }))).not.toBe(
      reviewJobResumeKey(makeRequest({ prd_content: "# Beta" })),
    );
  });

  it("changes resume key when the workspace source content changes", () => {
    expect(
      reviewJobResumeKey(makeRequest({ wiki_pages: { "guide.md": "old guide" } })),
    ).not.toBe(
      reviewJobResumeKey(makeRequest({ wiki_pages: { "guide.md": "new guide" } })),
    );
  });

  it("converts public job events into stream events without job bookkeeping", () => {
    const event: ReviewJobEvent = {
      index: 3,
      ts: 123,
      event: "worker_done",
      progress: 42,
      dim_key: "structure",
      dim_name: "业务",
      success: true,
      items_count: 2,
    };

    expect(reviewJobEventToStreamEvent(event)).toEqual({
      event: "worker_done",
      progress: 42,
      dim_key: "structure",
      dim_name: "业务",
      success: true,
      items_count: 2,
    });
  });

  it("keeps queued job events as PM-facing stream progress", () => {
    const event: ReviewJobEvent = {
      index: 4,
      ts: 124,
      event: "review_queued",
      progress: 12,
      label: "等待空闲评审位",
      message: "已进入评审队列，等待空闲评审位",
      max_concurrent: 2,
    };

    expect(reviewJobEventToStreamEvent(event)).toEqual({
      event: "review_queued",
      progress: 12,
      label: "等待空闲评审位",
      message: "已进入评审队列，等待空闲评审位",
      max_concurrent: 2,
    });
  });

  it("uses a PM-facing message when a stored resume job cannot be reused", () => {
    expect(REVIEW_JOB_RESUME_LOST_MESSAGE).toContain("无法继续接回");
    expect(REVIEW_JOB_RESUME_LOST_MESSAGE).toContain("重新发起评审");
    expect(REVIEW_JOB_RESUME_LOST_MESSAGE).not.toContain("job");
    expect(REVIEW_JOB_RESUME_LOST_MESSAGE).not.toContain("404");
  });

  it("prefers backend Chinese detail over API/HTTP prefixes", () => {
    expect(
      reviewStreamErrorMessage(
        new ApiError(403, "今日额度已用完，请明天再试。", "API 403 Forbidden"),
      ),
    ).toBe("今日额度已用完，请明天再试。");
    expect(reviewStreamErrorMessage(new Error("API 502 Bad Gateway"))).not.toContain(
      "API 502",
    );
  });

  it("turns raw timeout and gateway messages into PM-facing copy", () => {
    expect(pmFacingReviewMessage("Request timed out.")).toContain("评审响应过慢");
    expect(pmFacingReviewMessage("Request timed out.")).toContain("重新评审");
    expect(pmFacingReviewMessage("Request timed out.")).toContain("检查评审线路");
    expect(pmFacingReviewMessage("Request timed out.")).not.toContain("失败方向");
    expect(pmFacingReviewMessage("Request timed out.")).not.toContain("模型线路");
    expect(pmFacingReviewMessage("Request timed out.")).not.toContain("排查");
    expect(pmFacingReviewMessage("HTTP 524 Gateway Timeout")).not.toContain("HTTP 524");
    expect(pmFacingReviewMessage("API 502 Bad Gateway")).not.toContain("API 502");
  });

  it("turns browser network disconnect errors into resume guidance", () => {
    const message = pmFacingReviewMessage("Failed to fetch");

    expect(message).toContain("网络连接中断");
    expect(message).toContain("刷新页面");
    expect(message).toContain("页面会尝试接回本次评审");
    expect(message).not.toContain("后台");
    expect(message).not.toContain("系统会尽量");
    expect(message).not.toContain("Failed to fetch");
  });

  it("clears stored job binding after terminal events so rerun starts fresh", () => {
    const source = readFileSync(join(process.cwd(), "lib/useReviewStream.ts"), "utf8");

    expect(source).toMatch(
      /if \(sawTerminalEvent\) \{\s*clearStoredJobId\(resumeKey\);\s*activeJobResumeKeyRef\.current = null;\s*activeJobIdRef\.current = null;/,
    );
  });

  it("surfaces reused background jobs as a PM-facing progress event", () => {
    const source = readFileSync(join(process.cwd(), "lib/useReviewStream.ts"), "utf8");

    expect(source).toContain("started.reused");
    expect(source).toContain("已接回进行中的评审");
    expect(source).toContain("本次不会重复生成");
    expect(source).not.toContain("job reused");
  });
});
