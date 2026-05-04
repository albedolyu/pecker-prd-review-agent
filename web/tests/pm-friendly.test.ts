import { describe, expect, it } from "vitest";

import type { ReviewResult } from "@/lib/api";
import {
  buildPmFriendlySnapshot,
  buildZhiquHandoff,
  formatReviewModeLabel,
} from "@/lib/pm-friendly";

const baseResult: ReviewResult = {
  review_id: "rev_pm_001",
  created_at: 1,
  reviewer: "pm",
  workspace: "workspace-demo",
  prd_name: "demo.md",
  mode: "standard",
  items: [
    {
      id: "R-001",
      dimension: "structure",
      severity: "must",
      location: "账户冻结流程",
      problem: "缺少失败状态和验收标准",
      suggestion: "补充成功、失败、异常三种状态的验收口径",
      confidence: 0.92,
      rule_id: "rule_acceptance",
    },
    {
      id: "R-002",
      dimension: "ai_coding",
      severity: "must",
      location: "接口字段",
      problem: "接口字段缺少类型约束",
      suggestion: "补充字段类型和枚举",
      confidence: 0.88,
      rule_id: "rule_api_contract",
    },
    {
      id: "R-003",
      dimension: "quality",
      severity: "should",
      location: "通知文案",
      problem: "文案边界不清晰",
      suggestion: "补充 0 条、1 条、多条的展示规则",
      confidence: 0.75,
    },
  ],
  workers: [],
  usage: {},
  goshawk_summary: null,
  signature: "sig",
};

describe("pm-friendly review projection", () => {
  it("builds a PM-first conclusion and keeps engineering items separate", () => {
    const snapshot = buildPmFriendlySnapshot(baseResult);

    expect(snapshot.pmSummary.verdict).toBe("建议补充后再评审");
    expect(snapshot.pmSummary.blocking_count).toBe(2);
    expect(snapshot.pmView.pm_count).toBe(2);
    expect(snapshot.pmView.engineering_count).toBe(1);
    expect(snapshot.pmView.engineering_items[0]?.id).toBe("R-002");
  });

  it("marks missing acceptance/state details as blocking for ZhiQue handoff", () => {
    const snapshot = buildPmFriendlySnapshot(baseResult);

    expect(snapshot.testabilitySummary.testability_verdict).toBe("blocked");
    expect(snapshot.testabilitySummary.estimated_case_coverage).toBe("低");
    expect(snapshot.testabilitySummary.blocking_gap_count).toBe(1);
    expect(snapshot.testabilitySummary.engineering_context_count).toBe(1);
    expect(snapshot.testabilitySummary.untestable_gaps[0]?.id).toBe("R-001");
  });

  it("exports a deterministic pecker_to_zhiqu handoff package", () => {
    const handoff = buildZhiquHandoff(baseResult);

    expect(handoff.schema_version).toBe("pecker_to_zhiqu.v1");
    expect(handoff.target_agent).toBe("zhiqu_test_case_agent");
    expect(handoff.review_mode).toBe("deep");
    expect(handoff.scenario_matrix).toHaveLength(3);
    expect(handoff.pm_controls.do_not_invent_missing_requirements).toBe(true);
    expect(handoff.pm_controls.blocked_items_require_pm_input).toEqual([
      "R-001",
    ]);
    expect(handoff.traceability.map((item) => item.review_item_id)).toEqual([
      "R-001",
      "R-002",
      "R-003",
    ]);
  });

  it("uses light/deep labels while preserving quick/standard API values", () => {
    expect(formatReviewModeLabel("quick")).toBe("轻评审");
    expect(formatReviewModeLabel("standard")).toBe("深评审");
  });
});
