/**
 * 一次性截图脚本 · 验证 hand-drawn lg 头像正确渲染。
 * 跑完看 test-results 下截图。
 */

import { test } from "@playwright/test";

test("bird portraits visible on /about", async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/about", { waitUntil: "networkidle" });
  await page.waitForTimeout(500);
  await page.screenshot({
    path: testInfo.outputPath("about-1440px.png"),
    fullPage: true,
  });
});

test("bird portraits visible on /v8-preview", async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/v8-preview", { waitUntil: "networkidle" });
  await page.waitForTimeout(500);
  await page.screenshot({
    path: testInfo.outputPath("v8-preview-1440px.png"),
    fullPage: true,
  });
});
