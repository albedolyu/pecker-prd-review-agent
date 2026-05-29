import type {
  LangfuseRunAuditSummary,
  LangfuseSmokeResponse,
  SystemHealthResponse,
} from "@/lib/api";

export interface ControlPlaneHealthSummary {
  readonly orchestratorLabel: string;
  readonly orchestratorStatus: string;
  readonly checkpointLabel: string;
  readonly langfuseStatus: string;
  readonly langfuseDetail: string;
  readonly tone: "ok" | "warn";
}

export function summarizeControlPlaneHealth(
  health: SystemHealthResponse | null | undefined,
): ControlPlaneHealthSummary {
  const orchestrator = health?.control_plane?.orchestrator;
  const langfuse = health?.control_plane?.langfuse;
  const mode = String(orchestrator?.mode || "unknown").toLowerCase();
  const isLangGraph = mode === "langgraph";
  const checkpointReady =
    orchestrator?.checkpointing === "file" && Boolean(orchestrator.checkpoint_exists);
  const langfuseEnabled = Boolean(langfuse?.enabled);
  const langfuseConfigured = Boolean(langfuse?.configured);
  const langfuseSdkAvailable = Boolean(langfuse?.sdk_available);
  const promptManagement = langfuse?.prompt_management;

  let langfuseStatus = "未启用";
  if (langfuseEnabled && !langfuseConfigured) langfuseStatus = "缺少配置";
  else if (langfuseEnabled && !langfuseSdkAvailable) langfuseStatus = "SDK 未安装";
  else if (langfuseEnabled && langfuseConfigured && langfuseSdkAvailable) {
    langfuseStatus = "已连接";
  }

  return {
    orchestratorLabel: isLangGraph ? "LangGraph" : mode === "legacy" ? "Legacy" : "未知",
    orchestratorStatus: isLangGraph ? "已启用" : "回退模式",
    checkpointLabel: checkpointReady
      ? "文件检查点已就绪"
      : orchestrator?.checkpointing === "file"
        ? "等待首个检查点"
        : "未启用检查点",
    langfuseStatus,
    langfuseDetail: [
      langfuse?.prompt_label || "production",
      langfuse?.host || "",
      formatPromptManagementDetail(promptManagement),
    ].filter(Boolean).join(" · "),
    tone:
      isLangGraph &&
      langfuseEnabled &&
      langfuseConfigured &&
      langfuseSdkAvailable
        ? "ok"
        : "warn",
  };
}

function formatPromptManagementDetail(
  promptManagement: NonNullable<
    NonNullable<SystemHealthResponse["control_plane"]>["langfuse"]
  >["prompt_management"],
): string {
  if (!promptManagement) return "";
  const status = String(promptManagement.status || "unknown");
  const prefix = String(promptManagement.prefix || "pecker");
  const version = promptManagement.version;
  const suffix =
    version === undefined || version === null || version === ""
      ? prefix
      : `${prefix}@${String(version)}`;
  return `prompts=${status} ${suffix}`;
}

export function summarizeLangfuseSmokePrompts(
  smoke: LangfuseSmokeResponse | null | undefined,
): string {
  const checked = smoke?.prompts?.checked || [];
  if (checked.length === 0) return "";
  const labels = unique(
    checked.map((item) => {
      const label = String(item.label || "unknown");
      const version =
        item.version === undefined || item.version === null || item.version === ""
          ? "unknown"
          : String(item.version);
      return `${label}@${version}`;
    }),
  );
  const hashes = unique(
    checked
      .map((item) => String(item.hash || ""))
      .filter(Boolean),
  );
  const parts = [`prompts=${checked.length}`, labels.join(",")].filter(Boolean);
  if (hashes.length > 0) parts.push(`hashes=${hashes.join(",")}`);
  return parts.join(" ");
}

export function summarizeLangfuseRunAudits(
  audits: LangfuseRunAuditSummary | null | undefined,
): string {
  if (!audits) return "";
  const graphOrderFailures = graphTraceOrderFailureCount(audits);
  const checkpointFailures = checkpointFailureCount(audits);
  const workerFailures = workerFailureCount(audits);
  const sessionCheckpointMismatches = sessionCheckpointMismatchCount(audits);
  const evidenceScoreFailures = evidenceScoreFailureCount(audits);
  const feedbackScoreFailures = feedbackScoreFailureCount(audits);
  const parts = [
    `audits=${audits.total ?? 0}`,
    `ready=${audits.ready ?? 0}`,
    `missing=${audits.missing ?? 0}`,
    `trace=${audits.trace_ready ?? 0}`,
    `graph=${audits.graph_ready ?? 0}`,
    `checkpoint=${audits.checkpoint_ready ?? 0}`,
  ];
  if (graphOrderFailures > 0) {
    parts.push(`order=${graphOrderFailures}`);
  }
  if (checkpointFailures > 0) {
    parts.push(`checkpoint-missing=${checkpointFailures}`);
  }
  if (workerFailures > 0) {
    parts.push(`workers-degraded=${workerFailures}`);
  }
  if (sessionCheckpointMismatches > 0) {
    parts.push(`session-checkpoint=${sessionCheckpointMismatches}`);
  }
  if (evidenceScoreFailures > 0) {
    parts.push(`evidence-score=${evidenceScoreFailures}`);
  }
  if (feedbackScoreFailures > 0) {
    parts.push(`feedback-score=${feedbackScoreFailures}`);
  }
  return parts.join(" ");
}

export function summarizeLangfuseRunAuditStatus(
  audits: LangfuseRunAuditSummary | null | undefined,
): string {
  if (!audits) return "not checked";
  const graphOrderFailures = graphTraceOrderFailureCount(audits);
  const checkpointFailures = checkpointFailureCount(audits);
  const workerFailures = workerFailureCount(audits);
  const sessionCheckpointMismatches = sessionCheckpointMismatchCount(audits);
  const evidenceScoreFailures = evidenceScoreFailureCount(audits);
  const feedbackScoreFailures = feedbackScoreFailureCount(audits);
  if ((audits.missing ?? 0) > 0) {
    return [
      `${audits.missing} missing`,
      graphOrderFailures > 0 ? `order=${graphOrderFailures}` : "",
      checkpointFailures > 0 ? `checkpoint-missing=${checkpointFailures}` : "",
      workerFailures > 0 ? `workers-degraded=${workerFailures}` : "",
      sessionCheckpointMismatches > 0
        ? `session-checkpoint=${sessionCheckpointMismatches}`
        : "",
      evidenceScoreFailures > 0 ? `evidence-score=${evidenceScoreFailures}` : "",
      feedbackScoreFailures > 0 ? `feedback-score=${feedbackScoreFailures}` : "",
    ].filter(Boolean).join(" · ");
  }
  return "ready";
}

export interface LangfuseRunAuditLink {
  readonly label: string;
  readonly status: string;
  readonly tone: "ok" | "warn";
  readonly jsonUrl: string;
  readonly markdownUrl?: string;
  readonly missingSummary?: string;
}

export function recentLangfuseRunAuditLinks(
  audits: LangfuseRunAuditSummary | null | undefined,
  limit = 3,
): LangfuseRunAuditLink[] {
  const rows = audits?.audits || [];
  const links: LangfuseRunAuditLink[] = [];
  for (const row of rows) {
    const jsonUrl = asText(row.json_url);
    if (!jsonUrl) continue;
    const workspace = asText(row.workspace);
    const reviewId = asText(row.review_id);
    const missingCount =
      typeof row.missing_count === "number" ? row.missing_count : 0;
    const status = [
      asText(row.status) || (row.ok === false ? "missing" : "ready"),
      missingCount > 0 ? `missing=${missingCount}` : "",
    ].filter(Boolean).join(" ");
    const markdownUrl = asText(row.markdown_url);
    const missingSummary = missingSummaryFor(row);
    links.push({
      label: [workspace, reviewId].filter(Boolean).join(" / ") || "run audit",
      status,
      tone: row.ok === false || missingCount > 0 ? "warn" : "ok",
      jsonUrl,
      ...(markdownUrl ? { markdownUrl } : {}),
      ...(missingSummary ? { missingSummary } : {}),
    });
  }
  return links.slice(0, Math.max(1, limit));
}

function missingSummaryFor(
  row: NonNullable<LangfuseRunAuditSummary["audits"]>[number],
): string {
  const direct = asText(row.missing_summary);
  const missing = direct ? splitMissingSummary(direct) : missingValues(row);
  return missing.slice(0, 3).map(formatMissingReason).join(", ");
}

function countGraphTraceOrderFailures(
  audits: LangfuseRunAuditSummary,
): number {
  return (audits.audits || []).filter((row) =>
    row.graph_order_failure === true ||
    missingValues(row).includes("langgraph.graph_trace.order") ||
    splitMissingSummary(asText(row.missing_summary)).includes("langgraph.graph_trace.order"),
  ).length;
}

function graphTraceOrderFailureCount(audits: LangfuseRunAuditSummary): number {
  return typeof audits.graph_order_failures === "number"
    ? audits.graph_order_failures
    : countGraphTraceOrderFailures(audits);
}

function countCheckpointFailures(audits: LangfuseRunAuditSummary): number {
  return (audits.audits || []).filter((row) => row.checkpoint_failure === true).length;
}

function checkpointFailureCount(audits: LangfuseRunAuditSummary): number {
  return typeof audits.checkpoint_failures === "number"
    ? audits.checkpoint_failures
    : countCheckpointFailures(audits);
}

function countWorkerFailures(audits: LangfuseRunAuditSummary): number {
  return (audits.audits || []).filter((row) => row.worker_failure === true).length;
}

function workerFailureCount(audits: LangfuseRunAuditSummary): number {
  return typeof audits.worker_failures === "number"
    ? audits.worker_failures
    : countWorkerFailures(audits);
}

function countSessionCheckpointMismatches(audits: LangfuseRunAuditSummary): number {
  return (audits.audits || []).filter((row) =>
    row.session_checkpoint_mismatch === true ||
    missingValues(row).includes("langfuse.session_checkpoint_thread") ||
    splitMissingSummary(asText(row.missing_summary)).includes(
      "langfuse.session_checkpoint_thread",
    ),
  ).length;
}

function sessionCheckpointMismatchCount(audits: LangfuseRunAuditSummary): number {
  return typeof audits.session_checkpoint_mismatches === "number"
    ? audits.session_checkpoint_mismatches
    : countSessionCheckpointMismatches(audits);
}

function countEvidenceScoreFailures(audits: LangfuseRunAuditSummary): number {
  return (audits.audits || []).filter((row) =>
    row.evidence_score_failure === true ||
    missingValues(row).some((item) => item.startsWith("langfuse_evidence")) ||
    splitMissingSummary(asText(row.missing_summary)).some((item) =>
      item.startsWith("langfuse_evidence"),
    ),
  ).length;
}

function evidenceScoreFailureCount(audits: LangfuseRunAuditSummary): number {
  return typeof audits.evidence_score_failures === "number"
    ? audits.evidence_score_failures
    : countEvidenceScoreFailures(audits);
}

function countFeedbackScoreFailures(audits: LangfuseRunAuditSummary): number {
  return (audits.audits || []).filter((row) =>
    row.feedback_score_failure === true ||
    missingValues(row).some((item) => item.startsWith("langfuse_feedback")) ||
    splitMissingSummary(asText(row.missing_summary)).some((item) =>
      item.startsWith("langfuse_feedback"),
    ),
  ).length;
}

function feedbackScoreFailureCount(audits: LangfuseRunAuditSummary): number {
  return typeof audits.feedback_score_failures === "number"
    ? audits.feedback_score_failures
    : countFeedbackScoreFailures(audits);
}

function missingValues(
  row: NonNullable<LangfuseRunAuditSummary["audits"]>[number],
): string[] {
  return Array.isArray(row.missing)
    ? row.missing.filter((item): item is string => typeof item === "string")
    : [];
}

function splitMissingSummary(summary: string): string[] {
  return summary
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

function formatMissingReason(reason: string): string {
  if (reason === "langgraph.graph_trace.order") {
    return "trace order mismatch";
  }
  if (reason === "langfuse.session_checkpoint_thread") {
    return "trace/checkpoint mismatch";
  }
  return reason;
}

function asText(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function unique(values: string[]): string[] {
  return Array.from(new Set(values));
}
