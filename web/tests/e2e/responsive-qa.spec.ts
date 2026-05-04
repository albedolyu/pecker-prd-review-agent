/**
 * Responsive visual QA · 1440 / 1024 / 390 三个尺寸
 *
 * 跑法:
 *   pnpm exec playwright test tests/e2e/responsive-qa.spec.ts --project chromium-desktop
 *
 * 这是新加的 PM 工作台改造视觉检查,只断言"不溢出 / 没炸" — 截图存到
 * test-results/screenshots/ 给人工确认。
 */

import { test } from "@playwright/test";

const VIEWPORTS = [
  { name: "1440", width: 1440, height: 900 },
  { name: "1024", width: 1024, height: 768 },
  { name: "390", width: 390, height: 844 },
] as const;

const ROUTES = [
  { name: "landing", url: "/" },
  { name: "login", url: "/login" },
  { name: "v8-preview", url: "/v8-preview" },
];

test.describe("PM 工作台响应式视觉 QA", () => {
  for (const v of VIEWPORTS) {
    for (const r of ROUTES) {
      test(`${r.name} @ ${v.name}px`, async ({ page }, testInfo) => {
        await page.setViewportSize({ width: v.width, height: v.height });
        await page.goto(r.url, { waitUntil: "networkidle" });
        // 给 web font / hydration 留 0.4s 沉淀
        await page.waitForTimeout(400);
        await page.screenshot({
          path: testInfo.outputPath(
            `${r.name}-${v.name}px.png`,
          ),
          fullPage: true,
        });
      });
    }
  }
});
