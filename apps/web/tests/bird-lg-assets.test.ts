import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const ROOT = process.cwd();

function readSource(path: string): string {
  return readFileSync(join(ROOT, path), "utf8");
}

describe("bird lg portrait assets", () => {
  it("maps all 10 birds to large portrait files", () => {
    const source = readSource("components/birds/BirdAvatar.tsx");

    for (const fileName of [
      "biz-lg.png",
      "data-lg.png",
      "ux-lg.png",
      "risk-lg.png",
      "goshawk-lg.png",
      "woodpecker-lg.png",
      "dove-lg.png",
      "cuckoo-lg.png",
      "kakapo-lg.png",
      "shrike-lg.png",
    ]) {
      expect(source).toContain(`/birds/${fileName}`);
      expect(existsSync(join(ROOT, "public", "birds", fileName))).toBe(true);
    }

    expect(source).toContain("Record<BirdId, string>");
    expect(source).toContain("id <= 10");
  });

  it("uses the editor-in-chief bird as the global brand mark", () => {
    const source = readSource("components/TopBanner.tsx");

    expect(source).toContain("<BirdAvatar");
    expect(source).toContain("id={6}");
    expect(source).not.toContain("内凹圆点");
  });

  it("uses one generated team illustration on the login page", () => {
    const source = readSource("app/login/LoginForm.tsx");

    expect(source).toContain("/illustrations/login-bird-team.jpg");
    expect(source).toContain("LoginBirdTeamIllustration");
    expect(existsSync(join(ROOT, "public", "illustrations", "login-bird-team.jpg"))).toBe(
      true,
    );
  });
});
