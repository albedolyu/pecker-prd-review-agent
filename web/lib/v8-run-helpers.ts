/**
 * v8-run-helpers · Phase 2 V8 + RunDiff 的纯函数工具
 *
 * 提取自 Phase2RunningV8 / RunDiff 组件,让这些逻辑可以独立单测。
 * 组件侧只做渲染,不管派生计算。
 */

import type { BirdId } from "@/components/birds/BirdAvatar";
import type { RoleKey } from "@/lib/roles";
import type { WorkerDoneEvent } from "@/lib/useReviewStream";
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
