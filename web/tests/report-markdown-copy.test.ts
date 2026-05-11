import { describe, expect, it } from "vitest";

import type { ItemDecision, ReviewResult } from "@/lib/api";
import { generateReportMarkdown } from "@/lib/generateReport";

const result: ReviewResult = {
  review_id: "rev_report_copy",
  created_at: 1_778_000_000,
  reviewer: "pm-a",
  workspace: "workspace-alpha",
  prd_name: "alpha.md",
  mode: "standard",
  items: [
    {
      id: "R-001",
      dimension: "structure",
      severity: "must",
      location: "目标",
      problem: "目标没有说明验收口径",
      evidence: "原文只写支持积分抵扣",
      suggestion: "补充验收口径",
      confidence: 0.91,
    },
    {
      id: "R-002",
      dimension: "quality",
      severity: "should",
      problem: "提示文案过于专业",
      confidence: 0.6,
    },
  ],
  workers: [
    { dimension: "structure", dimension_name: "业务完整性", items_count: 1, error: null },
    { dimension: "quality", dimension_name: "使用体验", items_count: 1, error: null },
  ],
  usage: { input_tokens: 100, output_tokens: 20 },
  goshawk_summary: {
    flagged_as_false_positive: [],
    additional_findings: [],
  },
  signature: "signed",
};

describe("report markdown copy", () => {
  it("uses PM-facing report labels instead of backend handle wording", () => {
    const decisions: Record<string, ItemDecision> = {
      "R-001": { action: "accept" },
      "R-002": { action: "reject", reason_category: "model_noise" },
    };

    const markdown = generateReportMarkdown(result, decisions);

    expect(markdown).toContain("**资料库**");
    expect(markdown).toContain("**追踪编号**");
    expect(markdown).toContain("各方向提交");
    expect(markdown).toContain("参考程度");
    expect(markdown).toContain("PM 处理提示");
    expect(markdown).toContain("PM 需要判断");
    expect(markdown).toContain("建议动作");
    expect(markdown).toContain("业务完整性");
    expect(markdown).toContain("使用体验");
    expect(markdown).toContain("采纳");
    expect(markdown).toContain("驳回");
    expect(markdown).toContain("判断不准");
    expect(markdown).not.toContain("维护人排障信息");
    expect(markdown).not.toContain("维护人处理记录");
    expect(markdown).not.toContain("```json");
    expect(markdown).not.toContain("Workspace");
    expect(markdown).not.toContain("Review ID");
    expect(markdown).not.toContain("worker 贡献");
    expect(markdown).not.toContain("Opaque Handle");
    expect(markdown).not.toContain("**评审编号**");
    expect(markdown).not.toContain("置信度");
    expect(markdown).not.toContain("可信度");
    expect(markdown).not.toContain("模型噪音");
    expect(markdown).not.toContain("接受 1");
    expect(markdown).not.toContain("拒绝 1");
    expect(markdown).not.toContain("已接受");
    expect(markdown).not.toContain("已拒绝");
    expect(markdown).not.toContain("### 1. R-001");
  });

  it("keeps revision downloads away from backend item labels", () => {
    const decisions: Record<string, ItemDecision> = {
      "R-001": { action: "edit", edited_problem: "补充验收口径" },
      "R-002": { action: "reject", reason_category: "model_noise" },
    };

    const markdown = generateReportMarkdown(result, decisions);

    expect(markdown).toContain("原意见");
    expect(markdown).not.toContain("原始:");
    expect(markdown).not.toContain("原始评审问题");
  });

  it("prints 2D rejection reasons instead of the legacy bucket when present", () => {
    const decisions: Record<string, ItemDecision> = {
      "R-002": {
        action: "reject",
        reason_category: "known_tradeoff",
        correctness_reason: "unsupported_evidence",
        business_decision: "risk_accepted",
      },
    };

    const markdown = generateReportMarkdown(result, decisions);

    expect(markdown).toContain("**判断问题**: 依据不足");
    expect(markdown).toContain("**业务处理**: 风险接受");
    expect(markdown).not.toContain("**驳回原因**");
  });

  it("keeps maintenance JSON behind an explicit option", () => {
    const markdown = generateReportMarkdown(result, {}, { includeMaintenanceDetails: true });

    expect(markdown).toContain("维护人处理记录");
    expect(markdown).not.toContain("维护人排障信息");
    expect(markdown).toContain("```json");
    expect(markdown).toContain("items_count");
  });
});
