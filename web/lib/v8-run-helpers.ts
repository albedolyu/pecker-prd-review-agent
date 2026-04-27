/**
 * v8-run-helpers · Phase 2 V8 + RunDiff 的纯函数工具
 *
 * 提取自 Phase2RunningV8 / RunDiff 组件,让这些逻辑可以独立单测。
 * 组件侧只做渲染,不管派生计算。
 */

import type { BirdId } from "@/components/birds/BirdAvatar";
import type { RoleKey } from "@/lib/roles";
import type {
  ReviewStreamEvent,
  WorkerDoneEvent,
} from "@/lib/useReviewStream";
import type {
  AgentStatus,
  FailReason,
} from "@/components/run/AgentStatusCard";
import type { FailureCategory } from "@/components/run/RunHealthCheck";
import type { RunItemSummary } from "@/components/run/RunDiff";

// ============================================================
// RoleKey → BirdId 映射(v8 单一来源)

export const ROLE_TO_BIRD_ID: Record<RoleKey, BirdId> = {
  structure: 1, // 业务(责编)
  data_quality: 2, // 数据
  quality: 3, // 体验(审校)
  ai_coding: 4, // 风险(技编)
  "final-reviewer": 5, // 苍鹰 meta
  "editor-in-chief": 6,
  "reader-feedback": 7,
  "sample-reader": 8,
  archivist: 9,
  "qa-gatekeeper": 10,
};

export function roleToBird(roleKey: RoleKey): BirdId {
  return ROLE_TO_BIRD_ID[roleKey];
}

// ============================================================
// worker 状态派生

/**
 * 判断所有 worker 是否已离开运行态(done 或 failed)。
 * 只要有一只还在 queued / running,就返回 false。
 */
export function isAllWorkersDone(
  states: Map<RoleKey, AgentStatus>,
): boolean {
  for (const s of states.values()) {
    if (s !== "done" && s !== "failed") return false;
  }
  return true;
}

/**
 * 从 WorkerDoneEvent 推断 5 类失败分类:
 * - timeout   → timeout
 * - degraded  → json_parse_error(JSON 解析失败 + 重试无效)
 * - !success  → 根据 error 字符串关键词:
 *     quota / rate limit → quota_exhausted
 *     tool / function    → tool_call_failed
 *     json / parse       → json_parse_error
 *     empty / submit     → empty_submission
 * - success 但 items_count=0 → empty_submission
 * - 兜底 → tool_call_failed
 */
export function classifyFailure(ev: WorkerDoneEvent): FailureCategory {
  if (ev.timeout) return "timeout";
  if (ev.degraded) return "json_parse_error";
  if (!ev.success && ev.error) {
    const err = ev.error.toLowerCase();
    if (err.includes("quota") || err.includes("rate limit"))
      return "quota_exhausted";
    if (err.includes("tool") || err.includes("function"))
      return "tool_call_failed";
    if (err.includes("json") || err.includes("parse"))
      return "json_parse_error";
    if (err.includes("empty") || err.includes("submit"))
      return "empty_submission";
  }
  if (ev.items_count === 0 && ev.success) return "empty_submission";
  return "tool_call_failed";
}

/**
 * classifyFailure 的 FailReason 版本 · 给 AgentStatusCard 用
 * (FailReason 和 FailureCategory 是同一组字面量,但类型上是两个)
 */
export function classifyFailReason(ev: WorkerDoneEvent): FailReason {
  return classifyFailure(ev) as FailReason;
}

/**
 * worker running 中的进度估算。
 * 没有精确进度信号,用 stage-based:未收到 done 时 35%,收到 done 80%。
 * 真正完成后外层切换为 done 状态,不再显示进度条。
 */
export function inferProgress(ev?: WorkerDoneEvent): number {
  if (!ev) return 35;
  return 80;
}

// ============================================================
// 格式化

export function formatElapsed(secs: number): string {
  if (secs < 60) return `${secs}s`;
  const m = Math.floor(secs / 60);
  const s = secs % 60;
  return `${m}m${String(s).padStart(2, "0")}s`;
}

export function formatTokens(
  telemetry?: WorkerDoneEvent["telemetry"],
): string | undefined {
  if (!telemetry) return undefined;
  const total = (telemetry.tokens_in ?? 0) + (telemetry.tokens_out ?? 0);
  if (total === 0) return undefined;
  if (total >= 1000) return `${(total / 1000).toFixed(1)}k`;
  return String(total);
}

export function formatDuration(ms?: number): string | undefined {
  if (!ms) return undefined;
  if (ms < 1000) return `${ms}ms`;
  const s = ms / 1000;
  return `${s.toFixed(1)}s`;
}

/**
 * 根据 roleKey 选模型。
 * quick mode 统一 sonnet;standard 下 ai_coding 用 opus(深推理),其他 sonnet。
 */
export function modelForRole(roleKey: RoleKey, mode: string): string {
  if (mode === "quick") return "sonnet-4-6";
  return roleKey === "ai_coding" ? "opus-4" : "sonnet-4-6";
}

// ============================================================
// Funnel state · 从 SSE event 流派生 5 stage 漏斗 (2026-04-28 step 1c)
//
// 后端 step 1a 走 SSE 推 5 个 funnel_stage_* + funnel_summary,前端 Phase2 拿
// 这些事件实时渲染评审漏斗 panel。这里的派生函数纯函数,可以单测 (vitest node
// env 不能跑 React render,但可以测 events → state 的算法层)。
//
// 5 stage 语义 (与 review/funnel_telemetry.py 对齐):
// - N0_worker_raw          4 worker 原始产出 (含跨 worker 重复)
// - N1_after_dedup         merge_and_deduplicate 后
// - N2_after_evidence_verify  evidence verify (撤回/降权) 后
// - N3_after_goshawk       苍鹰终审 + apply_advisor_result 后
// - N4_after_pm_decision   PM 接受决策后 (confirm endpoint 单发, Phase2 拿不到, 标 pending)

export type FunnelStageKey =
  | "N0_worker_raw"
  | "N1_after_dedup"
  | "N2_after_evidence_verify"
  | "N3_after_goshawk"
  | "N4_after_pm_decision";

export interface FunnelStageState {
  /** 该 stage 的 item count (null = 还没收到对应 event) */
  count: number | null;
  /** stage 是否已收到事件 */
  received: boolean;
  /** stage 标签 (中文) */
  label: string;
  /** stage 的辅助文案 (例如 retracted=3 / dropped=6) */
  detail?: string;
}

export interface FunnelState {
  stages: Record<FunnelStageKey, FunnelStageState>;
  /** N1/N2/N3 留存比率 (来自 funnel_summary, 没收到时为 undefined) */
  retention?: {
    dedup_retention: number;
    evidence_verify_retention: number;
    goshawk_retention: number;
  };
  /** 是否任意 funnel event 收到过 — false 时 UI 走 fallback */
  hasAnyEvent: boolean;
  /** wiki_mode (从 evidence_verify 拿, 给 audit#4 用) */
  wikiMode?: "sparse" | "rich" | "unknown";
  /** wiki authority 分布 (canonical/contextual/generated) — audit#4 */
  authorityDistribution?: Readonly<Record<string, number>>;
}

const STAGE_LABELS: Record<FunnelStageKey, string> = {
  N0_worker_raw: "N0 · worker 原始产出",
  N1_after_dedup: "N1 · 去重后",
  N2_after_evidence_verify: "N2 · 证据校验后",
  N3_after_goshawk: "N3 · 苍鹰终审后",
  N4_after_pm_decision: "N4 · PM 决策后",
};

/**
 * 从 events 数组派生 funnel 5 stage 状态。
 *
 * 选最后一次出现的对应 event (而不是 first), 因为后端理论上一轮只发一次,
 * 但 retry 场景可能重发 — 取最后的避免显示老数据。
 */
export function deriveFunnelState(
  events: ReadonlyArray<ReviewStreamEvent>,
): FunnelState {
  const stages: Record<FunnelStageKey, FunnelStageState> = {
    N0_worker_raw: { count: null, received: false, label: STAGE_LABELS.N0_worker_raw },
    N1_after_dedup: { count: null, received: false, label: STAGE_LABELS.N1_after_dedup },
    N2_after_evidence_verify: {
      count: null,
      received: false,
      label: STAGE_LABELS.N2_after_evidence_verify,
    },
    N3_after_goshawk: { count: null, received: false, label: STAGE_LABELS.N3_after_goshawk },
    N4_after_pm_decision: {
      count: null,
      received: false,
      label: STAGE_LABELS.N4_after_pm_decision,
      detail: "待 PM 决策",
    },
  };

  let hasAnyEvent = false;
  let retention: FunnelState["retention"];
  let wikiMode: FunnelState["wikiMode"];
  let authorityDistribution: FunnelState["authorityDistribution"];

  for (const e of events) {
    switch (e.event) {
      case "funnel_stage_worker_raw":
        stages.N0_worker_raw = {
          count: e.count,
          received: true,
          label: STAGE_LABELS.N0_worker_raw,
          detail:
            e.dropped_unknown_rule_count && e.dropped_unknown_rule_count > 0
              ? `dropped 幻觉 rule_id ${e.dropped_unknown_rule_count}`
              : undefined,
        };
        hasAnyEvent = true;
        break;
      case "funnel_stage_after_dedup":
        stages.N1_after_dedup = {
          count: e.count,
          received: true,
          label: STAGE_LABELS.N1_after_dedup,
          detail: e.dropped_count > 0 ? `去重 -${e.dropped_count}` : undefined,
        };
        hasAnyEvent = true;
        break;
      case "funnel_stage_after_evidence_verify": {
        const parts: string[] = [];
        if (e.retracted_count && e.retracted_count > 0)
          parts.push(`撤回 -${e.retracted_count}`);
        if (e.downgraded_count && e.downgraded_count > 0)
          parts.push(`降权 ${e.downgraded_count}`);
        stages.N2_after_evidence_verify = {
          count: e.count,
          received: true,
          label: STAGE_LABELS.N2_after_evidence_verify,
          detail: parts.length > 0 ? parts.join(" · ") : undefined,
        };
        wikiMode = e.wiki_mode;
        authorityDistribution = e.authority_distribution;
        hasAnyEvent = true;
        break;
      }
      case "funnel_stage_after_goshawk": {
        const d = e.delta_breakdown;
        const parts: string[] = [];
        if (d.removed > 0) parts.push(`移除 -${d.removed}`);
        if (d.merged_to_facet > 0) parts.push(`合并 ${d.merged_to_facet}`);
        if (d.added > 0) parts.push(`补充 +${d.added}`);
        stages.N3_after_goshawk = {
          count: e.count,
          received: true,
          label: STAGE_LABELS.N3_after_goshawk,
          detail: parts.length > 0 ? parts.join(" · ") : undefined,
        };
        hasAnyEvent = true;
        break;
      }
      case "funnel_summary":
        retention = {
          dedup_retention: e.stage_retention.dedup_retention,
          evidence_verify_retention: e.stage_retention.evidence_verify_retention,
          goshawk_retention: e.stage_retention.goshawk_retention,
        };
        // funnel_summary 也可能后发, 同步 stages 做兜底
        if (typeof e.stages.N0_worker_raw === "number" && !stages.N0_worker_raw.received) {
          stages.N0_worker_raw = {
            count: e.stages.N0_worker_raw,
            received: true,
            label: STAGE_LABELS.N0_worker_raw,
          };
        }
        if (typeof e.stages.N1_after_dedup === "number" && !stages.N1_after_dedup.received) {
          stages.N1_after_dedup = {
            count: e.stages.N1_after_dedup,
            received: true,
            label: STAGE_LABELS.N1_after_dedup,
          };
        }
        if (
          typeof e.stages.N2_after_evidence_verify === "number" &&
          !stages.N2_after_evidence_verify.received
        ) {
          stages.N2_after_evidence_verify = {
            count: e.stages.N2_after_evidence_verify,
            received: true,
            label: STAGE_LABELS.N2_after_evidence_verify,
          };
        }
        if (
          typeof e.stages.N3_after_goshawk === "number" &&
          !stages.N3_after_goshawk.received
        ) {
          stages.N3_after_goshawk = {
            count: e.stages.N3_after_goshawk,
            received: true,
            label: STAGE_LABELS.N3_after_goshawk,
          };
        }
        hasAnyEvent = true;
        break;
      case "evidence_verify_done":
        // 老版兼容: evidence_verify_done 升级 payload 也带 wiki_mode + authority
        // (audit#4 的兜底数据源, 当 funnel_stage_after_evidence_verify 没发时)
        if (!wikiMode && e.wiki_mode) wikiMode = e.wiki_mode;
        if (!authorityDistribution && e.authority_distribution) {
          authorityDistribution = e.authority_distribution;
        }
        break;
      default:
        break;
    }
  }

  return {
    stages,
    retention,
    hasAnyEvent,
    wikiMode,
    authorityDistribution,
  };
}

// ============================================================
// RunDiff

export interface DiffBuckets {
  onlyLeft: RunItemSummary[];
  onlyRight: RunItemSummary[];
  bothSame: { left: RunItemSummary; right: RunItemSummary }[];
  bothChanged: { left: RunItemSummary; right: RunItemSummary }[];
}

/**
 * 计算两次 run items 的 4 桶 diff。
 * fuzzy id 用 problem.trim() 做 key(真实场景应该用 canonical key)。
 * conf 差异 > 0.05 算 changed,否则算 same。
 */
export function computeDiff(
  leftItems: RunItemSummary[],
  rightItems: RunItemSummary[],
  confThreshold: number = 0.05,
): DiffBuckets {
  const onlyLeft: RunItemSummary[] = [];
  const onlyRight: RunItemSummary[] = [];
  const bothSame: { left: RunItemSummary; right: RunItemSummary }[] = [];
  const bothChanged: { left: RunItemSummary; right: RunItemSummary }[] = [];

  const rightMap = new Map<string, RunItemSummary>();
  for (const it of rightItems) {
    rightMap.set(it.problem.trim(), it);
  }

  const leftKeys = new Set<string>();
  for (const it of leftItems) {
    const key = it.problem.trim();
    leftKeys.add(key);
    const rightMatch = rightMap.get(key);
    if (!rightMatch) {
      onlyLeft.push(it);
      continue;
    }
    const confDiff = Math.abs(rightMatch.confidence - it.confidence);
    if (confDiff > confThreshold) {
      bothChanged.push({ left: it, right: rightMatch });
    } else {
      bothSame.push({ left: it, right: rightMatch });
    }
  }

  for (const it of rightItems) {
    if (!leftKeys.has(it.problem.trim())) {
      onlyRight.push(it);
    }
  }

  return { onlyLeft, onlyRight, bothSame, bothChanged };
}
