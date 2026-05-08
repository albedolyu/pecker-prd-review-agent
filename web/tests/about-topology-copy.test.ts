import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const ROOT = process.cwd();

function readSource(path: string): string {
  return readFileSync(join(ROOT, path), "utf8");
}

describe("about page topology copy", () => {
  it("uses PM-facing workflow nodes instead of backend topology labels", () => {
    const source = readSource("app/about/page.tsx");

    expect(source).toContain("提交 PRD");
    expect(source).toContain("资料预检");
    expect(source).toContain("四个方向并行检查");
    expect(source).toContain("意见合并");
    expect(source).toContain("结果完整性");
    expect(source).toContain("PM 确认");
    expect(source).toContain("反馈回流");

    expect(source).not.toContain("Agent 协作拓扑");
    expect(source).not.toContain("Worker 层");
    expect(source).not.toContain("Meta 层");
    expect(source).not.toContain("苍鹰交叉校验");
    expect(source).not.toContain("orchestrator");
    expect(source).not.toContain("AI coding");
  });

  it("keeps non-bird topology nodes on a consistent icon system", () => {
    const source = readSource("app/about/page.tsx");

    expect(source).toContain("FileText");
    expect(source).toContain("ShieldCheck");
    expect(source).toContain("CircleCheckBig");
    expect(source).not.toContain("step.label?.slice(0, 1)");
  });

  it("uses the same bird avatar treatment as other review surfaces", () => {
    const source = readSource("app/about/page.tsx");

    expect(source).toContain('size="lg"');
    expect(source).not.toContain('size={compact ? "md" : "lg"}');
    expect(source).not.toContain('size={compact ? "sm" : "md"}');
    expect(source).not.toContain("placeholder: true");
    expect(source).not.toContain("placeholder={birdId > 5}");
    expect(source).not.toContain("placeholder?: boolean");
    expect(source).not.toContain("placeholder={step.placeholder}");
  });
});
