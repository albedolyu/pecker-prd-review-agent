import { afterEach, describe, expect, it, vi } from "vitest";

import {
  answerReviewAssistantQuestion,
  answerReviewAssistantQuestionAsync,
  shouldIncludeFactLayer,
  shouldQueryFengniaoEvidence,
} from "@/lib/review-assistant";
import { buildFigmaRawMaterial, buildImageRawMaterial } from "@/lib/supplemental-materials";

const originalFetch = global.fetch;

describe("review assistant answers", () => {
  afterEach(() => {
    global.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  it("answers whether image and Figma materials were included", () => {
    const answer = answerReviewAssistantQuestion("图片和 figma 读到了吗", {
      phase: 1,
      rawMaterials: [
        buildImageRawMaterial({
          name: "flow.png",
          mimeType: "image/png",
          sizeBytes: 100,
          source: "上传附件",
        }),
        buildFigmaRawMaterial("https://figma.com/design/abc123/Foo", "PRD 正文"),
      ],
    });

    expect(answer).toContain("已接入 1 个图片附件");
    expect(answer).toContain("1 个 Figma 链接");
    expect(answer).toContain("预检页");
  });

  it("answers confirmation action questions with the current decision vocabulary", () => {
    const answer = answerReviewAssistantQuestion("采纳 驳回 改写 有什么区别", {
      phase: 3,
      rawMaterials: [],
    });

    expect(answer).toContain("采纳");
    expect(answer).toContain("驳回");
    expect(answer).toContain("改写");
  });

  it("answers export questions with phase-aware guidance", () => {
    const answer = answerReviewAssistantQuestion("报告怎么导出", {
      phase: 4,
      rawMaterials: [],
    });

    expect(answer).toContain("导出报告");
    expect(answer).toContain("最后一步");
  });

  it("recognizes Fengniao evidence and original fact-layer questions", () => {
    expect(shouldQueryFengniaoEvidence("风鸟知识库里怎么说")).toBe(true);
    expect(shouldQueryFengniaoEvidence("查一下原始事实层字段")).toBe(true);
    expect(shouldQueryFengniaoEvidence("报告怎么导出")).toBe(false);

    expect(shouldIncludeFactLayer("查一下原始事实层字段")).toBe(true);
    expect(shouldIncludeFactLayer("这个接口源码里叫什么")).toBe(true);
    expect(shouldIncludeFactLayer("风鸟知识库里怎么说")).toBe(false);
  });

  it("queries the backend Fengniao evidence endpoint before falling back", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        answer: "查到 1 条事实层依据",
        hits: [],
        include_fact_layer: true,
      }),
    });
    global.fetch = fetchMock as unknown as typeof fetch;

    const answer = await answerReviewAssistantQuestionAsync("帮我查风鸟原始事实层字段", {
      phase: 3,
      rawMaterials: [],
    });

    expect(answer).toBe("查到 1 条事实层依据");
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/review/assistant/fengniao",
      expect.objectContaining({
        method: "POST",
        credentials: "include",
        body: JSON.stringify({
          question: "帮我查风鸟原始事实层字段",
          include_fact_layer: true,
          max_results: 5,
        }),
      }),
    );
  });
});
