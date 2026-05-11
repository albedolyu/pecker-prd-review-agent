import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { join } from "node:path";

const root = join(__dirname, "..");

function readSource(path: string): string {
  return readFileSync(join(root, path), "utf-8");
}

describe("supplemental material UI wiring", () => {
  it("lets both upload variants accept image files and build structured raw materials", () => {
    for (const sourcePath of [
      "components/phases/Phase0Upload.tsx",
      "components/phases/Phase0UploadV8.tsx",
    ]) {
      const source = readSource(sourcePath);
      expect(source).toContain("isSupportedImageFile");
      expect(source).toContain("buildImageRawMaterial");
      expect(source).toContain("extractMarkdownImageReferences");
      expect(source).toContain("buildImageReferenceRawMaterial");
      expect(source).toContain("buildFigmaRawMaterial");
      expect(source).toContain("image/png,image/jpeg,image/webp,image/gif");
      expect(source).toContain("rawMaterialTitle");
    }
  });

  it("mounts the right-bottom review assistant on the review workspace page", () => {
    const page = readSource("app/review/page.tsx");

    expect(page).toContain("ReviewHelpAssistant");
    expect(page).toContain("<ReviewHelpAssistant");
  });

  it("marks the review assistant panel as a dialog with polite answer updates", () => {
    const source = readSource("components/review/ReviewHelpAssistant.tsx");

    expect(source).toContain('role="dialog"');
    expect(source).toContain('aria-live="polite"');
  });

  it("adds lightweight assistant answer actions for feedback and copy signals", () => {
    const source = readSource("components/review/ReviewHelpAssistant.tsx");

    expect(source).toContain("ThumbsUp");
    expect(source).toContain("ThumbsDown");
    expect(source).toContain("Copy");
    expect(source).toContain('label="点赞这条回答"');
    expect(source).toContain('label="踩这条回答"');
    expect(source).toContain('label="复制这条回答"');
    expect(source).toContain("review_assistant_feedback");
    expect(source).toContain("review_assistant_copied");
    expect(source).toContain("navigator.clipboard.writeText");
    expect(source).toContain('document.execCommand("copy")');
    expect(source).toContain("auditApi.log");
  });

  it("keeps the assistant clear of bottom action bars and summarizes material types", () => {
    const source = readSource("components/review/ReviewHelpAssistant.tsx");

    expect(source).toContain("const bottomOffset = phase >= 3 ? 88 : 20");
    expect(source).toContain("bottom: bottomOffset");
    expect(source).toContain("materialSummaryText");
    expect(source).toContain('`图片 ${materialSummary.images}`');
    expect(source).toContain('`Figma ${materialSummary.figmaLinks}`');
  });
});
