/**
 * Team-facing route smoke tests.
 *
 * These checks follow the default internal-team UI:
 * - component preview stays hidden unless the maintainer flag is enabled
 * - regular PMs see personal review history, not internal run comparison
 * - maintenance pages render the admin guard when reached directly
 */

import { test, expect } from "@playwright/test";

test.describe("Pecker team-facing route smoke", () => {
  test("/v8-preview is closed by default", async ({ page }) => {
    await page.goto("/v8-preview");
    await expect(
      page.getByRole("heading", { name: /组件预览未开放/ }),
    ).toBeVisible();
    await expect(page.getByRole("link", { name: /返回评审工作台/ })).toBeVisible();
  });

  test("/runs/diff shows personal review history by default", async ({
    page,
  }) => {
    await page.goto("/runs/diff");
    await expect(
      page.getByRole("heading", { name: /我的评审记录/ }),
    ).toBeVisible();
    await expect(page.getByText(/不展示 PRD 正文/)).toBeVisible();
  });

  test("/runs/:id/replay is admin-only by default", async ({ page }) => {
    await page.goto("/runs/r_20260418_1042/replay");
    await expect(
      page.getByRole("heading", {
        name: /正在确认权限|暂时无法确认权限|这个页面仅管理员可见/,
      }),
    ).toBeVisible();
  });

  test("/system/health is admin-only by default", async ({ page }) => {
    await page.goto("/system/health");
    await expect(
      page.getByRole("heading", {
        name: /正在确认权限|暂时无法确认权限|这个页面仅管理员可见/,
      }),
    ).toBeVisible();
  });

  test("/system/prompts is admin-only by default", async ({ page }) => {
    await page.goto("/system/prompts");
    await expect(
      page.getByRole("heading", {
        name: /正在确认权限|暂时无法确认权限|这个页面仅管理员可见/,
      }),
    ).toBeVisible();
  });
});
