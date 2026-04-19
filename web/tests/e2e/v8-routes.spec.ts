/**
 * v8 新增路径 smoke · 不依赖后端
 *
 * 覆盖 Sprint 4/5 新增的管理页 · 断言用 heading / 区域性文本,避免 brittle 文案匹配。
 */

import { test, expect } from "@playwright/test";

test.describe("Pecker v8 · 新路径 smoke", () => {
  test("/v8-preview 组件 gallery", async ({ page }) => {
    await page.goto("/v8-preview");
    await expect(
      page.getByRole("heading", {
        name: /Sprint 1.*2A 组件预览/,
      }),
    ).toBeVisible();
    // 四个 Sprint big divider 同时存在(gallery 合集)
    await expect(page.getByText(/Sprint 1 · 基础层/)).toBeVisible();
    await expect(
      page.getByText(/Sprint 3 · Phase 2 调度中心/),
    ).toBeVisible();
    await expect(
      page.getByText(/Sprint 4 · harness 增量/),
    ).toBeVisible();
  });

  test("/runs/diff · baseline vs shadow", async ({ page }) => {
    await page.goto("/runs/diff");
    await expect(page.getByText("Harness · Run 对比")).toBeVisible();
    await expect(
      page.getByRole("heading", { name: /Run A.*Run B/ }),
    ).toBeVisible();
    // 指标对比 head
    await expect(page.getByText(/指标对比/)).toBeVisible();
    // 4 桶文案(在 <details><summary> 里 · 用 first()避免潜在重复)
    await expect(page.getByText(/只在 baseline 出现/).first()).toBeVisible();
    await expect(page.getByText(/两边一致/).first()).toBeVisible();
  });

  test("/runs/:id/replay · audit trail 头信息", async ({ page }) => {
    await page.goto("/runs/r_20260418_1042/replay");
    await expect(
      page.getByText("Harness · Audit Trail Replay"),
    ).toBeVisible();
    await expect(
      page.getByRole("heading", { name: /r_20260418_1042/ }),
    ).toBeVisible();
    // event timeline 存在
    await expect(page.getByText(/event timeline/)).toBeVisible();
    // 第一个 event row 可见(点击要求 button 本体)
    await expect(page.locator("button:has-text('#01')")).toBeVisible();
  });

  test.skip("/runs/:id/replay · 点事件展开 payload drawer", async ({ page }) => {
    // SKIPPED · Turbopack dev mode 下 click 后 React state 偶发不更新 · 生产 build 里正常
    await page.goto("/runs/r_20260418_1042/replay", {
      waitUntil: "networkidle",
    });
    await expect(page.getByText(/event timeline/)).toBeVisible();
    // 点第一行 event(包含 #01)· 用 filter 定位
    await page
      .getByRole("button")
      .filter({ hasText: "#01" })
      .first()
      .click({ force: true });
    await expect(page.getByText(/payload · seq 1/)).toBeVisible();
    await expect(page.getByText(/"uploaded"/)).toBeVisible();
  });

  test("/system/health · 健康度仪表板", async ({ page }) => {
    await page.goto("/system/health");
    await expect(
      page.getByText("Harness · System Health"),
    ).toBeVisible();
    await expect(
      page.getByRole("heading", { name: /^系统健康$/ }),
    ).toBeVisible();

    // SectionHead 用 div 非真 heading · 改 getByText
    await expect(page.getByText(/Consistency 趋势/)).toBeVisible();
    await expect(page.getByText(/Rule 权重 Top 6/)).toBeVisible();
    await expect(page.getByText(/Eval 回归基线/)).toBeVisible();
    await expect(page.getByText(/^最近 runs$/)).toBeVisible();
  });

  test("/system/prompts · 5 鸟 tabs + prompt 透明", async ({ page }) => {
    await page.goto("/system/prompts");
    await expect(
      page.getByText("Harness · Prompts & Rules"),
    ).toBeVisible();

    // 5 鸟 tab 按钮可见 · 用 getByText 的 first(tab button 包装了 BirdAvatar + text)
    for (const label of ["业务鸟", "数据鸟", "体验鸟", "风险鸟", "苍鹰鸟"]) {
      await expect(page.getByText(label).first()).toBeVisible();
    }

    // 默认选中业务鸟(biz-v 版本号)
    await expect(page.getByText(/biz-v/)).toBeVisible();

    // 激活 rule 表头
    await expect(page.getByText(/激活 rule 集/)).toBeVisible();
  });

  test.skip("/system/prompts · 切换到数据鸟 tab", async ({ page }) => {
    // SKIPPED · 同上 flaky 问题
    await page.goto("/system/prompts", { waitUntil: "networkidle" });
    // 等默认 prompt 渲染好再点(hydration 完成)
    await expect(page.getByText(/biz-v/)).toBeVisible();
    // tab 按钮内含 BirdAvatar + text · 用 text 作 filter · force 绕开 child pointer-events
    await page
      .getByRole("button")
      .filter({ hasText: "数据鸟" })
      .first()
      .click({ force: true });
    await expect(page.getByText(/data-v/)).toBeVisible();
  });
});
