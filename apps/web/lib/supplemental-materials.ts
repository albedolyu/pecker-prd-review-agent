export interface ImageRawMaterialInput {
  name: string;
  mimeType: string;
  sizeBytes: number;
  source: string;
}

export interface RawMaterialSummary {
  total: number;
  images: number;
  figmaLinks: number;
}

export interface MarkdownImageReference {
  alt: string;
  url: string;
}

const FIGMA_LINK_RE =
  /https?:\/\/(?:www\.)?figma\.com\/(?:design|file|proto|board|figjam)\/[^\s<>"')\]]+/gi;

const MARKDOWN_IMAGE_RE = /!\[([^\]]*)\]\(([^)\s]+)(?:\s+"[^"]*")?\)/g;

const IMAGE_EXT_RE = /\.(png|jpe?g|webp|gif|bmp|svg)$/i;

const SENSITIVE_QUERY_KEYS = new Set([
  "access_token",
  "api_key",
  "apikey",
  "auth",
  "authorization",
  "code",
  "client_secret",
  "password",
  "secret",
  "sig",
  "signature",
  "token",
]);

export function isSupportedImageFile(file: Pick<File, "name" | "type">): boolean {
  return file.type.startsWith("image/") || IMAGE_EXT_RE.test(file.name);
}

export function extractFigmaLinks(text: string): string[] {
  const seen = new Set<string>();
  const links: string[] = [];
  for (const match of text.matchAll(FIGMA_LINK_RE)) {
    const link = match[0].replace(/[，。；;,.]+$/, "");
    if (seen.has(link)) continue;
    seen.add(link);
    links.push(link);
  }
  return links;
}

export function buildFigmaRawMaterial(url: string, source: string): string {
  const parsed = parseFigmaUrl(url);
  url = redactSensitiveUrlQueryParams(url);
  return [
    "[补充材料: Figma]",
    `来源: ${source}`,
    `链接: ${url}`,
    parsed.fileKey ? `file_key: ${parsed.fileKey}` : "",
    parsed.nodeId ? `node_id: ${parsed.nodeId}` : "",
    "读取状态: Figma 链接已接入本次评审上下文；评审会围绕链接对应原型检查页面状态、交互和验收口径。",
  ]
    .filter(Boolean)
    .join("\n");
}

export function buildImageRawMaterial(input: ImageRawMaterialInput): string {
  return [
    "[补充材料: 图片]",
    `来源: ${input.source}`,
    `文件名: ${input.name}`,
    `类型: ${input.mimeType || "unknown"}`,
    `大小: ${formatBytes(input.sizeBytes)}`,
    "读取状态: 图片附件已接入本次评审上下文；请在 PRD 正文或评审备注中保留关键页面状态、字段和验收口径。",
  ].join("\n");
}

export function extractMarkdownImageReferences(text: string): MarkdownImageReference[] {
  const seen = new Set<string>();
  const refs: MarkdownImageReference[] = [];
  for (const match of text.matchAll(MARKDOWN_IMAGE_RE)) {
    const alt = match[1] ?? "";
    const url = match[2] ?? "";
    if (!url || seen.has(url)) continue;
    seen.add(url);
    refs.push({ alt, url });
  }
  return refs;
}

export function buildImageReferenceRawMaterial(
  input: MarkdownImageReference & { source: string },
): string {
  input.url = redactSensitiveUrlQueryParams(input.url);
  return [
    "[补充材料: 图片]",
    `来源: ${input.source}`,
    input.alt ? `图片说明: ${input.alt}` : "",
    `引用地址: ${input.url}`,
    "读取状态: Markdown 图片引用已接入本次评审上下文；若是私有或相对路径图片，请同时上传原图以便评审。",
  ]
    .filter(Boolean)
    .join("\n");
}

export function mergeRawMaterials(current: readonly string[], additions: readonly string[]): string[] {
  const out: string[] = [];
  const seen = new Set<string>();
  for (const item of [...current, ...additions]) {
    const normalized = item.trim();
    if (!normalized || seen.has(normalized)) continue;
    seen.add(normalized);
    out.push(normalized);
  }
  return out;
}

export function summarizeRawMaterials(rawMaterials: readonly string[]): RawMaterialSummary {
  let images = 0;
  let figmaLinks = 0;
  for (const material of rawMaterials) {
    if (material.includes("[补充材料: 图片]")) images += 1;
    if (material.includes("[补充材料: Figma]")) figmaLinks += 1;
  }
  return {
    total: rawMaterials.length,
    images,
    figmaLinks,
  };
}

export function rawMaterialTitle(material: string): string {
  const kind = material.match(/^\[补充材料: ([^\]]+)\]/)?.[1] ?? "补充材料";
  const name =
    material.match(/^文件名: (.+)$/m)?.[1] ??
    material.match(/^链接: (.+)$/m)?.[1] ??
    material.slice(0, 36);
  return `${kind}: ${name}`;
}

function parseFigmaUrl(url: string): { fileKey: string; nodeId: string } {
  try {
    const parsed = new URL(url);
    const parts = parsed.pathname.split("/").filter(Boolean);
    const fileKey = parts[1] ?? "";
    const nodeId = (parsed.searchParams.get("node-id") ?? "").replace("-", ":");
    return { fileKey, nodeId };
  } catch {
    return { fileKey: "", nodeId: "" };
  }
}

function redactSensitiveUrlQueryParams(url: string): string {
  try {
    const parsed = new URL(url);
    for (const key of Array.from(parsed.searchParams.keys())) {
      if (SENSITIVE_QUERY_KEYS.has(key.toLowerCase())) {
        parsed.searchParams.set(key, "[REDACTED]");
      }
    }
    return parsed.toString().replaceAll("%5BREDACTED%5D", "[REDACTED]");
  } catch {
    return url;
  }
}

function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes <= 0) return "0 B";
  if (bytes < 1024) return `${Math.round(bytes)} B`;
  const kb = bytes / 1024;
  if (kb < 1024) return `${Number(kb.toFixed(1))} KB`;
  return `${Number((kb / 1024).toFixed(1))} MB`;
}
