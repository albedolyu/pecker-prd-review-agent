import { readFileSync } from "node:fs";
import { join } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";

import { feedbackApi } from "@/lib/api";

const ROOT = process.cwd();
const originalFetch = global.fetch;

function readSource(path: string): string {
  return readFileSync(join(ROOT, path), "utf8");
}

describe("PM rework avoidance feedback", () => {
  afterEach(() => {
    global.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  it("posts rework avoidance feedback to the backend", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ status: "ok", feedback_id: 1 }),
    });
    global.fetch = fetchMock as unknown as typeof fetch;

    await feedbackApi.reportReworkAvoidance({
      categories: ["field_caliber", "implementation_risk"],
      note: "少补了一次字段口径说明",
      workspace: "workspace-alpha",
      prd_name: "alpha.md",
    });

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/feedback/rework-avoidance",
      expect.objectContaining({
        method: "POST",
        credentials: "include",
        body: JSON.stringify({
          categories: ["field_caliber", "implementation_risk"],
          note: "少补了一次字段口径说明",
          workspace: "workspace-alpha",
          prd_name: "alpha.md",
        }),
      }),
    );
  });

  it("renders the optional Phase 4 rework feedback card", () => {
    const phase4 = readSource("components/phases/Phase4Report.tsx");

    expect(phase4).toContain("本次评审帮你避免了什么返工");
    expect(phase4).toContain("避免字段口径返工");
    expect(phase4).toContain("避免体验流程返工");
    expect(phase4).toContain("避免实现风险返工");
    expect(phase4).toContain("暂未看到");
    expect(phase4).toContain("feedbackApi.reportReworkAvoidance");
  });

  it("shows rework avoidance samples in the admin usage dashboard", () => {
    const usage = readSource("app/system/usage/page.tsx");
    const api = readSource("lib/api.ts");

    expect(api).toContain("ReworkAvoidanceSummary");
    expect(api).toContain("rework_avoidance?: ReworkAvoidanceSummary");
    expect(usage).toContain("返工避免样本");
    expect(usage).toContain("productive_rate");
    expect(usage).toContain("reworkCategoryLabel");
  });

  it("exposes shift-right rule recommendations in the admin feedback contract", () => {
    const api = readSource("lib/api.ts");

    expect(api).toContain("RuleRecommendation");
    expect(api).toContain("rule_recommendations?: RuleRecommendation[]");
    expect(api).toContain("narrow_rule_trigger");
    expect(api).toContain("strengthen_missing_coverage");
  });

  it("shows shift-right rule recommendations in the admin usage dashboard", () => {
    const usage = readSource("app/system/usage/page.tsx");

    expect(usage).toContain("rule_recommendations");
    expect(usage).toContain("Shift-right rule recommendations");
    expect(usage).toContain("ruleRecommendationLabel");
    expect(usage).toContain("recommendation.samples.slice(0, 2)");
  });

  it("shows forced empty retry observability in the admin usage dashboard", () => {
    const usage = readSource("app/system/usage/page.tsx");
    const api = readSource("lib/api.ts");

    expect(api).toContain("EmptyRetrySummary");
    expect(api).toContain("empty_retry?: EmptyRetrySummary");
    expect(api).toContain("forced_confirmed_empty_retry: number");
    expect(usage).toContain("emptyRetrySummary");
    expect(usage).toContain("confirmed-empty forced retry");
    expect(usage).toContain("forced_confirmed_empty_retry");
  });
});
