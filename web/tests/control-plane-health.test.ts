import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

import {
  recentLangfuseRunAuditLinks,
  summarizeControlPlaneHealth,
  summarizeLangfuseRunAuditStatus,
  summarizeLangfuseRunAudits,
  summarizeLangfuseSmokePrompts,
} from "@/lib/control-plane-health";
import type { SystemHealthResponse } from "@/lib/api";

const ROOT = process.cwd();

function readSource(path: string): string {
  return readFileSync(join(ROOT, path), "utf8");
}

describe("control-plane health", () => {
  it("turns LangGraph and Langfuse readiness into PM-facing labels", () => {
    const health: SystemHealthResponse = {
      status: "ok",
      service: "pecker-api",
      version: "2.0.0",
      control_plane: {
        orchestrator: {
          mode: "langgraph",
          checkpointing: "file",
          checkpoint_path: ".pecker_checkpoints/langgraph.pkl",
          checkpoint_exists: true,
        },
        langfuse: {
          enabled: true,
          configured: true,
          sdk_available: true,
          host: "https://langfuse.example",
          prompt_label: "production",
          prompt_management: {
            enabled: true,
            status: "ready",
            prefix: "pecker",
            label: "production",
            version: "8",
          },
        },
      },
    };

    expect(summarizeControlPlaneHealth(health)).toEqual({
      orchestratorLabel: "LangGraph",
      orchestratorStatus: "已启用",
      checkpointLabel: "文件检查点已就绪",
      langfuseStatus: "已连接",
      langfuseDetail: "production · https://langfuse.example · prompts=ready pecker@8",
      tone: "ok",
    });
  });

  it("shows actionable Langfuse setup state without exposing keys", () => {
    const health: SystemHealthResponse = {
      status: "ok",
      service: "pecker-api",
      version: "2.0.0",
      control_plane: {
        orchestrator: { mode: "legacy", checkpointing: "file" },
        langfuse: {
          enabled: true,
          configured: false,
          sdk_available: true,
          host: "",
          prompt_label: "production",
        },
      },
    };

    const summary = summarizeControlPlaneHealth(health);
    expect(summary.orchestratorLabel).toBe("Legacy");
    expect(summary.langfuseStatus).toBe("缺少配置");
    expect(JSON.stringify(summary)).not.toContain("LANGFUSE_SECRET_KEY");
  });

  it("summarizes Langfuse smoke prompt label version and hash", () => {
    expect(
      summarizeLangfuseSmokePrompts({
        ok: true,
        prompts: {
          checked: [
            {
              name: "pecker.worker.structure.system",
              source: "langfuse",
              status: "ready",
              label: "production",
              version: 8,
              hash: "hash-structure",
            },
            {
              name: "pecker.worker.quality.system",
              source: "langfuse",
              status: "ready",
              label: "production",
              version: 8,
              hash: "hash-quality",
            },
          ],
        },
      }),
    ).toBe("prompts=2 production@8 hashes=hash-structure,hash-quality");
  });

  it("summarizes recent Langfuse run audits for the control plane", () => {
    expect(
      summarizeLangfuseRunAudits({
        total: 2,
        ready: 1,
        missing: 1,
        trace_ready: 2,
        graph_ready: 1,
        checkpoint_ready: 1,
        audits: [],
      }),
    ).toBe("audits=2 ready=1 missing=1 trace=2 graph=1 checkpoint=1");
  });

  it("calls out LangGraph trace order failures in the control-plane audit rollup", () => {
    expect(
      summarizeLangfuseRunAudits({
        total: 2,
        ready: 1,
        missing: 1,
        trace_ready: 2,
        graph_ready: 1,
        checkpoint_ready: 1,
        graph_order_failures: 1,
        audits: [],
      }),
    ).toBe("audits=2 ready=1 missing=1 trace=2 graph=1 checkpoint=1 order=1");
  });

  it("surfaces trace order failures directly in the Run Audit badge status", () => {
    expect(
      summarizeLangfuseRunAuditStatus({
        total: 2,
        ready: 1,
        missing: 1,
        trace_ready: 2,
        graph_ready: 1,
        checkpoint_ready: 1,
        graph_order_failures: 1,
        audits: [],
      }),
    ).toBe("1 missing · order=1");
  });

  it("surfaces checkpoint failures directly in the Run Audit badge status", () => {
    expect(
      summarizeLangfuseRunAuditStatus({
        total: 2,
        ready: 1,
        missing: 1,
        trace_ready: 2,
        graph_ready: 1,
        checkpoint_ready: 1,
        checkpoint_failures: 1,
        audits: [],
      }),
    ).toBe("1 missing · checkpoint-missing=1");
  });

  it("surfaces worker failures directly in the Run Audit badge status", () => {
    expect(
      summarizeLangfuseRunAuditStatus({
        total: 2,
        ready: 1,
        missing: 1,
        trace_ready: 2,
        graph_ready: 1,
        checkpoint_ready: 2,
        worker_failures: 1,
        audits: [],
      }),
    ).toBe("1 missing · workers-degraded=1");
  });

  it("falls back to recent audit rows when graph order failure count is absent", () => {
    expect(
      summarizeLangfuseRunAudits({
        total: 2,
        ready: 1,
        missing: 1,
        trace_ready: 2,
        graph_ready: 1,
        checkpoint_ready: 1,
        audits: [
          {
            review_id: "rev_order",
            workspace: "workspace-alpha",
            ok: false,
            missing_count: 1,
            missing_summary: "langgraph.graph_trace.order",
            missing: ["langgraph.graph_trace.order"],
            json_url:
              "/api/review/langfuse-audits/workspace-alpha/rev_order?format=json",
          },
        ],
      }),
    ).toBe("audits=2 ready=1 missing=1 trace=2 graph=1 checkpoint=1 order=1");
  });

  it("returns direct links for recent Langfuse run audit evidence", () => {
    expect(
      recentLangfuseRunAuditLinks({
        total: 2,
        ready: 1,
        missing: 1,
        trace_ready: 2,
        graph_ready: 1,
        checkpoint_ready: 1,
        audits: [
          {
            workspace: "workspace-alpha",
            review_id: "rev_ok",
            status: "ready",
            ok: true,
            json_url: "/api/review/langfuse-audits/workspace-alpha/rev_ok?format=json",
            markdown_url:
              "/api/review/langfuse-audits/workspace-alpha/rev_ok?format=markdown",
          },
          {
            workspace: "workspace-beta",
            review_id: "rev_missing",
            status: "missing",
            ok: false,
            missing_count: 2,
            missing_summary: "langgraph.graph_trace, langfuse.trace_url",
            json_url:
              "/api/review/langfuse-audits/workspace-beta/rev_missing?format=json",
          },
        ],
      }),
    ).toEqual([
      {
        label: "workspace-alpha / rev_ok",
        status: "ready",
        tone: "ok",
        jsonUrl: "/api/review/langfuse-audits/workspace-alpha/rev_ok?format=json",
        markdownUrl:
          "/api/review/langfuse-audits/workspace-alpha/rev_ok?format=markdown",
      },
      {
        label: "workspace-beta / rev_missing",
        status: "missing missing=2",
        tone: "warn",
        jsonUrl: "/api/review/langfuse-audits/workspace-beta/rev_missing?format=json",
        missingSummary: "langgraph.graph_trace, langfuse.trace_url",
      },
    ]);
  });

  it("labels recent trace order failures with a readable control-plane reason", () => {
    expect(
      recentLangfuseRunAuditLinks({
        total: 1,
        ready: 0,
        missing: 1,
        trace_ready: 1,
        graph_ready: 0,
        checkpoint_ready: 1,
        audits: [
          {
            workspace: "workspace-alpha",
            review_id: "rev_order",
            status: "missing",
            ok: false,
            missing_count: 2,
            missing_summary: "langgraph.graph_trace.order, langfuse.trace_url",
            missing: ["langgraph.graph_trace.order", "langfuse.trace_url"],
            json_url:
              "/api/review/langfuse-audits/workspace-alpha/rev_order?format=json",
          },
        ],
      }),
    ).toEqual([
      {
        label: "workspace-alpha / rev_order",
        status: "missing missing=2",
        tone: "warn",
        jsonUrl: "/api/review/langfuse-audits/workspace-alpha/rev_order?format=json",
        missingSummary: "trace order mismatch, langfuse.trace_url",
      },
    ]);
  });

  it("connects the system health page to live API health", () => {
    const source = readSource("app/system/health/page.tsx");
    const api = readSource("lib/api.ts");

    expect(source).toContain("systemHealthApi.get");
    expect(source).toContain("adminUsageApi.langfuseSmoke");
    expect(source).toContain("adminUsageApi.langgraphCheckpoints");
    expect(source).toContain("adminUsageApi.langfuseRunAudits");
    expect(source).toContain("langfuseSmokeQuery.refetch");
    expect(source).toContain("langgraphCheckpointQuery.refetch");
    expect(source).toContain("langfuseRunAuditQuery.refetch");
    expect(source).toContain("Langfuse Run Audit");
    expect(source).toContain("recentLangfuseRunAuditLinks");
    expect(source).toContain("刷新 Langfuse 体检");
    expect(source).toContain("刷新 checkpoint 摘要");
    expect(source).toContain("ControlPlanePanel");
    expect(source).toContain("编排与观测");
    expect(api).toContain("/api/admin/langfuse-smoke");
    expect(api).toContain("/api/admin/langgraph-checkpoints");
    expect(api).toContain("/api/admin/langfuse-run-audits");
  });

  it("surfaces evidence score delivery failures directly in the Run Audit badge status", () => {
    expect(
      summarizeLangfuseRunAuditStatus({
        total: 2,
        ready: 1,
        missing: 1,
        trace_ready: 2,
        graph_ready: 1,
        checkpoint_ready: 2,
        evidence_score_failures: 1,
        audits: [],
      }),
    ).toBe("1 missing · evidence-score=1");
  });

  it("surfaces PM feedback score delivery failures directly in the Run Audit badge status", () => {
    expect(
      summarizeLangfuseRunAuditStatus({
        total: 2,
        ready: 1,
        missing: 1,
        trace_ready: 2,
        graph_ready: 1,
        checkpoint_ready: 2,
        feedback_score_failures: 1,
        audits: [],
      }),
    ).toBe("1 missing · feedback-score=1");
  });
  it("surfaces Langfuse session and checkpoint thread mismatches in the audit rollup", () => {
    expect(
      summarizeLangfuseRunAudits({
        total: 2,
        ready: 1,
        missing: 1,
        trace_ready: 2,
        graph_ready: 1,
        checkpoint_ready: 2,
        session_checkpoint_mismatches: 1,
        audits: [],
      }),
    ).toBe(
      "audits=2 ready=1 missing=1 trace=2 graph=1 checkpoint=2 session-checkpoint=1",
    );
    const status = summarizeLangfuseRunAuditStatus({
      total: 2,
      ready: 1,
      missing: 1,
      trace_ready: 2,
      graph_ready: 1,
      checkpoint_ready: 2,
      session_checkpoint_mismatches: 1,
      audits: [],
    });
    expect(status).toContain("1 missing");
    expect(status).toContain("session-checkpoint=1");
  });

  it("labels session/checkpoint mismatch with a readable control-plane reason", () => {
    expect(
      recentLangfuseRunAuditLinks({
        total: 1,
        ready: 0,
        missing: 1,
        trace_ready: 1,
        graph_ready: 1,
        checkpoint_ready: 1,
        audits: [
          {
            workspace: "workspace-alpha",
            review_id: "rev_mismatch",
            status: "missing",
            ok: false,
            missing_count: 1,
            missing_summary: "langfuse.session_checkpoint_thread",
            missing: ["langfuse.session_checkpoint_thread"],
            json_url:
              "/api/review/langfuse-audits/workspace-alpha/rev_mismatch?format=json",
          },
        ],
      }),
    ).toEqual([
      {
        label: "workspace-alpha / rev_mismatch",
        status: "missing missing=1",
        tone: "warn",
        jsonUrl:
          "/api/review/langfuse-audits/workspace-alpha/rev_mismatch?format=json",
        missingSummary: "trace/checkpoint mismatch",
      },
    ]);
  });
});
