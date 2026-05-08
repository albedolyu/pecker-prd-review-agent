import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const ROOT = process.cwd();

function readSource(path: string): string {
  return readFileSync(join(ROOT, path), "utf8");
}

describe("workspace entry", () => {
  it("keeps a path from selected workspace back to creating a new workspace", () => {
    const source = readSource("components/phases/Phase0UploadV8.tsx");

    expect(source).toContain("customWorkspaceMode");
    expect(source).toContain("setCustomWorkspaceMode(true)");
    expect(source).toContain('setUserInput({ workspace: "" })');
    expect(source).toContain("showCustomWorkspaceInput");
  });

  it("keeps the same workspace escape hatch in the legacy upload component", () => {
    const source = readSource("components/phases/Phase0Upload.tsx");

    expect(source).toContain("customWorkspaceMode");
    expect(source).toContain("setCustomWorkspaceMode(true)");
    expect(source).toContain('setUserInput({ workspace: "" })');
    expect(source).toContain("showCustomWorkspaceInput");
  });
});
