import { describe, expect, it } from "vitest";

import type { ReviewResult } from "@/lib/api";
import {
  buildReviewItemPatchText,
  buildPmFriendlySnapshot,
  buildZhiquHandoff,
  explainReviewItemForPm,
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

  it("uses the same PM-facing direction names as the review UI", () => {
    const snapshot = buildPmFriendlySnapshot({
      ...baseResult,
      items: [
        ...baseResult.items,
        {
          id: "R-004",
          dimension: "data_quality",
          severity: "should",
          location: "抵扣金额字段",
          problem: "字段来源没有写清楚",
          suggestion: "补充字段来源和计算口径",
          confidence: 0.8,
        },
      ],
    });
    const dimensions = [
      ...snapshot.pmView.pm_items.map((item) => item.dimension),
      ...snapshot.pmView.engineering_items.map((item) => item.dimension),
      ...snapshot.testabilitySummary.testable_modules.map((item) => item.dimension),
    ];

    expect(dimensions).toContain("业务完整性");
    expect(dimensions).toContain("使用体验");
    expect(dimensions).toContain("字段口径");
    expect(dimensions).not.toContain("结构");
    expect(dimensions).not.toContain("质量");
    expect(dimensions).not.toContain("数据质量");
  });

  it("adds a PM-readable explanation for technical items", () => {
    const explanation = explainReviewItemForPm(baseResult.items[1]!);
    expect(explanation.plain_language_summary).toContain("PM");
    expect(explanation.plain_language_summary).toContain("枚举就是可选值清单");

    expect(explanation.detail_label).toBe("偏研发细节");
    expect(explanation.pm_question).toContain("研发实现细节");
    expect(explanation.suggested_next_step).toContain("实现细节");
    expect(explanation.is_engineering_context).toBe(true);
  });

  it("uses backend proposed_patch as the one-click PRD patch text", () => {
    const patchText = buildReviewItemPatchText({
      id: "R-patch",
      dimension: "structure",
      location: "3. Acceptance",
      problem: "Missing failure state",
      suggestion: "Fallback suggestion should not be copied first.",
      proposed_patch: "Add this exact failure-state paragraph to the PRD.",
      evidence: "Existing acceptance section",
    });

    expect(patchText).toBe("Add this exact failure-state paragraph to the PRD.");
  });

  it("falls back to a paste-ready patch when proposed_patch is missing", () => {
    const patchText = buildReviewItemPatchText({
      id: "R-patch",
      dimension: "structure",
      location: "3. Acceptance",
      problem: "Missing failure state",
      suggestion: "Add success, failure, and timeout acceptance criteria.",
      evidence: "Existing acceptance section",
    });

    expect(patchText).toContain("3. Acceptance");
    expect(patchText).toContain("Add success, failure, and timeout acceptance criteria.");
    expect(patchText).toContain("Missing failure state");
  });

  it("translates common implementation terms into PM decision language", () => {
    const explanation = explainReviewItemForPm({
      id: "R-tech",
      dimension: "ai_coding",
      severity: "must",
      location: "支付回调",
      problem: "接口回调没有说明并发重复提交时怎么兜底",
      suggestion: "补充接口调用方、回调触发时机、并发重复提交的处理规则",
      confidence: 0.8,
    });

    expect(explanation.plain_language_summary).toContain("系统之间的对接方式");
    expect(explanation.plain_language_summary).toContain("多人或多个请求同时发生");
    expect(explanation.plain_language_summary).not.toContain("debug");
  });

  it("translates release and data tracking terms into PM decision language", () => {
    const explanation = explainReviewItemForPm({
      id: "R-release",
      dimension: "ai_coding",
      severity: "must",
      location: "上线策略",
      problem: "状态机没有说明超时后的回滚,也缺少灰度和埋点口径",
      suggestion: "补充上游下游依赖、事务边界、超时回滚、灰度发布和埋点校验",
      confidence: 0.83,
    });

    expect(explanation.plain_language_summary).toContain("状态机可以理解为业务状态怎么流转");
    expect(explanation.plain_language_summary).toContain("回滚是出问题后怎么退回");
    expect(explanation.plain_language_summary).toContain("灰度是先放给一小部分用户");
    expect(explanation.plain_language_summary).toContain("埋点是后续看数据的记录方式");
    expect(explanation.plain_language_summary).toContain("上游下游是前后依赖的系统或流程");
    expect(explanation.plain_language_summary).not.toMatch(/\bdebug|trace\b/i);
  });

  it("translates stability and compliance terms into PM decision language", () => {
    const explanation = explainReviewItemForPm({
      id: "R-stability",
      dimension: "ai_coding",
      severity: "must",
      location: "批量导入任务",
      problem: "缺少 P99、QPS、限流、熔断、队列积压、补偿任务和数据脱敏审计口径",
      suggestion: "补充高峰期容量、触发保护后的提示、失败补偿方式、脱敏字段和审计留痕",
      confidence: 0.86,
    });

    expect(explanation.plain_language_summary).toContain("高峰期能不能扛住");
    expect(explanation.plain_language_summary).toContain("流量太大时怎么保护服务");
    expect(explanation.plain_language_summary).toContain("异步任务排队太多时怎么处理");
    expect(explanation.plain_language_summary).toContain("失败后怎么补救");
    expect(explanation.plain_language_summary).toContain("哪些字段不能直接展示或外发");
    expect(explanation.plain_language_summary).not.toMatch(/\bdebug|trace\b/i);
  });
});
