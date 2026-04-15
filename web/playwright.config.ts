import { defineConfig, devices } from "@playwright/test";

/**
 * Playwright 配置 — Phase E1 / E3 / E7 的 E2E + 视觉回归
 *
 * 运行前置:
 * 1. 安装浏览器二进制: `pnpm exec playwright install chromium`
 * 2. 跑起后端: `uvicorn api.main:app --port 8000`
 * 3. 跑起前端: `pnpm dev --port 3000`
 *
 * 然后:
 *   - 全量:     `pnpm exec playwright test`
 *   - 更新 baseline:  `pnpm exec playwright test --update-snapshots`
 *   - 单个文件: `pnpm exec playwright test tests/e2e/smoke.spec.ts`
 *
 * CI 里会先启 dev server(webServer 配置项),但本地开发我们手动管。
 */

export default defineConfig({
  testDir: "./tests/e2e",
  fullyParallel: false, // 单后端 semaphore=2,并行跑容易 429

  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : 1,

  reporter: process.env.CI ? "github" : "list",

  use: {
    baseURL: process.env.PECKER_WEB_BASE_URL ?? "http://127.0.0.1:3000",
    trace: "on-first-retry",
    screenshot: "only-on-failure",
  },

  projects: [
    {
      name: "chromium-desktop",
      use: {
        ...devices["Desktop Chrome"],
        viewport: { width: 1440, height: 900 },
      },
    },
  ],

  // 视觉回归阈值:像素差异超过 5% 失败
  expect: {
    toHaveScreenshot: {
      maxDiffPixelRatio: 0.05,
    },
  },
});
