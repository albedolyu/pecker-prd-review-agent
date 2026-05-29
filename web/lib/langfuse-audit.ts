import {
  reviewJobsApi,
  type ConfirmResponse,
  type LangfuseAuditSnapshot,
  type LangfusePromptVersion,
  type LangfuseRunAudit,
  type LangfuseScoreSnapshot,
  type LangGraphCheckpointSnapshot,
  type LangGraphRunSnapshot,
  type ReviewResult,
} from "@/lib/api";

export interface LangfuseAuditPromptSummary {
  readonly dimension: string;
  readonly name: string;
  readonly version: number | string | null;
  readonly source: string;
  readonly promptLabel: string;
  readonly hash: string;
  readonly label: string;
}

export interface LangfuseAuditSummary {
  readonly ready: boolean;
  readonly orchestrator: string;
  readonly traceUrl: string;
  readonly sessionId: string;
  readonly checkpointThreadId: string;
  readonly threadLinkStatus: string;
  readonly auditOk: boolean | null;
  readonly auditStatus: string;
  readonly auditMissing: ReadonlyArray<string>;
  readonly auditMissingCount: number;
  readonly auditMissingSummary: string;
  readonly auditJsonUrl: string;
  readonly auditMarkdownUrl: string;
  readonly promptVersions: ReadonlyArray<LangfuseAuditPromptSummary>;
  readonly evidenceStatus: string;
  readonly feedbackStatus: string;
  readonly graphStatus: string;
  readonly checkpointStatus: string;
}

export function buildLangfuseAuditSummary(
  reviewResult: ReviewResult,
  audit?: LangfuseRunAudit | null,
): LangfuseAuditSummary | null {
  const observability = reviewResult.telemetry?.observability;
  const trace = observability?.langfuse;
  const auditSnapshot = observability?.langfuse_audit;
  const traceUrl = audit?.langfuse?.trace_url || trace?.trace_url || "";
  const sessionId = audit?.langfuse?.session_id || trace?.session_id || "";
  const checkpoint = audit?.langgraph_checkpoint || observability?.langgraph_checkpoint;
  const checkpointThreadId = checkpoint?.thread_id || "";
  const hasLangfuse = Boolean(trace || auditSnapshot || audit?.langfuse);
  if (!hasLangfuse) return null;

  const workspace = reviewResult.workspace || "";
  const reviewId = audit?.review_id || reviewResult.review_id || "";
  const auditMissing = audit?.missing || auditSnapshot?.missing || [];
  const auditMissingCount = auditMissingCountFrom(audit, auditSnapshot, auditMissing);
  const auditOk = typeof audit?.ok === "boolean"
    ? audit.ok
    : typeof auditSnapshot?.ok === "boolean"
      ? auditSnapshot.ok
      : null;
  const auditStatus = audit?.status || auditSnapshot?.status || (
    auditOk === null ? "unknown" : auditOk ? "ready" : "missing"
  );
  const evidenceScoreFailure =
    auditSnapshot?.evidence_score_failure === true ||
    missingHasPrefix(auditMissing, "langfuse_evidence");
  const feedbackScoreFailure =
    auditSnapshot?.feedback_score_failure === true ||
    missingHasPrefix(auditMissing, "langfuse_feedback");
  return {
    ready: auditOk !== null ? auditOk : Boolean(traceUrl || sessionId),
    orchestrator: reviewResult.telemetry?.orchestrator || "",
    traceUrl,
    sessionId,
    checkpointThreadId,
    threadLinkStatus: formatThreadLinkStatus(
      sessionId,
      checkpointThreadId,
      audit,
      auditSnapshot,
      auditMissing,
    ),
    auditOk,
    auditStatus,
    auditMissing,
    auditMissingCount,
    auditMissingSummary: summarizeAuditMissing(auditMissing),
    auditJsonUrl: reviewJobsApi.langfuseAuditUrl(workspace, reviewId, "json"),
    auditMarkdownUrl: reviewJobsApi.langfuseAuditUrl(workspace, reviewId, "markdown"),
    promptVersions: summarizePromptVersions(audit?.langfuse?.prompt_versions || []),
    evidenceStatus: formatScoreStatus(
      audit?.langfuse?.evidence_scores || observability?.langfuse_evidence,
      { includeReliability: true, deliveryFailure: evidenceScoreFailure },
    ),
    feedbackStatus: formatScoreStatus(
      audit?.langfuse?.pm_feedback_scores || observability?.langfuse_feedback,
      { deliveryFailure: feedbackScoreFailure },
    ),
    graphStatus: formatGraphStatus(
      audit?.langgraph || graphSnapshotFromAuditSnapshot(auditSnapshot),
      reviewResult.telemetry,
    ),
    checkpointStatus: formatCheckpointStatus(checkpoint),
  };
}

function auditMissingCountFrom(
  audit: LangfuseRunAudit | null | undefined,
  auditSnapshot: LangfuseAuditSnapshot | undefined,
  missing: ReadonlyArray<string>,
): number {
  if (typeof audit?.missing_count === "number") return audit.missing_count;
  if (typeof auditSnapshot?.missing_count === "number") {
    return auditSnapshot.missing_count;
  }
  return missing.length;
}

function formatThreadLinkStatus(
  sessionId: string,
  checkpointThreadId: string,
  audit: LangfuseRunAudit | null | undefined,
  auditSnapshot: LangfuseAuditSnapshot | undefined,
  missing: ReadonlyArray<string>,
): string {
  const auditMismatch =
    audit?.session_checkpoint_mismatch === true ||
    auditSnapshot?.session_checkpoint_mismatch === true ||
    missing.includes("langfuse.session_checkpoint_thread");
  if (auditMismatch) return "trace/checkpoint mismatch";

  const auditLinked =
    audit?.session_checkpoint_linked === true ||
    auditSnapshot?.session_checkpoint_linked === true;
  if (auditLinked && !checkpointThreadId) return "trace/checkpoint linked";

  if (sessionId && checkpointThreadId) {
    return sessionId === checkpointThreadId ? "session linked" : "session mismatch";
  }
  if (sessionId || checkpointThreadId) return "partial link";
  return "not recorded";
}

function summarizeAuditMissing(missing: ReadonlyArray<string>): string {
  return missing
    .filter((item) => typeof item === "string" && item.trim().length > 0)
    .slice(0, 3)
    .join(", ");
}

function missingHasPrefix(missing: ReadonlyArray<string>, prefix: string): boolean {
  return missing.some((item) => typeof item === "string" && item.startsWith(prefix));
}

export function mergeConfirmLangfuseObservability(
  reviewResult: ReviewResult,
  response: ConfirmResponse,
): ReviewResult {
  if (!response.langfuse_feedback && !response.langfuse_audit) {
    return reviewResult;
  }
  const telemetry = reviewResult.telemetry || {};
  const observability = telemetry.observability || {};
  return {
    ...reviewResult,
    telemetry: {
      ...telemetry,
      observability: {
        ...observability,
        ...(response.langfuse_feedback
          ? { langfuse_feedback: response.langfuse_feedback }
          : {}),
        ...(response.langfuse_audit
          ? { langfuse_audit: response.langfuse_audit }
          : {}),
      },
    },
  };
}

function summarizePromptVersions(
  promptVersions: ReadonlyArray<LangfusePromptVersion>,
): LangfuseAuditPromptSummary[] {
  return promptVersions.map((item) => {
    const dimension = item.dimension || promptDimensionFromName(item.name || "") || "worker";
    const version = item.version ?? null;
    const promptLabel = item.label || "";
    const hash = item.hash || "";
    const versionLabel = version === null || version === "" ? "unknown" : `v${version}`;
    return {
      dimension,
      name: item.name || "",
      version,
      source: item.source || "",
      promptLabel,
      hash,
      label: `${dimension} ${promptLabel ? `${promptLabel} ` : ""}${versionLabel}`,
    };
  });
}

function promptDimensionFromName(name: string): string {
  const match = name.match(/^pecker\.worker\.([^.]+)\.system$/);
  return match?.[1] || "";
}

function formatScoreStatus(
  score: LangfuseScoreSnapshot | undefined,
  options: { includeReliability?: boolean; deliveryFailure?: boolean } = {},
): string {
  if (!score) return options.deliveryFailure ? "score delivery missing" : "not recorded";
  const sent = typeof score.scores_sent === "number" ? score.scores_sent : null;
  const scored = typeof score.scored_items === "number" ? score.scored_items : null;
  const deliveryFailure =
    options.deliveryFailure || (scored !== null && scored > 0 && sent !== null && sent <= 0);
  const status = deliveryFailure ? "score delivery missing" : score.status || "unknown";
  const parts = [status];
  if (sent !== null) parts.push(`${sent} scores`);
  if (options.includeReliability && typeof score.reliability === "number") {
    parts.push(`reliability ${score.reliability.toFixed(2)}`);
  }
  if (score.trace_linked === true) {
    parts.push("trace linked");
  } else if (score.trace_linked === false && score.trace_id) {
    parts.push("trace mismatch");
  }
  return parts.join(" · ");
}

function formatGraphStatus(
  graph: LangGraphRunSnapshot | undefined,
  telemetry: ReviewResult["telemetry"],
): string {
  const graphTraceReady =
    typeof graph?.graph_trace_ready === "boolean"
      ? graph.graph_trace_ready
      : Array.isArray(telemetry?.graph_trace)
        ? graphTraceLooksReady(telemetry.graph_trace)
        : null;
  const graphTraceOrderReady =
    typeof graph?.graph_trace_order_ready === "boolean"
      ? graph.graph_trace_order_ready
      : null;
  const workerNodesReady =
    typeof graph?.worker_nodes_ready === "boolean"
      ? graph.worker_nodes_ready
      : Array.isArray(telemetry?.worker_node_statuses)
        ? telemetry.worker_node_statuses.length > 0 &&
          telemetry.worker_node_statuses.every((item) => {
            const status = String(item.status || "");
            return ["success", "ok", "completed", "done"].includes(status);
          })
        : null;
  const recoveredWorkers =
    typeof graph?.recovered_workers === "number"
      ? graph.recovered_workers
      : typeof telemetry?.resilience?.recovered_workers === "number"
        ? telemetry.resilience.recovered_workers
        : null;

  const parts: string[] = [];
  if (graphTraceReady !== null) {
    parts.push(
      graphTraceReady
        ? "trace ready"
        : graphTraceOrderReady === false
          ? "trace order mismatch"
          : "trace missing",
    );
  }
  if (workerNodesReady !== null) {
    parts.push(workerNodesReady ? "workers ready" : "workers degraded");
  }
  if (recoveredWorkers !== null) {
    parts.push(`recovered ${recoveredWorkers}`);
  }
  return parts.length > 0 ? parts.join(" · ") : "not recorded";
}

function graphSnapshotFromAuditSnapshot(
  auditSnapshot: LangfuseAuditSnapshot | undefined,
): LangGraphRunSnapshot | undefined {
  if (!auditSnapshot) return undefined;
  const graphTraceReady =
    typeof auditSnapshot.graph_trace_ready === "boolean"
      ? auditSnapshot.graph_trace_ready
      : undefined;
  const graphTraceOrderReady =
    typeof auditSnapshot.graph_trace_order_ready === "boolean"
      ? auditSnapshot.graph_trace_order_ready
      : undefined;
  const workerNodesReady =
    typeof auditSnapshot.worker_nodes_ready === "boolean"
      ? auditSnapshot.worker_nodes_ready
      : undefined;
  if (
    graphTraceReady === undefined &&
    graphTraceOrderReady === undefined &&
    workerNodesReady === undefined
  ) {
    return undefined;
  }
  return {
    ...(graphTraceReady !== undefined ? { graph_trace_ready: graphTraceReady } : {}),
    ...(graphTraceOrderReady !== undefined
      ? { graph_trace_order_ready: graphTraceOrderReady }
      : {}),
    ...(workerNodesReady !== undefined ? { worker_nodes_ready: workerNodesReady } : {}),
  };
}

function graphTraceLooksReady(trace: ReadonlyArray<string>): boolean {
  return trace.includes("prepare_round") && trace.includes("finalize_review");
}

function formatCheckpointStatus(
  checkpoint: LangGraphCheckpointSnapshot | undefined,
): string {
  if (!checkpoint) return "not recorded";
  const status = checkpoint.status || "unknown";
  const count =
    typeof checkpoint.checkpoint_count === "number"
      ? checkpoint.checkpoint_count
      : null;
  const parts = [status];
  if (count !== null) parts.push(`${count} checkpoints`);
  return parts.join(" · ");
}
