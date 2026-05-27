import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const ROOT = process.cwd();

function readSource(path: string): string {
  return readFileSync(join(ROOT, path), "utf8");
}

describe("PM-friendly navigation copy", () => {
  it("does not expose backend route names in primary navigation", () => {
    const source = readSource("components/TopBanner.tsx");

    expect(source).toContain("评审记录");
    expect(source).toContain("质量看板");
    expect(source).toContain("me?.is_admin");
    expect(source).not.toContain(">Runs<");
    expect(source).not.toContain(">System<");
  });

  it("uses PM-facing titles for run and system workbench pages", () => {
    const runDiff = readSource("app/runs/diff/page.tsx");
    const replayPage = readSource("app/runs/[id]/replay/page.tsx");
    const health = readSource("app/system/health/page.tsx");
    const prompts = readSource("app/system/prompts/page.tsx");
    const usage = readSource("app/system/usage/page.tsx");

    expect(runDiff).toContain("两次评审对比");
    expect(runDiff).toContain("NEXT_PUBLIC_ENABLE_INTERNAL_RUNS");
    expect(runDiff).toContain("我的评审记录");
    expect(runDiff).toContain("不展示 PRD 正文");
    expect(runDiff).toContain("reviewHistoryApi");
    expect(runDiff).not.toContain("Harness · Run 对比");
    expect(runDiff).not.toContain("Run A ↔ Run B");
    expect(replayPage).toContain("AdminOnlyPage");

    expect(health).toContain("评审质量看板");
    expect(health).toContain("最近评审");
    expect(health).toContain("AdminOnlyPage");
    expect(health).toContain("目标线");
    expect(health).toContain("30 天前");
    expect(health).toContain("今天");
    expect(health).toContain('["样例", "得分", "变化"]');
    expect(health).not.toContain("Harness · System Health");
    expect(health).not.toContain("最近 runs");
    expect(health).not.toContain("prompts & rules");
    expect(health).not.toContain("threshold {threshold.toFixed");
    expect(health).not.toContain(">today<");

    expect(prompts).toContain("评审规则配置");
    expect(prompts).toContain("AdminOnlyPage");
    expect(prompts).toContain("更新于");
    expect(prompts).not.toContain("Harness · Prompts & Rules");
    expect(prompts).not.toContain("Prompt / Rule 透明度");
    expect(prompts).not.toContain("updated {prompt.updated}");

    expect(usage).toContain("AdminOnlyPage");
  });

  it("makes PM decision feedback filterable for admin follow-up", () => {
    const usage = readSource("app/system/usage/page.tsx");
    const api = readSource("lib/api.ts");

    expect(usage).toContain("FEEDBACK_ACTION_OPTIONS");
    expect(usage).toContain("全部反馈");
    expect(usage).toContain("只看驳回");
    expect(usage).toContain("只看改写");
    expect(usage).toContain("adminUsageApi.feedback(days, { action: feedbackAction })");
    expect(usage).toContain("FeedbackBreakdown");
    expect(usage).toContain("按同事看");
    expect(usage).toContain("按资料库看");
    expect(api).toContain("AdminFeedbackFilters");
    expect(api).toContain('filters.action && filters.action !== "all"');
  });

  it("does not expose legacy Claude model names in PM-facing surfaces", () => {
    const visibleSources = [
      readSource("lib/roles.ts"),
      readSource("app/system/prompts/page.tsx"),
      readSource("components/phases/Phase1Precheck.tsx"),
      readSource("components/phases/Phase2Running.tsx"),
      readSource("components/phases/Phase2RunningV8.tsx"),
      readSource("components/run/AgentStatusCard.tsx"),
      readSource("lib/v8-run-helpers.ts"),
    ].join("\n");

    expect(visibleSources).toContain("gpt-5.5");
    expect(visibleSources).not.toContain("sonnet-4-6");
    expect(visibleSources).not.toContain("opus-4");
    expect(visibleSources).not.toContain("Opus");
    expect(visibleSources).not.toContain("Claude Sonnet");
    expect(visibleSources).not.toContain("Claude CLI 配额已用完");
  });

  it("does not promise a fixed 10-15 second wait for precheck", () => {
    const precheckSources = [
      readSource("components/phases/Phase1Precheck.tsx"),
      readSource("components/phases/Phase1PrecheckV8.tsx"),
    ].join("\n");

    expect(precheckSources).not.toContain("10-15 秒");
    expect(precheckSources).not.toContain("~15s");
    expect(precheckSources).toContain("通常几十秒内完成");
    expect(precheckSources).toContain("资料库较大或服务繁忙时会更久");
    expect(precheckSources).toContain("重新预检");
    expect(precheckSources).not.toMatch(/>\s*重试\s*</);
  });

  it("keeps legacy fallback pages away from backend storage and token wording", () => {
    const fallbackSources = [
      readSource("components/phases/Phase1Precheck.tsx"),
      readSource("components/phases/Phase4Report.tsx"),
    ].join("\n");

    expect(fallbackSources).toContain("资料库");
    expect(fallbackSources).not.toContain("wiki 内容缺失");
    expect(fallbackSources).not.toContain("保存到 wiki");
    expect(fallbackSources).not.toContain("只读用户不能保存 wiki");
    expect(fallbackSources).not.toContain("K in");
    expect(fallbackSources).not.toContain("K out");
  });

  it("keeps the run detail console collapsed behind PM-friendly wording", () => {
    const phase2 = readSource("components/phases/Phase2RunningV8.tsx");

    expect(phase2).toContain("查看处理明细");
    expect(phase2).toContain("收起处理明细");
    expect(phase2).toContain("需要复盘时可查看每个阶段的处理记录");
    expect(phase2).not.toContain("展开 console");
    expect(phase2).not.toContain("debug log");
    expect(phase2).not.toContain("排障时可展开");
  });

  it("keeps replay page wording away from audit-log implementation terms", () => {
    const replayPage = readSource("app/runs/[id]/replay/page.tsx");

    expect(replayPage).toContain("过程明细");
    expect(replayPage).toContain("查看处理原始记录");
    expect(replayPage).not.toContain("排障原始记录");
    expect(replayPage).not.toContain("复盘和排障");
    expect(replayPage).not.toContain("payload(JSON)");
    expect(replayPage).not.toContain(">seq <");
    expect(replayPage).not.toContain("Run Replay");
  });

  it("keeps the component preview page behind an explicit maintainer flag", () => {
    const previewPage = readSource("app/v8-preview/page.tsx");

    expect(previewPage).toContain("NEXT_PUBLIC_ENABLE_V8_PREVIEW");
    expect(previewPage).toContain("组件预览未开放");
    expect(previewPage).toContain("<V8PreviewGallery />");
  });

  it("keeps e2e smoke coverage aligned with the team-facing UI", () => {
    const e2eSources = [
      readSource("tests/e2e/v8-routes.spec.ts"),
      readSource("tests/e2e/bird-portrait-check.spec.ts"),
      readSource("tests/e2e/responsive-qa.spec.ts"),
    ].join("\n");

    expect(e2eSources).not.toContain("Harness ·");
    expect(e2eSources).not.toContain("event timeline");
    expect(e2eSources).not.toContain("/v8-preview 组件 gallery");
    expect(e2eSources).not.toContain("v8-preview-1440px.png");
    expect(e2eSources).not.toContain(
      '{ name: "v8-preview", url: "/v8-preview" }',
    );
  });

  it("persists PM missing-report feedback instead of leaving it in console placeholders", () => {
    const feedbackSources = [
      readSource("lib/api.ts"),
      readSource("components/phases/Phase3ConfirmV8.tsx"),
      readSource("components/phases/Phase4ReportV8.tsx"),
    ].join("\n");

    expect(feedbackSources).toContain("feedbackApi");
    expect(feedbackSources).toContain("reportMissing");
    expect(feedbackSources).not.toContain("[harness · missing-report]");
    expect(feedbackSources).not.toContain("console.log(\"[harness");
  });

  it("uses PM-facing wording in shared step and progress components", () => {
    const sharedSources = [
      readSource("components/PhaseStepper.tsx"),
      readSource("components/ProgressRail.tsx"),
    ].join("\n");

    expect(sharedSources).toContain("选资料库");
    expect(sharedSources).toContain("读取资料");
    expect(sharedSources).toContain("分向评审");
    expect(sharedSources).toContain("当前进度");
    expect(sharedSources).not.toContain("选 workspace");
    expect(sharedSources).not.toContain("扫 wiki");
    expect(sharedSources).not.toContain("Stage");
    expect(sharedSources).not.toContain("4 位编辑");
  });

  it("sets realistic review-time expectations on upload pages", () => {
    const uploadSources = [
      readSource("components/phases/Phase0Upload.tsx"),
      readSource("components/phases/Phase0UploadV8.tsx"),
      readSource("lib/review-eta.ts"),
    ].join("\n");

    expect(uploadSources).toContain("estimateReviewEtaLabel");
    expect(uploadSources).toContain("通常 3-8 分钟");
    expect(uploadSources).toContain("材料较长时会更久");
    expect(uploadSources).not.toContain("预计 10 分钟");
    expect(uploadSources).not.toContain("≈ 10 分钟");
    expect(uploadSources).not.toContain("全 sonnet");
    expect(uploadSources).not.toContain("~90-150 秒");
    expect(uploadSources).not.toContain("workspace 决定 wiki");
    expect(uploadSources).not.toContain("<Label htmlFor=\"ws\">Workspace</Label>");
    expect(uploadSources).not.toContain("选择一个 workspace");
    expect(uploadSources).not.toContain("wiki {w.wiki_page_count}");
    expect(uploadSources).not.toContain("输入新资料库名(如 workspace-");
  });

  it("tells PMs that draft restore avoids rerunning the review after refresh", () => {
    const uploadPage = readSource("components/phases/Phase0UploadV8.tsx");
    const legacyUploadPage = readSource("components/phases/Phase0Upload.tsx");

    expect(uploadPage).toContain("如果刚才断网或刷新");
    expect(uploadPage).toContain("不用重新跑评审");
    expect(uploadPage).toContain("继续上次评审");
    expect(legacyUploadPage).toContain("进度: ${phaseLabel(draft.phase)}");
    expect(legacyUploadPage).toContain("进度 {phaseLabel(draft.phase)}");
    expect(legacyUploadPage).not.toContain("Phase ${draft.phase}");
    expect(legacyUploadPage).not.toContain("Phase {draft.phase}");
  });

  it("keeps running pages aligned with PM-facing review wording", () => {
    const runningPage = readSource("components/phases/Phase2Running.tsx");
    const runningV8Page = readSource("components/phases/Phase2RunningV8.tsx");

    expect(runningPage).toContain("四个方向并行检查");
    expect(runningPage).toContain("部分方向返回不完整");
    expect(runningPage).not.toContain("4 Workers");
    expect(runningPage).not.toContain("预计 90–150 秒");
    expect(runningPage).not.toContain("超时 - 走空兜底");
    expect(runningPage).not.toContain("JSON 解析失败 + 重试无效");
    expect(runningPage).not.toContain("建议重试");
    expect(runningPage).not.toContain("给维护人看的错误原文");
    expect(runningV8Page).not.toContain("给维护人看的错误原文");
    expect(runningPage).not.toContain("we.error.slice");
    expect(runningV8Page).not.toContain("{banner.errorPreview}");
    expect(runningPage).not.toContain('<span className="font-mono">{we.dim}</span>');
  });

  it("uses report-preview wording instead of markdown jargon on report pages", () => {
    const reportPage = [
      readSource("components/phases/Phase4Report.tsx"),
      readSource("components/phases/Phase4ReportV8.tsx"),
      readSource("components/demo/ReviewDemoFlow.tsx"),
    ].join("\n");

    expect(reportPage).toContain("完整报告预览");
    expect(reportPage).toContain("下载评审报告");
    expect(reportPage).not.toContain("完整 markdown");
    expect(reportPage).not.toContain("Markdown 预览");
    expect(reportPage).not.toContain("导出 Markdown");
    expect(reportPage).not.toContain("title=\"下载 .md\"");
    expect(reportPage).not.toContain("下载 md / 保存 wiki");
    expect(reportPage).not.toContain("不走后端");
    expect(reportPage).not.toContain("FEISHU_APP_ID");
    expect(reportPage).not.toContain("APP_SECRET");
    expect(reportPage).not.toContain("CHAT_ID");
    expect(reportPage).not.toContain("msg_id=");
    expect(reportPage).not.toContain("消息号");
  });

  it("keeps the test-handoff summary readable for PMs", () => {
    const reportPage = readSource("components/phases/Phase4ReportV8.tsx");

    expect(reportPage).toContain("测试用例准备度");
    expect(reportPage).toContain("暂不适合生成");
    expect(reportPage).toContain("部分可生成");
    expect(reportPage).toContain("可生成测试用例");
    expect(reportPage).toContain("可直接处理");
    expect(reportPage).toContain("需研发一起看");
    expect(reportPage).not.toContain("PM 默认");
    expect(reportPage).not.toContain("工程展开");
    expect(reportPage).not.toContain("下载交接包");
  });

  it("uses PM-facing wording for report confidence review details", () => {
    const reportPage = readSource("components/phases/Phase4ReportV8.tsx");

    expect(reportPage).toContain("结果复核说明");
    expect(reportPage).toContain("保留少数意见");
    expect(reportPage).not.toContain("评审治理摘要");
    expect(reportPage).not.toContain("少数派");
  });

  it("keeps legacy report run details PM-facing and hides token cost details", () => {
    const reportPage = readSource("components/phases/Phase4Report.tsx");

    expect(reportPage).toContain("<details");
    expect(reportPage).toContain("运行记录");
    expect(reportPage).toContain("处理耗时");
    expect(reportPage).not.toContain("tokens_in");
    expect(reportPage).not.toContain("tokens_out");
    expect(reportPage).not.toContain("成本归因");
    expect(reportPage).not.toContain("维护人排障信息");
  });

  it("uses Chinese fallback names in the admin usage dashboard", () => {
    const usagePage = readSource("app/system/usage/page.tsx");
    const apiTypes = readSource("lib/api.ts");

    expect(usagePage).toContain("未署名");
    expect(usagePage).toContain("PM 补充线索");
    expect(usagePage).toContain("只展示线索摘要和位置，不展示 PRD 正文");
    expect(usagePage).toContain("recent_job_events");
    expect(usagePage).toContain("最近处理轨迹");
    expect(apiTypes).toContain("active_drafts");
    expect(apiTypes).not.toContain("tokens_in?: number");
    expect(apiTypes).not.toContain("tokens_out?: number");
    expect(apiTypes).not.toContain("input_tokens?: number");
    expect(apiTypes).not.toContain("output_tokens?: number");
    expect(usagePage).toContain("进行中的草稿");
    expect(usagePage).not.toContain('|| "unknown"');
  });

  it("shows safe run diagnostics for active drafts in the admin usage dashboard", () => {
    const usagePage = readSource("app/system/usage/page.tsx");
    const apiTypes = readSource("lib/api.ts");

    expect(apiTypes).toContain("duration_ms?: number");
    expect(apiTypes).toContain("orchestrator?: string");
    expect(apiTypes).toContain("recovered_workers?: number");
    expect(apiTypes).toContain("context_packet_workers?: number");
    expect(usagePage).toContain("formatDraftRunMeta(draft)");
    expect(usagePage).toContain("recovered_workers");
    expect(usagePage).toContain("context_packet_workers");
    expect(usagePage).not.toContain("internal detail");
  });

  it("distinguishes admin guard auth errors from non-admin access", () => {
    const adminGuard = readSource("components/auth/AdminOnlyPage.tsx");

    expect(adminGuard).toContain("isError");
    expect(adminGuard).toContain("暂时无法确认权限");
    expect(adminGuard).toContain("请刷新页面后再试");
  });

  it("uses PM decision verbs on the per-item confirmation page", () => {
    const confirmPage = readSource("components/phases/Phase3ConfirmV8.tsx");

    expect(confirmPage).toContain("采纳");
    expect(confirmPage).toContain("驳回");
    expect(confirmPage).toContain("改写");
    expect(confirmPage).not.toContain(">接受<");
    expect(confirmPage).not.toContain(">拒绝<");
    expect(confirmPage).not.toContain(">编辑<");
    expect(confirmPage).not.toContain("已接受");
    expect(confirmPage).not.toContain("已拒绝");
  });

  it("does not promise per-direction retry when the retry action reruns the review", () => {
    const healthCheck = readSource("components/run/RunHealthCheck.tsx");
    const statusCard = readSource("components/run/AgentStatusCard.tsx");

    expect(healthCheck).toContain("重新评审");
    expect(statusCard).toContain("重新评审");
    expect(statusCard).not.toMatch(/>\s*重跑\s*</);
    expect(healthCheck).not.toContain("重跑异常方向");
    expect(healthCheck).not.toContain("重跑前请确认额度");
  });

  it("keeps the V8 running page away from technical retry wording", () => {
    const runningV8 = readSource("components/phases/Phase2RunningV8.tsx");

    expect(runningV8).toContain("重新评审");
    expect(runningV8).toContain("返回上一步");
    expect(runningV8).toContain("pmFacingReviewMessage(e.message)");
    expect(runningV8).not.toContain("继续确认还是重跑");
    expect(runningV8).not.toContain("未知错误,请重试");
    expect(runningV8).not.toContain("未知错误，请重试");
  });

  it("uses PM-facing wording on the public landing page", () => {
    const landing = readSource("app/ForestLanding.tsx");

    expect(landing).toContain("重新评审");
    expect(landing).not.toContain("提醒重跑");
  });

  it("keeps login timeout copy away from backend-service wording", () => {
    const api = readSource("lib/api.ts");

    expect(api).toContain("评审服务");
    expect(api).not.toContain("后端服务");
  });
});
