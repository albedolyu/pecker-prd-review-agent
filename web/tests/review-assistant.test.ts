import { describe, expect, it } from "vitest";

import { answerReviewAssistantQuestion } from "@/lib/review-assistant";
import { buildFigmaRawMaterial, buildImageRawMaterial } from "@/lib/supplemental-materials";

describe("review assistant answers", () => {
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
});
