/**
 * extractWorkerErrors · 把 SSE 流里散落的 worker_done.error 聚合成可渲染的 banner
 *
 * 触发 bug:Claude CLI 登录态过期,4 个 worker 全部 success=false / items_count=0,
 * 但前端老 UI 只看 items_count,显示"评审完成 0 条"误导用户。修法是把 error
 * 字段抽出来,按 not_logged_in / quota / other 分类成顶部 banner。
 *
 * 跑:cd web && pnpm test tests/extract-worker-errors.test.ts
 */

import { describe, it, expect } from "vitest";
import type { ReviewStreamEvent } from "@/lib/useReviewStream";
import { extractWorkerErrors } from "@/lib/v8-run-helpers";

// 真实样本(workspace-sample/output/sessions/rev_1777352680_bc901d.jsonl 里抓的)
// 后端 stream.py:115 把 result["error"] 截断到 200 字,这里取截断后的样子
const NOT_LOGGED_IN_ERROR =
  'claude -p 退出码 1: {"type":"result","subtype":"success","is_error":true,"api_error_status":null,"duration_ms":373,"duration_api_ms":0,"num_turns":1,"result":"Not logged in · Please run /login","stop_rea';

function workerDoneEvent(
  dimKey: string,
  dimName: string,
  error?: string,
): ReviewStreamEvent {
  return {
    event: "worker_done",
    progress: 50,
    dim_key: dimKey,
    dim_name: dimName,
    success: error == null,
    items_count: 0,
    ...(error ? { error } : {}),
  } as ReviewStreamEvent;
}

describe("extractWorkerErrors", () => {
  it("3 个 worker_done 都带 'Not logged in' → 1 个 not_logged_in banner,影响 3 个 dim", () => {
    const events: ReviewStreamEvent[] = [
      workerDoneEvent("structure", "结构", NOT_LOGGED_IN_ERROR),
      workerDoneEvent("ai_coding", "AI 编码", NOT_LOGGED_IN_ERROR),
      workerDoneEvent("data_quality", "数据质量", NOT_LOGGED_IN_ERROR),
    ];

    const banners = extractWorkerErrors(events);

    expect(banners).toHaveLength(1);
    const b = banners[0]!;
    expect(b.category).toBe("not_logged_in");
    expect(b.title).toContain("Claude CLI 未登录");
    expect(b.hint).toContain("claude login");
    expect(b.affectedDims).toHaveLength(3);
    expect(b.affectedDims.map((d) => d.dim).sort()).toEqual([
      "ai_coding",
      "data_quality",
      "structure",
    ]);
  });

  it("quota 关键词 → quota banner,文案提示额度耗尽", () => {
    const ev = workerDoneEvent(
      "structure",
      "结构",
      'claude -p 退出码 1: QuotaExhaustedError: hit your limit',
    );
    const banners = extractWorkerErrors([ev]);
    expect(banners).toHaveLength(1);
    expect(banners[0]!.category).toBe("quota");
    expect(banners[0]!.title).toContain("额度");
  });

  it("其他错误 → other banner,errorPreview 含 dim + error 前缀", () => {
    const ev = workerDoneEvent(
      "ai_coding",
      "AI 编码",
      "Connection timed out after 120s talking to upstream",
    );
    const banners = extractWorkerErrors([ev]);
    expect(banners).toHaveLength(1);
    const b = banners[0]!;
    expect(b.category).toBe("other");
    expect(b.affectedDims[0]!.dim).toBe("ai_coding");
    expect(b.errorPreview).toBeDefined();
    expect(b.errorPreview!).toContain("Connection timed out");
  });

  it("success worker / 无 error 字段 → 0 个 banner", () => {
    const events: ReviewStreamEvent[] = [
      workerDoneEvent("structure", "结构"),
      workerDoneEvent("quality", "质量"),
    ];
    expect(extractWorkerErrors(events)).toHaveLength(0);
  });

  it("同 dim + 同错误前缀重复出现 → dedupe 只保留 1 条", () => {
    const events: ReviewStreamEvent[] = [
      workerDoneEvent("structure", "结构", NOT_LOGGED_IN_ERROR),
      workerDoneEvent("structure", "结构", NOT_LOGGED_IN_ERROR),
    ];
    const banners = extractWorkerErrors(events);
    expect(banners).toHaveLength(1);
    expect(banners[0]!.affectedDims).toHaveLength(1);
  });

  it("混合 not_logged_in + quota → 2 个 banner,分别归类", () => {
    const events: ReviewStreamEvent[] = [
      workerDoneEvent("structure", "结构", NOT_LOGGED_IN_ERROR),
      workerDoneEvent("ai_coding", "AI 编码", "QuotaExhaustedError"),
    ];
    const banners = extractWorkerErrors(events);
    expect(banners).toHaveLength(2);
    const cats = banners.map((b) => b.category).sort();
    expect(cats).toEqual(["not_logged_in", "quota"]);
  });
});
