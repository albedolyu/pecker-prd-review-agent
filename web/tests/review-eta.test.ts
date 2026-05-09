import { describe, expect, it } from "vitest";

import {
  estimateReviewEtaHint,
  estimateReviewEtaLabel,
  reviewEtaSoftLimitSeconds,
  reviewInputChars,
} from "@/lib/review-eta";

describe("review eta copy", () => {
  it("keeps short quick reviews around five minutes", () => {
    expect(
      estimateReviewEtaLabel({
        mode: "quick",
        prdContent: "# 标题\n短 PRD",
        rawMaterials: [],
      }),
    ).toBe("约 5 分钟");
  });

  it("raises standard review expectations for longer PRDs", () => {
    expect(
      estimateReviewEtaLabel({
        mode: "standard",
        prdContent: "长内容".repeat(30_000),
        rawMaterials: [],
      }),
    ).toBe("约 6-10 分钟");
  });

  it("warns very large reviews can take ten to fifteen minutes", () => {
    expect(
      estimateReviewEtaLabel({
        mode: "standard",
        prdContent: "超长内容".repeat(45_000),
        rawMaterials: ["补充材料".repeat(20_000)],
      }),
    ).toBe("约 10-15 分钟");
  });

  it("counts raw materials and workspace context in the same estimate", () => {
    expect(
      reviewInputChars({
        prdContent: "abc",
        rawMaterials: ["de", "fghi"],
        wikiPageCount: 2,
      }),
    ).toBe(3 + 2 + 4 + 2_400);
  });

  it("uses reconnectable waiting copy instead of implying the run is stuck", () => {
    expect(
      estimateReviewEtaHint({
        mode: "standard",
        prdContent: "长内容".repeat(30_000),
      }),
    ).toContain("刷新或断网后可继续等待");
  });

  it("mentions queueing when several PMs use the tool at the same time", () => {
    expect(
      estimateReviewEtaHint({
        mode: "standard",
        prdContent: "# 短 PRD",
      }),
    ).toContain("多人同时使用时可能排队");
  });

  it("uses a longer soft limit when the estimate is longer", () => {
    expect(
      reviewEtaSoftLimitSeconds({
        mode: "standard",
        prdContent: "超长内容".repeat(45_000),
      }),
    ).toBe(900);
  });
});
