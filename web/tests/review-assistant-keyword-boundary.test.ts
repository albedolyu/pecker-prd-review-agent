import { describe, expect, it } from "vitest";

import {
  shouldIncludeFactLayer,
  shouldQueryFengniaoEvidence,
} from "@/lib/review-assistant";

describe("review assistant english keyword boundaries", () => {
  it("does not treat english keyword substrings as fact-layer requests", () => {
    const question = "How should PMs compare capital budget tradeoffs?";

    expect(shouldIncludeFactLayer(question)).toBe(false);
    expect(shouldQueryFengniaoEvidence(question)).toBe(false);
  });
});
