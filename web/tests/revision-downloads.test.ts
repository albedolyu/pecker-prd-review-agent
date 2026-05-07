import { describe, expect, it } from "vitest";

import type { ItemDecision, ReviewResult } from "@/lib/api";
import {
  generateRevisionAdviceMarkdown,
  generateRevisionDraftMarkdown,
} from "@/lib/generateReport";

const result: ReviewResult = {
  review_id: "rev_sensitive",
  created_at: 1,
  reviewer: "alice",
  workspace: "workspace-demo",
  prd_name: "真实客户需求.md",
  mode: "standard",
  workers: [],
  usage: {},
  goshawk_summary: null,
  signature: "sig",
  items: [
    {
      id: "R-001",
      dimension: "structure",
      severity: "must",
      location: "三、结算规则",
      problem: "缺少退款边界。",
      evidence: "只描述成功路径。",
      suggestion: "补充失败、撤销和重复提交处理。",
      confidence: 0.91,
    },
    {
      id: "R-002",
      dimension: "quality",
      severity: "should",
      location: "四、提醒",
      problem: "提醒文案不明确。",
      suggestion: "改成 PM 指定的文案。",
      confidence: 0.72,
    },
    {
      id: "R-003",
      dimension: "data_quality",
      severity: "suggest",
      problem: "低价值建议。",
      suggestion: "可以考虑补表。",
      confidence: 0.4,
    },
  ],
};

const decisions: Record<string, ItemDecision> = {
  "R-001": { action: "accept" },
  "R-002": {
    action: "edit",
    edited_problem: "提醒文案需要补充触发时机和失败态。",
  },
  "R-003": { action: "reject", reason_category: "model_noise" },
};

describe("revision download documents", () => {
  it("exports only accepted or edited items in the revision advice pack", () => {
    const markdown = generateRevisionAdviceMarkdown(result, decisions);

    expect(markdown).toContain("内部资料 / 仅限啄木鸟内网试用");
    expect(markdown).toContain("R-001");
    expect(markdown).toContain("R-002");
    expect(markdown).toContain("提醒文案需要补充触发时机和失败态。");
    expect(markdown).not.toContain("R-003");
    expect(markdown).not.toContain("低价值建议");
  });

  it("keeps the original PRD body and appends confirmed advice in the draft", () => {
    const originalPrd = "# 真实 PRD\n\n客户: 北京某某科技\n价格: 100 万";
    const markdown = generateRevisionDraftMarkdown(
      result,
      decisions,
      originalPrd,
    );

    expect(markdown).toContain("含未脱敏 PRD 内容");
    expect(markdown).toContain("## 原 PRD 正文");
    expect(markdown).toContain("客户: 北京某某科技");
    expect(markdown).toContain("价格: 100 万");
    expect(markdown).toContain("## 啄木鸟修订建议附录");
    expect(markdown).toContain("R-001");
    expect(markdown).not.toContain("R-003");
  });
});
