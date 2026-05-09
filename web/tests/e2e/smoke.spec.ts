/**
 * 啄木鸟 E2E smoke test · v8 适配
 *
 * 只验证"页面能开、核心元素在、导航能走"。不跑真实评审。
 * 断言用 role/heading/placeholder 这种 "结构性" 匹配,避开纯文本歧义。
 */

import { test, expect } from "@playwright/test";

test.describe("Pecker v8 smoke · 无后端依赖", () => {
  test("根路径渲染 v8 landing", async ({ page }) => {
    await page.goto("/");
    await expect(
      page.getByText("Pecker · PRD 评审工作台", { exact: true }),
    ).toBeVisible();
    await expect(
      page.getByRole("heading", { name: /提交前.*PRD.*查清楚/ }),
    ).toBeVisible();
    await expect(page.getByText(/重点检查目标范围/)).toBeVisible();
    await expect(
      page.getByRole("button", { name: /开始评审/ }),
    ).toBeVisible();
  });

  test("/login v8 工作台气质登录页", async ({ page }) => {
    await page.goto("/login");

    // h1
    await expect(page.getByRole("heading", { name: /^登录$/ })).toBeVisible();
    await expect(page.getByText(/PRD 评审工作台/)).toBeVisible();

    // 用 placeholder 定位 input(v8 Field 的 label 未用 htmlFor 关联)
    await expect(page.getByPlaceholder("晨舒")).toBeVisible();
    await expect(page.locator('input[type="password"]')).toBeVisible();

    // 登录 CTA
    await expect(
      page.getByRole("button", { name: /登录/ }),
    ).toBeVisible();
    await expect(page.getByText(/记住我/)).toBeVisible();
  });

  test("/about v8 agent 家族介绍", async ({ page }) => {
    await page.goto("/about");
    await expect(
      page.locator("main").getByText("使用说明", { exact: true }),
    ).toBeVisible();
    await expect(
      page.getByRole("heading", { name: /PRD 评审工作台怎么用/ }),
    ).toBeVisible();

    await expect(page.getByText("工具定位")).toBeVisible();
    await expect(page.getByText(/你只需要完成三件事/)).toBeVisible();
    await expect(page.getByText("长期维护能力")).toBeVisible();
  });

  test("/login 空密码 HTML5 required 阻止提交", async ({ page }) => {
    await page.goto("/login");
    await page.getByPlaceholder("晨舒").fill("smoke-test");
    await page.getByRole("button", { name: /登录/ }).click();
    // HTML5 required 拦住 · URL 不跳
    await expect(page).toHaveURL(/\/login/);
  });

  test("/not-found 404 页 · 啄木鸟困惑态 + 双 CTA", async ({ page }) => {
    const resp = await page.goto("/some-bogus-path-that-doesnt-exist");
    // Next 在 streamed 响应里返回 200,非 streamed 返回 404 — 两种都接受
    expect([200, 404]).toContain(resp?.status() ?? 0);
    await expect(page.getByText(/找不到这个页面/)).toBeVisible();
    await expect(
      page.getByRole("heading", { name: /啄木鸟也不知道你要找什么/ }),
    ).toBeVisible();
    await expect(page.getByRole("link", { name: /进入评审/ })).toBeVisible();
    await expect(page.getByRole("link", { name: /回首页/ })).toBeVisible();
  });

  test("TopBanner v8 · brand + 导航", async ({ page }) => {
    await page.goto("/login");
    // brand "Pecker"(exact 避开正文其他 Pecker)
    await expect(page.getByText("Pecker", { exact: true }).first()).toBeVisible();
    // PM 友好导航:普通未登录/非管理员视角不暴露后台治理入口
    await expect(page.getByRole("link", { name: /^评审记录$/ })).toBeVisible();
    await expect(page.getByRole("link", { name: /^使用说明$/ })).toBeVisible();
    await expect(page.getByRole("link", { name: /^Runs$/ })).toHaveCount(0);
    await expect(page.getByRole("link", { name: /^System$/ })).toHaveCount(0);
  });
});
