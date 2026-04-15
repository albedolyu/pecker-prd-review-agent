/**
 * markdown-lint 的 vitest 测试
 *
 * 跑: cd web && pnpm vitest run
 */

import { describe, it, expect } from "vitest";
import { lintMarkdown } from "@/lib/markdown-lint";

describe("lintMarkdown", () => {
  it("补上未闭合的代码块", () => {
    const bad = "# 标题\n\n```python\ndef foo():\n    pass\n\n文字继续";
    const { fixed, warnings } = lintMarkdown(bad);
    const fences = fixed.match(/^```/gm)?.length ?? 0;
    expect(fences % 2).toBe(0);
    expect(warnings.some((w) => w.includes("代码块"))).toBe(true);
  });

  it("降级跳跃的标题层级(H1 → H4 → H1 → H2)", () => {
    const bad = "# 一级\n\n#### 四级跳跃\n\n##### 再跳";
    const { fixed, warnings } = lintMarkdown(bad);
    // 预期: H1 → H2 → H3
    expect(fixed).toMatch(/^# 一级/m);
    expect(fixed).toMatch(/^## 四级跳跃/m);
    expect(fixed).toMatch(/^### 再跳/m);
    expect(warnings.some((w) => w.includes("标题"))).toBe(true);
  });

  it("移除孤立的 footnote 引用", () => {
    const bad = "这段有引用[^a]和[^b]但只有一个定义\n\n[^a]: 这是定义";
    const { fixed, warnings } = lintMarkdown(bad);
    expect(fixed).toContain("[^a]");
    expect(fixed).not.toContain("[^b]");
    expect(warnings.some((w) => w.includes("footnote"))).toBe(true);
  });

  it("保留代码块里的 # 不当作标题降级", () => {
    const bad =
      "# 真标题\n\n```python\n# 这是 python 注释\n#### 也是注释\n```\n\n后续";
    const { fixed, warnings } = lintMarkdown(bad);
    // python 注释应该原样保留,不被当成 heading 降级
    expect(fixed).toContain("# 这是 python 注释");
    expect(fixed).toContain("#### 也是注释");
    // 不会产生 heading jump warning
    expect(warnings.every((w) => !w.includes("标题"))).toBe(true);
  });

  it("检测到中文全角 / 半角混排但不自动改", () => {
    const bad = "这是问题,缺少 evidence; 需要补充!";
    const { fixed, warnings } = lintMarkdown(bad);
    // 原文本保留(半角标点没被改)
    expect(fixed).toContain("问题,");
    expect(fixed).toContain("evidence;");
    expect(warnings.some((w) => w.includes("混排"))).toBe(true);
  });

  it("归一化尾部换行和多空行", () => {
    const bad = "第一段\n\n\n\n第二段\n\n\n";
    const { fixed } = lintMarkdown(bad);
    // 3+ 空行压缩为 2
    expect(fixed).not.toMatch(/\n{3,}/);
    // 尾部正好一个 \n
    expect(fixed.endsWith("\n")).toBe(true);
    expect(fixed.endsWith("\n\n")).toBe(false);
  });

  it("纯净 markdown 原样返回", () => {
    const good = "# 干净\n\n- 一条\n- 两条\n";
    const { fixed, warnings } = lintMarkdown(good);
    expect(fixed).toBe(good);
    expect(warnings).toHaveLength(0);
  });
});
