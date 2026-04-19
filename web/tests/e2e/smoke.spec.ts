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
      page.getByText("PRD Review · Agent Workbench · v8"),
    ).toBeVisible();
    await expect(
      page.getByRole("heading", { name: /10 只鸟.*PRD/ }),
    ).toBeVisible();
    await expect(
      page.getByRole("button", { name: /进入评审/ }),
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
    await expect(page.getByText("About · Agent 家族")).toBeVisible();
    await expect(
      page.getByRole("heading", { name: /啄木鸟编辑部/ }),
    ).toBeVisible();

    // 4 层分组标题
    await expect(page.getByRole("heading", { name: /^主控层$/ })).toBeVisible();
    await expect(
      page.getByRole("heading", { name: /Worker 层/ }),
    ).toBeVisible();
    await expect(
      page.getByRole("heading", { name: /Meta 层/ }),
    ).toBeVisible();
    await expect(
      page.getByRole("heading", { name: /Agent 协作拓扑/ }),
    ).toBeVisible();

    // 抽样 3 个职能词(不穷举,避免 brittle)
    for (const label of ["主编", "终审", "质检员"]) {
      await expect(page.getByText(label).first()).toBeVisible();
    }
  });

  test("/login 空密码 HTML5 required 阻止提交", async ({ page }) => {
    await page.goto("/login");
    await page.getByPlaceholder("晨舒").fill("smoke-test");
    await page.getByRole("button", { name: /登录/ }).click();
    // HTML5 required 拦住 · URL 不跳
    await expect(page).toHaveURL(/\/login/);
  });

  test("TopBanner v8 · brand + 导航", async ({ page }) => {
    await page.goto("/login");
    // brand "Pecker"(exact 避开正文其他 Pecker)
    await expect(page.getByText("Pecker", { exact: true }).first()).toBeVisible();
    // v8 新增入口
    await expect(page.getByRole("link", { name: /^Runs$/ })).toBeVisible();
    await expect(page.getByRole("link", { name: /^System$/ })).toBeVisible();
    await expect(page.getByRole("link", { name: /^关于$/ })).toBeVisible();
  });
});
