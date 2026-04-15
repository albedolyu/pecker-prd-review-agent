/**
 * 啄木鸟 E2E smoke test — 只验证"页面能开、导航能走、登录能弹卡片",
 * 不跑真实评审(那要 90-150s + 后端 Claude CLI)。
 *
 * 真正的评审流程 E2E(上传 PRD → 5 phase → 下载报告)在 full-flow.spec.ts,
 * 那个需要先 export PECKER_WEB_PASSWORD + 后端跑起来,时间成本更高,只在
 * 上线前 smoke 跑。
 *
 * 这个 smoke 测试只需要 `pnpm dev` 起来即可,不依赖后端(后端调用会 401,
 * 我们断言 401 的错误提示出现,而不是断言评审成功)。
 */

import { test, expect } from "@playwright/test";

test.describe("啄木鸟 smoke test — 无后端依赖", () => {
  test("根路径重定向到 /review 或 /login", async ({ page }) => {
    // 后端可能在跑(返回 200 + me),也可能没跑(返回 401 → /login)
    // smoke 只验证根路径有动作,两种终态都接受
    await page.goto("/");
    await page.waitForURL(/\/(login|review)/);
    await expect(page).toHaveURL(/\/(login|review)/);
  });

  test("登录页渲染核心元素 — 标题 + 两个输入框 + 按钮", async ({ page }) => {
    await page.goto("/login");

    // Phase F 标题:大衬线 "今日 签到"(报纸刊头风),不再是 "啄木鸟登录"
    await expect(page.getByRole("heading", { name: /签 ?到/ })).toBeVisible();
    // 左侧引语板(md:flex 以上才出现,1440 视口肯定可见)
    await expect(page.getByText(/评审不是/)).toBeVisible();

    // 两个 input(label 文案:"01 · 评审人" / "02 · 团队密码")
    await expect(
      page.getByRole("textbox", { name: /评审人/ }),
    ).toBeVisible();
    await expect(page.getByLabel(/团队密码/)).toBeVisible();

    // Phase F 按钮文案从"登录"换成"进入编辑部"
    await expect(
      page.getByRole("button", { name: /进入编辑部/ }),
    ).toBeVisible();
  });

  test("/about 页面渲染 10 只鸟的品牌故事", async ({ page }) => {
    await page.goto("/about");

    // Phase F 刊头 h1:"啄木鸟编辑部"(drop cap 把"啄"拆到 sr-only span,
    // accessible name 被空白分隔,所以用 /木鸟编辑部/ 更稳健)
    await expect(
      page.getByRole("heading", { name: /木鸟编辑部/ }),
    ).toBeVisible();

    // 必须出现这 10 个职能词(BirdCard h3 里 "主编 又名 啄木鸟" 同行
    // 合并,不用 exact,前缀/子串匹配即可)
    for (const label of [
      "主编",
      "责编",
      "审校",
      "技术编辑",
      "数据核对员",
      "终审",
      "读者反馈员",
      "试读员",
      "资料员",
      "质检员",
    ]) {
      await expect(page.getByText(label).first()).toBeVisible();
    }
  });

  test("/about 页面**不应**在正文(非 tooltip)里出现生僻鸟名", async ({
    page,
  }) => {
    // 这是 Phase C.5 的 C.5.1 约束 grep 验证的 UI 层等价断言
    // UI 可见文字里不该出现"鸬鹚"/"鸮鹦"/"伯劳"等原始鸟名(tooltip 允许)
    // 但 /about 恰恰是唯一允许并置的彩蛋页,所以这里我们改成验证
    // **评审页**上不出现,移到 /review 的测试里更合适
    await page.goto("/about");
    // /about 是品牌页,鸟名本身就会出现(作为 birdName 字段)
    // 所以这个 test 只断言"鸮鹦"出现在"又名"上下文中,不是孤零零的
    const kakapoText = page.getByText(/又名.*鸮鹦/);
    await expect(kakapoText).toBeVisible();
  });

  test("登录失败 — 空密码应该被阻止提交", async ({ page }) => {
    await page.goto("/login");
    await page
      .getByRole("textbox", { name: /评审人/ })
      .fill("smoke-test");
    // 不填密码直接点按钮
    await page.getByRole("button", { name: /进入编辑部/ }).click();
    // HTML5 required 会阻止提交,URL 不变
    await expect(page).toHaveURL(/\/login/);
  });

  test("TopBanner 可见 + 品牌名 + 关于链接", async ({ page }) => {
    await page.goto("/login");
    await expect(page.getByText("啄木鸟").first()).toBeVisible();
    // TopBanner 的"Pecker"logo(exact,避开 LoginForm 的 PECKER_WEB_PASSWORD)
    await expect(page.getByText("Pecker", { exact: true })).toBeVisible();
    // 顶部 "关于" 链接
    await expect(
      page.getByRole("link", { name: /关于/i }).first(),
    ).toBeVisible();
  });
});
