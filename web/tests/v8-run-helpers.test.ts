/**
 * v8-run-helpers 的单元测试 · 纯函数全覆盖
 *
 * 跑:cd web && pnpm vitest run
 */

import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import {
  ROLE_TO_BIRD_ID,
  roleToBird,
  isAllWorkersDone,
  classifyFailure,
  classifyFailReason,
  inferProgress,
  formatElapsed,
  formatTokens,
  formatDuration,
  modelForRole,
  deriveRunObservability,
  computeDiff,
} from "@/lib/v8-run-helpers";
import type { ReviewStreamEvent, WorkerDoneEvent } from "@/lib/useReviewStream";
import type { ReviewResult } from "@/lib/api";
import type { AgentStatus } from "@/components/run/AgentStatusCard";
import type { RoleKey } from "@/lib/roles";
import type { RunItemSummary } from "@/components/run/RunDiff";

// ============================================================
// RoleKey → BirdId 映射完整性

describe("ROLE_TO_BIRD_ID", () => {
  it("10 个 RoleKey 全覆盖", () => {
    const keys: RoleKey[] = [
      "editor-in-chief",
      "structure",
      "quality",
      "ai_coding",
      "data_quality",
      "final-reviewer",
      "reader-feedback",
      "sample-reader",
      "archivist",
      "qa-gatekeeper",
    ];
    for (const k of keys) {
      const id = ROLE_TO_BIRD_ID[k];
      expect(id).toBeGreaterThanOrEqual(1);
      expect(id).toBeLessThanOrEqual(10);
    }
  });

  it("4 worker + 1 苍鹰占了 1-5 位", () => {
    expect(ROLE_TO_BIRD_ID.structure).toBe(1); // 业务
    expect(ROLE_TO_BIRD_ID.data_quality).toBe(2); // 数据
    expect(ROLE_TO_BIRD_ID.quality).toBe(3); // 体验
    expect(ROLE_TO_BIRD_ID.ai_coding).toBe(4); // 风险
    expect(ROLE_TO_BIRD_ID["final-reviewer"]).toBe(5); // 苍鹰 meta
  });

  it("后台 4 鸟 + orchestrator 占 6-10", () => {
    const backgroundIds = new Set([
      ROLE_TO_BIRD_ID["editor-in-chief"],
      ROLE_TO_BIRD_ID["reader-feedback"],
      ROLE_TO_BIRD_ID["sample-reader"],
      ROLE_TO_BIRD_ID.archivist,
      ROLE_TO_BIRD_ID["qa-gatekeeper"],
    ]);
    expect(backgroundIds.size).toBe(5);
    for (const id of backgroundIds) {
      expect(id).toBeGreaterThanOrEqual(6);
    }
  });

  it("roleToBird 等价于 ROLE_TO_BIRD_ID lookup", () => {
    expect(roleToBird("structure")).toBe(ROLE_TO_BIRD_ID.structure);
    expect(roleToBird("final-reviewer")).toBe(
      ROLE_TO_BIRD_ID["final-reviewer"],
    );
  });
});

// ============================================================
// isAllWorkersDone

describe("isAllWorkersDone", () => {
  const build = (...states: AgentStatus[]): Map<RoleKey, AgentStatus> => {
    const keys: RoleKey[] = [
      "structure",
      "quality",
      "ai_coding",
      "data_quality",
    ];
    return new Map(keys.map((k, i) => [k, states[i] ?? "queued"]));
  };

  it("全 done 返回 true", () => {
    expect(isAllWorkersDone(build("done", "done", "done", "done"))).toBe(
      true,
    );
  });

  it("done + failed 混合也算全部离开运行态", () => {
    expect(
      isAllWorkersDone(build("done", "failed", "done", "failed")),
    ).toBe(true);
  });

  it("有 running 返回 false", () => {
    expect(
      isAllWorkersDone(build("done", "running", "done", "done")),
    ).toBe(false);
  });

  it("有 queued 返回 false", () => {
    expect(
      isAllWorkersDone(build("done", "done", "queued", "done")),
    ).toBe(false);
  });

  it("空 map 返回 true(vacuous truth)", () => {
    expect(isAllWorkersDone(new Map())).toBe(true);
  });
});

// ============================================================
// classifyFailure

describe("classifyFailure", () => {
  const mkEv = (partial: Partial<WorkerDoneEvent>): WorkerDoneEvent => ({
    event: "worker_done",
    progress: null,
    dim_key: "structure",
    dim_name: "结构层",
    success: true,
    items_count: 5,
    ...partial,
  });

  it("timeout 优先级最高", () => {
    expect(
      classifyFailure(mkEv({ timeout: true, success: false, error: "json parse" })),
    ).toBe("timeout");
  });

  it("degraded 映射到 json_parse_error", () => {
    expect(
      classifyFailure(mkEv({ degraded: true, success: false })),
    ).toBe("json_parse_error");
  });

  it("error 含 'quota' → quota_exhausted", () => {
    expect(
      classifyFailure(
        mkEv({
          success: false,
          error: "Anthropic quota exhausted, please try again later",
        }),
      ),
    ).toBe("quota_exhausted");
  });

  it("error 含 'rate limit' → quota_exhausted", () => {
    expect(
      classifyFailure(
        mkEv({ success: false, error: "HTTP 429 rate limit hit" }),
      ),
    ).toBe("quota_exhausted");
  });

  it("error 含 'tool' → tool_call_failed", () => {
    expect(
      classifyFailure(
        mkEv({ success: false, error: "tool invocation failed with 500" }),
      ),
    ).toBe("tool_call_failed");
  });

  it("error 含 'json' → json_parse_error", () => {
    expect(
      classifyFailure(
        mkEv({ success: false, error: "invalid json from model" }),
      ),
    ).toBe("json_parse_error");
  });

  it("error 含 'empty' → empty_submission", () => {
    expect(
      classifyFailure(
        mkEv({ success: false, error: "empty submission received" }),
      ),
    ).toBe("empty_submission");
  });

  it("success + items_count=0 → empty_submission(静默失败)", () => {
    expect(classifyFailure(mkEv({ success: true, items_count: 0 }))).toBe(
      "empty_submission",
    );
  });

  it("兜底 tool_call_failed", () => {
    expect(
      classifyFailure(
        mkEv({ success: false, error: "something unexpected" }),
      ),
    ).toBe("tool_call_failed");
  });

  it("classifyFailReason 与 classifyFailure 字面量等价", () => {
    const ev = mkEv({ success: false, error: "quota" });
    expect(classifyFailReason(ev)).toBe(classifyFailure(ev));
  });
});

// ============================================================
// inferProgress

describe("inferProgress", () => {
  it("没 event 时返回 35", () => {
    expect(inferProgress(undefined)).toBe(35);
  });

  it("有 event 时返回 80", () => {
    expect(
      inferProgress({
        event: "worker_done",
        progress: null,
        dim_key: "structure",
        dim_name: "结构层",
        success: true,
        items_count: 5,
      }),
    ).toBe(80);
  });
});

// ============================================================
// 格式化

describe("formatElapsed", () => {
  it("< 60s", () => {
    expect(formatElapsed(0)).toBe("0s");
    expect(formatElapsed(59)).toBe("59s");
  });
  it(">= 60s 分钟补零", () => {
    expect(formatElapsed(60)).toBe("1m00s");
    expect(formatElapsed(125)).toBe("2m05s");
    expect(formatElapsed(599)).toBe("9m59s");
  });
});

describe("formatTokens", () => {
  it("undefined 输入返回 undefined", () => {
    expect(formatTokens(undefined)).toBeUndefined();
  });
  it("空 token 返回 undefined", () => {
    expect(formatTokens({ tokens_in: 0, tokens_out: 0 })).toBeUndefined();
  });
  it("< 1k 用整数", () => {
    expect(formatTokens({ tokens_in: 200, tokens_out: 300 })).toBe("500");
  });
  it(">= 1k 用 k 后缀 + 1 位小数", () => {
    expect(formatTokens({ tokens_in: 600, tokens_out: 500 })).toBe("1.1k");
    expect(formatTokens({ tokens_in: 10000, tokens_out: 500 })).toBe("10.5k");
  });
});

describe("deriveRunObservability", () => {
  it("surfaces LangGraph checkpoint and final Langfuse trace metadata", () => {
    const events: ReviewStreamEvent[] = [
      {
        event: "langgraph_checkpoint_ready",
        progress: null,
        thread_id: "review-job:job-123",
      },
    ];
    const result = {
      telemetry: {
        observability: {
          langfuse: {
            status: "done",
            trace_id: "trace-123",
            trace_url: "https://langfuse.example/project/proj/traces/trace-123",
            session_id: "review-job:job-123",
          },
        },
      },
    } as unknown as ReviewResult;

    expect(deriveRunObservability(events, result)).toEqual({
      hasLangGraphCheckpoint: true,
      langGraphThreadId: "review-job:job-123",
      hasLangfuseTrace: true,
      langfuseTraceId: "trace-123",
      langfuseTraceUrl: "https://langfuse.example/project/proj/traces/trace-123",
      langfuseSessionId: "review-job:job-123",
      langfuseStatus: "done",
      langfuseEvidenceScoreFailure: false,
      langfuseFeedbackScoreFailure: false,
      langfuseScoreStatus: null,
      langfuseCheckpointStatus: "trace/checkpoint linked",
    });
  });

  it("surfaces Langfuse score failures from the audit snapshot", () => {
    const result = {
      telemetry: {
        observability: {
          langfuse: {
            status: "done",
            trace_id: "trace-123",
            trace_url: "https://langfuse.example/project/proj/traces/trace-123",
            session_id: "review-job:job-123",
          },
          langfuse_audit: {
            ok: false,
            evidence_score_failure: true,
            feedback_score_failure: true,
            missing: [
              "langfuse_evidence.scores_sent",
              "langfuse_feedback.scores_sent",
            ],
          },
        },
      },
    } as unknown as ReviewResult;

    expect(deriveRunObservability([], result)).toMatchObject({
      langfuseEvidenceScoreFailure: true,
      langfuseFeedbackScoreFailure: true,
      langfuseScoreStatus: "evidence/PM score delivery missing",
    });
  });

  it("surfaces Langfuse session and LangGraph checkpoint thread mismatch", () => {
    const events: ReviewStreamEvent[] = [
      {
        event: "langgraph_checkpoint_ready",
        progress: null,
        thread_id: "review-job:other-thread",
      },
    ];
    const result = {
      telemetry: {
        observability: {
          langfuse: {
            status: "done",
            trace_id: "trace-123",
            trace_url: "https://langfuse.example/project/proj/traces/trace-123",
            session_id: "review-job:job-123",
          },
          langfuse_audit: {
            ok: false,
            session_checkpoint_linked: false,
            session_checkpoint_mismatch: true,
            missing: ["langfuse.session_checkpoint_thread"],
          },
        },
      },
    } as unknown as ReviewResult;

    expect(deriveRunObservability(events, result)).toMatchObject({
      langGraphThreadId: "review-job:other-thread",
      langfuseSessionId: "review-job:job-123",
      langfuseCheckpointStatus: "trace/checkpoint mismatch",
    });
  });

  it("uses an empty observability state before LangGraph or Langfuse reports", () => {
    expect(deriveRunObservability([], null)).toEqual({
      hasLangGraphCheckpoint: false,
      langGraphThreadId: null,
      hasLangfuseTrace: false,
      langfuseTraceId: null,
      langfuseTraceUrl: null,
      langfuseSessionId: null,
      langfuseStatus: null,
      langfuseEvidenceScoreFailure: false,
      langfuseFeedbackScoreFailure: false,
      langfuseScoreStatus: null,
      langfuseCheckpointStatus: null,
    });
  });

  it("renders Langfuse score status in the Phase 2 observability strip", () => {
    const source = readFileSync(
      join(process.cwd(), "components/phases/Phase2RunningV8.tsx"),
      "utf8",
    );

    expect(source).toContain("Langfuse Score");
    expect(source).toContain("langfuseScoreStatus");
    expect(source).toContain("Trace/Checkpoint");
    expect(source).toContain("langfuseCheckpointStatus");
  });
});

describe("formatDuration", () => {
  it("undefined / 0 返回 undefined", () => {
    expect(formatDuration(undefined)).toBeUndefined();
    expect(formatDuration(0)).toBeUndefined();
  });
  it("< 1s 用 ms", () => {
    expect(formatDuration(500)).toBe("500ms");
  });
  it(">= 1s 用秒 + 1 位小数", () => {
    expect(formatDuration(1500)).toBe("1.5s");
    expect(formatDuration(12300)).toBe("12.3s");
  });
});

// ============================================================
// modelForRole

describe("modelForRole", () => {
  it("quick 模式使用轻量 GPT 路由", () => {
    expect(modelForRole("structure", "quick")).toBe("gpt-5.4-mini");
    expect(modelForRole("ai_coding", "quick")).toBe("gpt-5.4-mini");
  });
  it("standard 模式风险与终审使用更强 GPT 路由", () => {
    expect(modelForRole("ai_coding", "standard")).toBe("gpt-5.5");
    expect(modelForRole("final-reviewer", "standard")).toBe("gpt-5.5");
  });
  it("standard 模式其他评审方向使用默认 GPT 路由", () => {
    expect(modelForRole("structure", "standard")).toBe("gpt-5.4");
    expect(modelForRole("quality", "standard")).toBe("gpt-5.4");
    expect(modelForRole("data_quality", "standard")).toBe("gpt-5.4");
  });
});

// ============================================================
// computeDiff

describe("computeDiff", () => {
  const mkItem = (
    id: string,
    problem: string,
    conf: number,
  ): RunItemSummary => ({
    id,
    problem,
    birdId: 1,
    confidence: conf,
  });

  it("空 vs 空 → 4 桶全空", () => {
    const r = computeDiff([], []);
    expect(r.onlyLeft).toHaveLength(0);
    expect(r.onlyRight).toHaveLength(0);
    expect(r.bothSame).toHaveLength(0);
    expect(r.bothChanged).toHaveLength(0);
  });

  it("完全相同 → 全部进 bothSame", () => {
    const a = [mkItem("a1", "问题 A", 0.8), mkItem("a2", "问题 B", 0.7)];
    const b = [mkItem("b1", "问题 A", 0.8), mkItem("b2", "问题 B", 0.7)];
    const r = computeDiff(a, b);
    expect(r.bothSame).toHaveLength(2);
    expect(r.onlyLeft).toHaveLength(0);
    expect(r.onlyRight).toHaveLength(0);
    expect(r.bothChanged).toHaveLength(0);
  });

  it("只在 left 的项进 onlyLeft", () => {
    const a = [mkItem("a1", "只在 A 的问题", 0.9)];
    const b = [mkItem("b1", "完全不同的问题", 0.8)];
    const r = computeDiff(a, b);
    expect(r.onlyLeft).toHaveLength(1);
    expect(r.onlyLeft[0].problem).toBe("只在 A 的问题");
    expect(r.onlyRight).toHaveLength(1);
    expect(r.onlyRight[0].problem).toBe("完全不同的问题");
  });

  it("conf 差异 > threshold 进 bothChanged", () => {
    const a = [mkItem("a1", "共同问题", 0.6)];
    const b = [mkItem("b1", "共同问题", 0.9)];
    const r = computeDiff(a, b);
    expect(r.bothChanged).toHaveLength(1);
    expect(r.bothChanged[0].left.confidence).toBe(0.6);
    expect(r.bothChanged[0].right.confidence).toBe(0.9);
    expect(r.bothSame).toHaveLength(0);
  });

  it("conf 差异 <= threshold 进 bothSame", () => {
    const a = [mkItem("a1", "共同问题", 0.8)];
    const b = [mkItem("b1", "共同问题", 0.82)];
    const r = computeDiff(a, b, 0.05);
    expect(r.bothSame).toHaveLength(1);
    expect(r.bothChanged).toHaveLength(0);
  });

  it("自定义 threshold 改变分类", () => {
    const a = [mkItem("a1", "共同问题", 0.8)];
    const b = [mkItem("b1", "共同问题", 0.82)];
    // threshold=0.01 时 0.02 的差异应进 bothChanged
    const r = computeDiff(a, b, 0.01);
    expect(r.bothChanged).toHaveLength(1);
  });

  it("problem 两边 trim 后匹配(空白不敏感)", () => {
    const a = [mkItem("a1", "  去掉首尾空格的问题  ", 0.8)];
    const b = [mkItem("b1", "去掉首尾空格的问题", 0.8)];
    const r = computeDiff(a, b);
    expect(r.bothSame).toHaveLength(1);
  });

  it("混合场景 · 4 桶都有内容", () => {
    const a = [
      mkItem("a1", "A 独有", 0.9),
      mkItem("a2", "两边都有 · 一致", 0.8),
      mkItem("a3", "两边都有 · conf 变化", 0.5),
    ];
    const b = [
      mkItem("b1", "B 独有", 0.7),
      mkItem("b2", "两边都有 · 一致", 0.8),
      mkItem("b3", "两边都有 · conf 变化", 0.9),
    ];
    const r = computeDiff(a, b);
    expect(r.onlyLeft.map((x) => x.problem)).toEqual(["A 独有"]);
    expect(r.onlyRight.map((x) => x.problem)).toEqual(["B 独有"]);
    expect(r.bothSame.map((x) => x.left.problem)).toEqual([
      "两边都有 · 一致",
    ]);
    expect(r.bothChanged.map((x) => x.left.problem)).toEqual([
      "两边都有 · conf 变化",
    ]);
  });
});
