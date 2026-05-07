import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const ROOT = process.cwd();

function readSource(path: string): string {
  return readFileSync(join(ROOT, path), "utf8");
}

describe("PM-friendly navigation copy", () => {
  it("does not expose backend route names in primary navigation", () => {
    const source = readSource("components/TopBanner.tsx");

    expect(source).toContain("评审记录");
    expect(source).toContain("质量看板");
    expect(source).not.toContain(">Runs<");
    expect(source).not.toContain(">System<");
  });

  it("uses PM-facing titles for run and system workbench pages", () => {
    const runDiff = readSource("app/runs/diff/page.tsx");
    const health = readSource("app/system/health/page.tsx");
    const prompts = readSource("app/system/prompts/page.tsx");

    expect(runDiff).toContain("两次评审对比");
    expect(runDiff).not.toContain("Harness · Run 对比");
    expect(runDiff).not.toContain("Run A ↔ Run B");

    expect(health).toContain("评审质量看板");
    expect(health).toContain("最近评审");
    expect(health).not.toContain("Harness · System Health");
    expect(health).not.toContain("最近 runs");
    expect(health).not.toContain("prompts & rules");

    expect(prompts).toContain("评审规则配置");
    expect(prompts).not.toContain("Harness · Prompts & Rules");
    expect(prompts).not.toContain("Prompt / Rule 透明度");
  });

  it("does not expose legacy Claude model names in PM-facing surfaces", () => {
    const visibleSources = [
      readSource("lib/roles.ts"),
      readSource("app/system/prompts/page.tsx"),
      readSource("components/phases/Phase1Precheck.tsx"),
      readSource("components/phases/Phase2Running.tsx"),
      readSource("components/phases/Phase2RunningV8.tsx"),
      readSource("components/run/AgentStatusCard.tsx"),
      readSource("lib/v8-run-helpers.ts"),
    ].join("\n");

    expect(visibleSources).toContain("gpt-5.5");
    expect(visibleSources).not.toContain("sonnet-4-6");
    expect(visibleSources).not.toContain("opus-4");
    expect(visibleSources).not.toContain("Opus");
    expect(visibleSources).not.toContain("Claude Sonnet");
    expect(visibleSources).not.toContain("Claude CLI 配额已用完");
  });
});
