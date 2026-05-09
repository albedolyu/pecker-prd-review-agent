import { describe, expect, it } from "vitest";

import {
  findPrdAnchorMatch,
  getPrdAnchorLineLabel,
  getPrdAnchorSnippet,
} from "@/lib/prd-anchor";

describe("prd anchor matching", () => {
  const prd = [
    "# PRD",
    "## 账户冻结流程",
    "用户触发冻结后，需要展示成功、失败和异常三种状态。",
    "## 通知文案",
    "0 条、1 条、多条需要分别展示。",
  ].join("\n");

  it("matches exact location text first", () => {
    const match = findPrdAnchorMatch(prd, "账户冻结流程");

    expect(match?.strategy).toBe("exact");
    expect(match?.text).toBe("账户冻结流程");
  });

  it("falls back to evidence quote when location is a loose label", () => {
    const match = findPrdAnchorMatch(
      prd,
      "第三部分 / 状态说明",
      "成功、失败和异常三种状态",
    );

    expect(match?.strategy).toBe("quote");
    expect(match?.text).toBe("成功、失败和异常三种状态");
  });

  it("matches evidence even when the PRD wraps the quoted text across lines", () => {
    const wrappedPrd = [
      "# 积分抵扣",
      "支付前需要支持支付前",
      "锁定本次使用的积分，并在失败后返还。",
    ].join("\n");

    const match = findPrdAnchorMatch(
      wrappedPrd,
      "原文依据",
      "支持支付前锁定本次使用的积分",
    );

    expect(match?.strategy).toBe("quote");
    expect(match?.text.replace(/\s+/g, "")).toBe("支持支付前锁定本次使用的积分");
    expect(getPrdAnchorLineLabel(wrappedPrd, match)).toBe("第 2-3 行");
  });

  it("supports line references from worker output", () => {
    const match = findPrdAnchorMatch(prd, "line 4");

    expect(match?.strategy).toBe("line");
    expect(match?.text).toContain("通知文案");
  });

  it("supports line-range references from review output", () => {
    const match = findPrdAnchorMatch(prd, "第 3-4 行");

    expect(match?.strategy).toBe("line");
    expect(match?.text).toContain("成功、失败和异常三种状态");
    expect(match?.text).toContain("通知文案");
    expect(getPrdAnchorLineLabel(prd, match)).toBe("第 3-4 行");
  });

  it("uses long tokens as a final fallback", () => {
    const match = findPrdAnchorMatch(prd, "模块/通知文案/展示规则");

    expect(match?.strategy).toBe("token");
    expect(match?.text).toBe("通知文案");
  });

  it("builds a short PM-readable source snippet around the matched text", () => {
    const match = findPrdAnchorMatch(prd, "成功、失败和异常三种状态");
    const snippet = getPrdAnchorSnippet(prd, match, 8);

    expect(snippet).toContain("成功、失败和异常三种状态");
    expect(snippet.length).toBeLessThan(prd.length);
    expect(snippet.startsWith("…")).toBe(true);
    expect(snippet.endsWith("…")).toBe(true);
  });

  it("returns a PM-readable line label for the matched source location", () => {
    const match = findPrdAnchorMatch(prd, "成功、失败和异常三种状态");

    expect(getPrdAnchorLineLabel(prd, match)).toBe("第 3 行");
  });
});
