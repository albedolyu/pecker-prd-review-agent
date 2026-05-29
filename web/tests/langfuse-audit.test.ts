import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { join } from "node:path";

import type { LangfuseRunAudit, ReviewResult } from "@/lib/api";
import {
  buildLangfuseAuditSummary,
  mergeConfirmLangfuseObservability,
} from "@/lib/langfuse-audit";

const reviewResult: ReviewResult = {
  review_id: "rev_langfuse_001",
  created_at: 1,
  reviewer: "pm-a",
  workspace: "workspace-alpha",
  prd_name: "alpha.md",
  mode: "standard",
  items: [],
  workers: [],
  usage: {},
  goshawk_summary: null,
  signature: "sig",
  telemetry: {
    orchestrator: "langgraph",
    observability: {
      langfuse: {
        enabled: true,
        configured: true,
        status: "done",
        backend: "langfuse",
        session_id: "review-job:rjob-1",
        trace_id: "abc123abc123abc123abc123abc123ab",
        trace_url: "https://langfuse.example/project/proj/traces/abc123abc123abc123abc123abc123ab",
      },
      langfuse_audit: {
        ok: true,
        json_path: "output/langfuse_audits/rev_langfuse_001.json",
        markdown_path: "output/langfuse_audits/rev_langfuse_001.md",
        missing: [],
        graph_trace_ready: true,
        graph_trace_order_ready: true,
        worker_nodes_ready: true,
      },
      langgraph_checkpoint: {
        enabled: true,
        thread_id: "review-job:rjob-1",
        status: "ready",
        checkpoint_path: ".pecker_checkpoints/langgraph.pkl",
        checkpoint_exists: true,
        thread_found: true,
        checkpoint_count: 12,
      },
    },
  },
};

const audit: LangfuseRunAudit = {
  ok: true,
  review_id: "rev_langfuse_001",
  langfuse: {
    trace_link_ready: true,
    trace_url: "https://langfuse.example/project/proj/traces/abc123abc123abc123abc123abc123ab",
    session_id: "review-job:rjob-1",
    prompt_versions: [
      {
        dimension: "structure",
        name: "pecker.worker.structure.system",
        version: 8,
        label: "production",
        hash: "hash-structure",
        source: "langfuse",
      },
      {
        dimension: "quality",
        name: "pecker.worker.quality.system",
        version: 9,
        label: "canary",
        hash: "hash-quality",
        source: "langfuse",
      },
    ],
    evidence_scores: {
      status: "recorded",
      scored_items: 2,
      scores_sent: 4,
      reliability: 0.9,
      trace_linked: true,
    },
    pm_feedback_scores: {
      status: "recorded",
      scored_items: 2,
      scores_sent: 3,
      trace_linked: true,
    },
  },
  langgraph_checkpoint: {
    enabled: true,
    thread_id: "review-job:rjob-1",
    status: "ready",
    checkpoint_path: ".pecker_checkpoints/langgraph.pkl",
    checkpoint_exists: true,
    thread_found: true,
    checkpoint_count: 12,
  },
  langgraph: {
    graph_trace: [
      "prepare_round",
      "worker.structure",
      "worker.quality",
      "finalize_round",
      "finalize_review",
    ],
    graph_trace_ready: true,
    worker_node_statuses: [
      { dimension: "structure", status: "success", error_type: "" },
      { dimension: "quality", status: "success", error_type: "" },
    ],
    worker_nodes_ready: true,
    failed_workers: 0,
    recovered_workers: 1,
    recommended_batch_size: 2,
  },
  missing: [],
};

describe("Langfuse audit summary", () => {
  it("builds PM-visible links and score status from review telemetry plus fetched audit", () => {
    const summary = buildLangfuseAuditSummary(reviewResult, audit);

    expect(summary).not.toBeNull();
    if (!summary || !audit.langfuse) throw new Error("expected Langfuse summary");
    expect(summary.ready).toBe(true);
    expect(summary.orchestrator).toBe("langgraph");
    expect(summary.traceUrl).toBe(audit.langfuse.trace_url);
    expect(summary.auditJsonUrl).toBe(
      "/api/review/langfuse-audits/workspace-alpha/rev_langfuse_001?format=json",
    );
    expect(summary.auditMarkdownUrl).toBe(
      "/api/review/langfuse-audits/workspace-alpha/rev_langfuse_001?format=markdown",
    );
    expect(summary.promptVersions.map((item) => item.label)).toEqual([
      "structure production v8",
      "quality canary v9",
    ]);
    expect(summary.promptVersions.map((item) => item.hash)).toEqual([
      "hash-structure",
      "hash-quality",
    ]);
    expect(summary.evidenceStatus).toBe(
      "recorded · 4 scores · reliability 0.90 · trace linked",
    );
    expect(summary.feedbackStatus).toBe("recorded · 3 scores · trace linked");
    expect(summary.graphStatus).toBe("trace ready · workers ready · recovered 1");
    expect(summary.checkpointStatus).toBe("ready · 12 checkpoints");
    expect(summary.checkpointThreadId).toBe("review-job:rjob-1");
    expect(summary.threadLinkStatus).toBe("session linked");
  });

  it("falls back to telemetry snapshot when the local audit has not loaded", () => {
    const summary = buildLangfuseAuditSummary(reviewResult);

    expect(summary).not.toBeNull();
    if (!summary) throw new Error("expected Langfuse summary");
    expect(summary.ready).toBe(true);
    expect(summary.traceUrl).toBe(
      "https://langfuse.example/project/proj/traces/abc123abc123abc123abc123abc123ab",
    );
    expect(summary.promptVersions).toEqual([]);
    expect(summary.auditMissing).toEqual([]);
    expect(summary.graphStatus).toBe("trace ready · workers ready");
    expect(summary.checkpointStatus).toBe("ready · 12 checkpoints");
  });

  it("summarizes missing LangGraph and Langfuse evidence for the report page", () => {
    const summary = buildLangfuseAuditSummary(reviewResult, {
      ...audit,
      ok: false,
      missing: [
        "langgraph.graph_trace",
        "langfuse.trace_url",
        "worker_prompt.structure.version",
        "worker_prompt.quality.hash",
      ],
    });

    expect(summary).not.toBeNull();
    expect(summary?.ready).toBe(false);
    expect(summary?.auditOk).toBe(false);
    expect(summary?.auditMissing).toHaveLength(4);
    expect(summary?.auditMissingSummary).toBe(
      "langgraph.graph_trace, langfuse.trace_url, worker_prompt.structure.version",
    );
  });

  it("calls out LangGraph trace order failures in the report summary", () => {
    const summary = buildLangfuseAuditSummary(reviewResult, {
      ...audit,
      ok: false,
      langgraph: {
        ...audit.langgraph,
        graph_trace_ready: false,
        graph_trace_order_ready: false,
      },
      missing: ["langgraph.graph_trace.order"],
    });

    expect(summary).not.toBeNull();
    expect(summary?.ready).toBe(false);
    expect(summary?.graphStatus).toBe(
      "trace order mismatch · workers ready · recovered 1",
    );
    expect(summary?.auditMissingSummary).toBe("langgraph.graph_trace.order");
  });

  it("surfaces a Langfuse session and LangGraph checkpoint thread mismatch", () => {
    const summary = buildLangfuseAuditSummary(reviewResult, {
      ...audit,
      langgraph_checkpoint: {
        ...audit.langgraph_checkpoint,
        thread_id: "review-job:other-thread",
      },
    });

    expect(summary).not.toBeNull();
    expect(summary?.sessionId).toBe("review-job:rjob-1");
    expect(summary?.checkpointThreadId).toBe("review-job:other-thread");
    expect(summary?.threadLinkStatus).toBe("session mismatch");
  });

  it("returns null when the review result has no Langfuse observability", () => {
    expect(
      buildLangfuseAuditSummary({
        ...reviewResult,
        telemetry: { orchestrator: "langgraph" },
      }),
    ).toBeNull();
  });

  it("merges confirm feedback and refreshed audit into the Phase 4 review result", () => {
    const updated = mergeConfirmLangfuseObservability(reviewResult, {
      status: "confirmed",
      review_id: reviewResult.review_id,
      accepted: 1,
      rejected: 0,
      edited: 0,
      pending: 0,
      total: 1,
      report_markdown: "# Report",
      langfuse_feedback: {
        status: "recorded",
        scores_sent: 2,
        trace_id: "abc123abc123abc123abc123abc123ab",
        trace_linked: true,
      },
      langfuse_audit: {
        ok: true,
        status: "refreshed",
        json_path: "output/langfuse_audits/rev_langfuse_001.json",
        markdown_path: "output/langfuse_audits/rev_langfuse_001.md",
        missing: [],
      },
    });

    expect(updated).not.toBe(reviewResult);
    expect(updated.telemetry?.observability?.langfuse_feedback?.status).toBe("recorded");
    expect(updated.telemetry?.observability?.langfuse_audit?.status).toBe("refreshed");
    expect(reviewResult.telemetry?.observability?.langfuse_feedback).toBeUndefined();
  });

  it("shows confirm feedback status before the refreshed audit is fetched", () => {
    const updated = mergeConfirmLangfuseObservability(reviewResult, {
      status: "confirmed",
      review_id: reviewResult.review_id,
      accepted: 1,
      rejected: 0,
      edited: 0,
      pending: 0,
      total: 1,
      report_markdown: "# Report",
      langfuse_feedback: {
        status: "recorded",
        scored_items: 1,
        scores_sent: 2,
        trace_id: "abc123abc123abc123abc123abc123ab",
        trace_linked: true,
      },
    });

    const summary = buildLangfuseAuditSummary(updated);

    expect(summary).not.toBeNull();
    expect(summary?.feedbackStatus).toBe("recorded · 2 scores · trace linked");
  });

  it("surfaces score delivery failures from the telemetry audit snapshot before local audit loads", () => {
    const summary = buildLangfuseAuditSummary({
      ...reviewResult,
      telemetry: {
        ...reviewResult.telemetry,
        observability: {
          ...reviewResult.telemetry?.observability,
          langfuse_audit: {
            ok: false,
            status: "missing",
            missing_count: 2,
            json_path: "output/langfuse_audits/rev_langfuse_001.json",
            markdown_path: "output/langfuse_audits/rev_langfuse_001.md",
            missing: [
              "langfuse_evidence.scores_sent",
              "langfuse_feedback.scores_sent",
            ],
            evidence_score_failure: true,
            feedback_score_failure: true,
          },
          langfuse_evidence: {
            status: "recorded",
            scored_items: 2,
            scores_sent: 0,
            trace_linked: true,
          },
          langfuse_feedback: {
            status: "recorded",
            scored_items: 1,
            scores_sent: 0,
            trace_linked: true,
          },
        },
      },
    });

    expect(summary).not.toBeNull();
    expect(summary?.ready).toBe(false);
    expect(summary?.auditStatus).toBe("missing");
    expect(summary?.auditMissingCount).toBe(2);
    expect(summary?.evidenceStatus).toBe(
      "score delivery missing · 0 scores · trace linked",
    );
    expect(summary?.feedbackStatus).toBe(
      "score delivery missing · 0 scores · trace linked",
    );
    expect(summary?.auditMissingSummary).toBe(
      "langfuse_evidence.scores_sent, langfuse_feedback.scores_sent",
    );
  });

  it("surfaces session and checkpoint mismatch from the telemetry audit snapshot", () => {
    const summary = buildLangfuseAuditSummary({
      ...reviewResult,
      telemetry: {
        ...reviewResult.telemetry,
        observability: {
          langfuse: reviewResult.telemetry?.observability?.langfuse,
          langfuse_audit: {
            ok: false,
            status: "missing",
            missing_count: 1,
            json_path: "output/langfuse_audits/rev_langfuse_001.json",
            markdown_path: "output/langfuse_audits/rev_langfuse_001.md",
            missing: ["langfuse.session_checkpoint_thread"],
            session_checkpoint_linked: false,
            session_checkpoint_mismatch: true,
          },
        },
      },
    });

    expect(summary).not.toBeNull();
    expect(summary?.auditStatus).toBe("missing");
    expect(summary?.auditMissingCount).toBe(1);
    expect(summary?.threadLinkStatus).toBe("trace/checkpoint mismatch");
    expect(summary?.auditMissingSummary).toBe("langfuse.session_checkpoint_thread");
  });

  it("is rendered from the Phase 4 report exit with the local audit endpoint", () => {
    const source = readFileSync(
      join(process.cwd(), "components/phases/Phase4ReportV8.tsx"),
      "utf8",
    );

    expect(source).toContain("reviewJobsApi.getLangfuseAudit");
    expect(source).toContain("buildLangfuseAuditSummary");
    expect(source).toContain("LangfuseAuditPanel");
    expect(source).toContain("Graph Trace");
    expect(source).toContain("Checkpoint");
    expect(source).toContain("auditJsonUrl");
    expect(source).toContain("auditStatus");
    expect(source).toContain("auditMissingCount");
    expect(source).toContain("auditMissingSummary");
    expect(source).toContain("threadLinkStatus");
    expect(source).toContain("Trace Thread");
    expect(source).toContain("打开 Langfuse Trace");
    expect(source).toContain("本地审计 JSON");
    expect(source).toContain("本地审计 Markdown");
  });

  it("exposes compact Langfuse audit snapshot API client", () => {
    const source = readFileSync(join(process.cwd(), "lib/api.ts"), "utf8");

    expect(source).toContain(
      'export type LangfuseAuditFormat = "json" | "markdown" | "snapshot"',
    );
    expect(source).toContain("getLangfuseAuditSnapshot");
    expect(source).toContain(
      'reviewJobsApi.langfuseAuditUrl(workspace, reviewId, "snapshot")',
    );
  });
});
