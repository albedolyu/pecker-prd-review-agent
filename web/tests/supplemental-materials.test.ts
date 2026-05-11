import { describe, expect, it } from "vitest";

import {
  buildFigmaRawMaterial,
  buildImageReferenceRawMaterial,
  buildImageRawMaterial,
  extractFigmaLinks,
  extractMarkdownImageReferences,
  mergeRawMaterials,
  summarizeRawMaterials,
} from "@/lib/supplemental-materials";

describe("supplemental materials", () => {
  it("extracts Figma design and proto links from PRD text", () => {
    const text = [
      "原型见 https://www.figma.com/design/abc123/Foo?node-id=1-2",
      "交互见 https://figma.com/proto/def456/Bar?page-id=0%3A1",
    ].join("\n");

    expect(extractFigmaLinks(text)).toEqual([
      "https://www.figma.com/design/abc123/Foo?node-id=1-2",
      "https://figma.com/proto/def456/Bar?page-id=0%3A1",
    ]);
  });

  it("builds a Figma raw material block that keeps file key and node id", () => {
    const material = buildFigmaRawMaterial(
      "https://www.figma.com/design/abc123/Foo?node-id=1-2",
      "PRD 正文",
    );

    expect(material).toContain("[补充材料: Figma]");
    expect(material).toContain("来源: PRD 正文");
    expect(material).toContain("file_key: abc123");
    expect(material).toContain("node_id: 1:2");
  });

  it("redacts sensitive Figma link query params before adding review context", () => {
    const material = buildFigmaRawMaterial(
      "https://www.figma.com/design/abc123/Foo?node-id=1-2&access_token=secret-token",
      "PRD text",
    );

    expect(material).toContain("node_id: 1:2");
    expect(material).toContain("access_token=[REDACTED]");
    expect(material).not.toContain("secret-token");
  });

  it("builds an image raw material block with readable metadata", () => {
    const material = buildImageRawMaterial({
      name: "flow.png",
      mimeType: "image/png",
      sizeBytes: 1536,
      source: "上传附件",
    });

    expect(material).toContain("[补充材料: 图片]");
    expect(material).toContain("文件名: flow.png");
    expect(material).toContain("类型: image/png");
    expect(material).toContain("大小: 1.5 KB");
    expect(material).toContain("读取状态: 图片附件已接入本次评审上下文");
  });

  it("extracts markdown image references from PRD text", () => {
    const refs = extractMarkdownImageReferences(
      "流程如下 ![开户流程](./assets/open.png) 失败态 ![](https://cdn.example/fail.jpg)",
    );

    expect(refs).toEqual([
      { alt: "开户流程", url: "./assets/open.png" },
      { alt: "", url: "https://cdn.example/fail.jpg" },
    ]);
  });

  it("builds a raw material block for markdown image references", () => {
    const material = buildImageReferenceRawMaterial({
      alt: "开户流程",
      url: "./assets/open.png",
      source: "PRD 正文",
    });

    expect(material).toContain("[补充材料: 图片]");
    expect(material).toContain("引用地址: ./assets/open.png");
    expect(material).toContain("图片说明: 开户流程");
  });

  it("redacts signed markdown image reference URLs before adding review context", () => {
    const material = buildImageReferenceRawMaterial({
      alt: "flow",
      url: "https://cdn.example/flow.png?sig=secret-signature&version=1",
      source: "PRD text",
    });

    expect(material).toContain("sig=[REDACTED]");
    expect(material).toContain("version=1");
    expect(material).not.toContain("secret-signature");
  });

  it("dedupes raw materials while preserving order", () => {
    expect(mergeRawMaterials(["A", "B"], ["B", "C"])).toEqual(["A", "B", "C"]);
  });

  it("summarizes image and Figma material counts for the assistant", () => {
    const rawMaterials = [
      buildImageRawMaterial({
        name: "flow.png",
        mimeType: "image/png",
        sizeBytes: 100,
        source: "上传附件",
      }),
      buildFigmaRawMaterial("https://www.figma.com/design/abc123/Foo", "PRD 正文"),
    ];

    expect(summarizeRawMaterials(rawMaterials)).toEqual({
      total: 2,
      images: 1,
      figmaLinks: 1,
    });
  });
});
