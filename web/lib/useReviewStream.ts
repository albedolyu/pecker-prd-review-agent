/**
 * useReviewStream — POST /api/review/run 的 SSE 消费 hook
 *
 * 为什么自己写而不用 EventSource:
 * 原生 `EventSource` 只支持 GET,但后端 /api/review/run 是 POST(body 里带 PRD
 * 内容 + mode + user notes)。需要 fetch + ReadableStream 手写 SSE 帧解析。
 *
 * 帧格式(由 api/stream.py 产出):
 *   event: <event_name>\n
 *   data: <json>\n
 *   \n
 *
 * 8 个 milestone + 1 个 error + 1 个 result,详细定义见 api/stream.py MILESTONES。
 *
 * 取消:通过 AbortController,用户关闭浏览器 tab 时 React 的 useEffect 清理会
 * 触发 abort,后端 request.is_disconnected() 会感知并 cancel 主评审 task,
 * semaphore 在 finally 里释放。
 */

"use client";

import { useCallback, useRef, useState } from "react";
import type { ReviewResult, ReviewRunRequest } from "./api";

// ============================================================
// 事件类型(与后端 stream.py 对齐)
// ============================================================

export type ReviewStreamState =
  | "idle"
  | "connecting"
  | "running"
  | "done"
  | "error"
  | "cancelled";

interface BaseEvent {
  readonly event: string;
  readonly progress: number | null;
  readonly label?: string;
}

export interface UploadedEvent extends BaseEvent {
  readonly event: "uploaded";
}

export interface WikiScannedEvent extends BaseEvent {
  readonly event: "wiki_scanned";
  readonly page_count?: number;
}

export interface WorkersStartedEvent extends BaseEvent {
  readonly event: "workers_started";
  readonly mode?: string;
}

export interface WorkerDoneEvent extends BaseEvent {
  readonly event: "worker_done";
  readonly dim_key: string;
  readonly dim_name: string;
  readonly success: boolean;
  readonly items_count: number;
  readonly error?: string;
  /** Phase G #1: worker 输出被降级(JSON 解析失败 + 重试无效) */
  readonly degraded?: boolean;
  /** Phase G #2: worker timeout 触发降级 */
  readonly timeout?: boolean;
  /** CC telemetry: worker 运行时指标 */
  readonly telemetry?: {
    readonly duration_ms?: number;
    readonly tokens_in?: number;
    readonly tokens_out?: number;
    readonly cost_usd?: number;
    readonly turns_used?: number;
  };
}

export interface FinalReviewerStartedEvent extends BaseEvent {
  readonly event: "final_reviewer_started";
}

/**
 * final_reviewer_done — 苍鹰终审完成 (2026-04-28 step 1a 升级:统一 SSE/jsonl payload)
 *
 * 老版前端只能拿 false_positive / additional / verdict;现在升级带:
 * - confidence + empty_retry_used (复用原来 jsonl-only 字段)
 * - DAR resample telemetry: n_samples / n_samples_succeeded /
 *   retention_kind_dist (unanimous|majority|minority) / minority_kept
 *   (DAR = 少数派保留机制, 2026-04-26 借鉴 GitHub 落地)
 *
 * error 分支只有 error 字段, 主任务异常时由 `emit_and_log(..., {"error": ...})` 推。
 */
export interface FinalReviewerDoneEvent extends BaseEvent {
  readonly event: "final_reviewer_done";
  readonly false_positive?: number;
  readonly additional?: number;
  readonly verdict?: string;
  readonly confidence?: number;
  readonly empty_retry_used?: boolean;
  // DAR resample telemetry (修法 C, 2026-04-26)
  readonly n_samples?: number;
  readonly n_samples_succeeded?: number;
  readonly retention_kind_dist?: Readonly<{
    unanimous?: number;
    majority?: number;
    minority?: number;
  }>;
  readonly minority_kept?: number;
  // 失败时只有 error 字段
  readonly error?: string;
}

// ============================================================
// 2026-04-28 step 1a: funnel telemetry SSE 双发事件
// ============================================================
// 后端 review.py emit_and_log() 把 funnel telemetry 走 SSE,
// 前端 Phase2/4 dashboard 实时拿数据 (而不是要等 result 后回查 jsonl).
// schema 与 review/funnel_telemetry.py 各 compute_* 函数返回对齐.

/**
 * funnel_stage_worker_raw — N0 stage:4 worker 原始产出
 *
 * by_dimension 把每个 worker 维度产出拆开 (structure/quality/data_quality/ai_coding).
 * 2026-04-28 P1 anti-corruption 加 dropped_unknown_* 暴露 LLM 幻觉 rule_id 被 schema_registry drop 的统计.
 */
export interface FunnelStageWorkerRawEvent extends BaseEvent {
  readonly event: "funnel_stage_worker_raw";
  readonly count: number;
  readonly by_dimension: Readonly<Record<string, number>>;
  readonly empty_retry_dimensions?: ReadonlyArray<string>;
  readonly dropped_unknown_rule_count?: number;
  readonly dropped_unknown_rule_ids_by_dim?: Readonly<Record<string, ReadonlyArray<string>>>;
}

/**
 * funnel_stage_after_dedup — N1 stage:merge_and_deduplicate 后
 *
 * dropped_count = N0 - N1 (含跨 worker 重复的 item 被合并).
 */
export interface FunnelStageAfterDedupEvent extends BaseEvent {
  readonly event: "funnel_stage_after_dedup";
  readonly count: number;
  readonly dropped_count: number;
}

/**
 * funnel_stage_after_evidence_verify — N2 stage:evidence_verify 后
 *
 * - retracted_by_reason / downgraded_by_reason: 按原因码统计 (no_wiki_match / wiki_contradicts ...)
 * - wiki_mode: sparse (新业务/模板 PRD) | rich (有 canonical wiki)
 * - authority_distribution: 按 wiki tier 统计 (canonical / contextual / generated)
 */
export interface FunnelStageAfterEvidenceVerifyEvent extends BaseEvent {
  readonly event: "funnel_stage_after_evidence_verify";
  readonly count: number;
  readonly retracted_count?: number;
  readonly downgraded_count?: number;
  readonly retracted_by_reason: Readonly<Record<string, number>>;
  readonly downgraded_by_reason: Readonly<Record<string, number>>;
  readonly wiki_mode: "sparse" | "rich" | "unknown";
  readonly authority_distribution: Readonly<Record<string, number>>;
}

/**
 * funnel_stage_after_goshawk — N3 stage:苍鹰终审 + apply_advisor_result 后
 *
 * delta_breakdown 五桶互斥:
 * - removed: 苍鹰判 false_positive 且建议移除的
 * - merged_to_facet: 主项的 facet 子项 (P0-1 commit 213ca4c 起保留)
 * - added: 苍鹰补充新条目 (provenance=meta_added 或 source=苍鹰补充)
 * - false_positive_restored: 误判后被 sanity_check 复活的
 * - kept_intact: worker 原生穿过苍鹰
 *
 * facet_links: facet 子项 → primary 主项的引用对.
 */
export interface FunnelStageAfterGoshawkEvent extends BaseEvent {
  readonly event: "funnel_stage_after_goshawk";
  readonly count: number;
  readonly delta_breakdown: Readonly<{
    removed: number;
    merged_to_facet: number;
    added: number;
    false_positive_restored: number;
    kept_intact: number;
  }>;
  readonly facet_links: ReadonlyArray<Readonly<{ facet: string; primary: string }>>;
}

/**
 * funnel_summary — 完整漏斗汇总 (review.py 末尾发, confirm_review 单独再发 N4)
 *
 * stage_retention 三个比率: dedup / evidence_verify / goshawk (N4 在 confirm endpoint 单发).
 * suspicious_flags: stage 之间留存比率低于阈值时的告警字符串数组.
 */
export interface FunnelSummaryEvent extends BaseEvent {
  readonly event: "funnel_summary";
  readonly stages: Readonly<{
    N0_worker_raw?: number;
    N1_after_dedup?: number;
    N2_after_evidence_verify?: number;
    N3_after_goshawk?: number;
    N4_after_pm_decision?: number;
  }>;
  readonly stage_retention: Readonly<{
    dedup_retention: number;
    evidence_verify_retention: number;
    goshawk_retention: number;
    pm_retention?: number;
  }>;
  readonly suspicious_flags: ReadonlyArray<string>;
}

/**
 * evidence_verify_done — 兼容老版 (老 review.py 已发, step 1a 升级 payload)
 *
 * 老版只 retracted + caveat;step 1a 加 wiki_mode + authority_distribution
 * 让前端 dashboard 不用回查 jsonl 也能渲染 wiki 治理面板.
 */
export interface EvidenceVerifyDoneEvent extends BaseEvent {
  readonly event: "evidence_verify_done";
  readonly retracted: number;
  readonly caveat: number;
  readonly wiki_mode?: "sparse" | "rich" | "unknown";
  readonly authority_distribution?: Readonly<Record<string, number>>;
}

export interface ResultEvent extends BaseEvent {
  readonly event: "result";
  readonly payload: ReviewResult;
}

export interface ErrorEvent extends BaseEvent {
  readonly event: "error";
  readonly message: string;
}

// P0-1: 后端在所有 worker 失败时发 review_failed(走配额耗尽或全员其他失败)
export interface ReviewFailedEvent extends BaseEvent {
  readonly event: "review_failed";
  readonly reason: "quota_exhausted" | "all_workers_failed" | string;
  readonly message: string;
  readonly failed_count?: number;
  readonly total_count?: number;
  readonly worker_errors?: ReadonlyArray<{ dim: string; error: string }>;
}

// P0-1: 部分 worker 失败且 merged_items 为空时的降级提示(非致命,不 abort)
export interface ReviewDegradedEvent extends BaseEvent {
  readonly event: "review_degraded";
  readonly failed_count?: number;
  readonly total_count?: number;
  readonly message: string;
}

export type ReviewStreamEvent =
  | UploadedEvent
  | WikiScannedEvent
  | WorkersStartedEvent
  | WorkerDoneEvent
  | FinalReviewerStartedEvent
  | FinalReviewerDoneEvent
  | ResultEvent
  | ErrorEvent
  | ReviewFailedEvent
  | ReviewDegradedEvent
  // 2026-04-28 step 1b: funnel telemetry SSE (5 新增 + evidence_verify_done 升级)
  | FunnelStageWorkerRawEvent
  | FunnelStageAfterDedupEvent
  | FunnelStageAfterEvidenceVerifyEvent
  | FunnelStageAfterGoshawkEvent
  | FunnelSummaryEvent
  | EvidenceVerifyDoneEvent;

// ============================================================
// SSE 帧解析器
// ============================================================

/**
 * 从累计缓冲里抽出所有完整的 SSE frames。
 * 返回 [已消耗的完整 frames, 剩余未完整的 buffer]。
 */
function splitSseFrames(buffer: string): [string[], string] {
  // SSE 规范允许 \r\n\r\n 或 \n\n 分隔
  const normalized = buffer.replace(/\r\n/g, "\n");
  const parts = normalized.split("\n\n");
  const remainder = parts.pop() ?? "";
  return [parts, remainder];
}

/**
 * 解析单个 SSE frame 为 { event, data } 对。
 * 帧里可能有多行 data:,按规范要 join,但我们后端只发单行 data:。
 */
function parseSseFrame(frame: string): { event: string; data: string } | null {
  const lines = frame.split("\n");
  let eventName = "message";
  const dataLines: string[] = [];
  for (const raw of lines) {
    if (!raw || raw.startsWith(":")) continue; // 空行或注释
    const colonIdx = raw.indexOf(":");
    if (colonIdx === -1) continue;
    const field = raw.slice(0, colonIdx).trim();
    const value = raw.slice(colonIdx + 1).replace(/^ /, "");
    if (field === "event") {
      eventName = value;
    } else if (field === "data") {
      dataLines.push(value);
    }
    // 忽略 id: / retry: 字段,后端不发
  }
  if (dataLines.length === 0) return null;
  return { event: eventName, data: dataLines.join("\n") };
}

// ============================================================
// Hook
// ============================================================

export interface UseReviewStreamResult {
  state: ReviewStreamState;
  events: ReadonlyArray<ReviewStreamEvent>;
  lastEvent: ReviewStreamEvent | null;
  progress: number;
  result: ReviewResult | null;
  error: string | null;
  start: (req: ReviewRunRequest) => Promise<void>;
  cancel: () => void;
  reset: () => void;
}

export function useReviewStream(): UseReviewStreamResult {
  const [state, setState] = useState<ReviewStreamState>("idle");
  const [events, setEvents] = useState<ReadonlyArray<ReviewStreamEvent>>([]);
  const [progress, setProgress] = useState(0);
  const [result, setResult] = useState<ReviewResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const reset = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    setState("idle");
    setEvents([]);
    setProgress(0);
    setResult(null);
    setError(null);
  }, []);

  const cancel = useCallback(() => {
    if (abortRef.current) {
      abortRef.current.abort();
      setState("cancelled");
    }
  }, []);

  const start = useCallback(
    async (req: ReviewRunRequest) => {
      // 清理之前的状态
      abortRef.current?.abort();
      setEvents([]);
      setProgress(0);
      setResult(null);
      setError(null);
      setState("connecting");

      const controller = new AbortController();
      abortRef.current = controller;

      try {
        // SSE 必须直连后端,绕开 Next.js dev rewrite 对 streaming response
        // 的 buffer 行为(rewrite 会等整个 stream 关闭才一次性 forward)。
        // dev: web/.env.local 里设 NEXT_PUBLIC_SSE_BASE=http://localhost:8000 直连
        // prod: 不设此变量,走同源相对路径,由反代 / Tunnel 按 path 分流到 FastAPI
        const apiBase = process.env.NEXT_PUBLIC_SSE_BASE ?? "";
        const res = await fetch(`${apiBase}/api/review/run`, {
          method: "POST",
          credentials: "include",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(req),
          signal: controller.signal,
        });

        if (!res.ok || !res.body) {
          throw new Error(`HTTP ${res.status} ${res.statusText}`);
        }

        setState("running");

        const reader = res.body.getReader();
        const decoder = new TextDecoder("utf-8");
        let buffer = "";

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });

          const [frames, remainder] = splitSseFrames(buffer);
          buffer = remainder;

          for (const frame of frames) {
            const parsed = parseSseFrame(frame);
            if (!parsed) continue;

            let json: Record<string, unknown>;
            try {
              json = JSON.parse(parsed.data) as Record<string, unknown>;
            } catch {
              // 解析失败跳过,不影响后续事件
              continue;
            }

            // 合并 event 名(SSE header) 和 data payload
            const ev = {
              ...(json as object),
              event: parsed.event,
            } as ReviewStreamEvent;

            setEvents((prev) => [...prev, ev]);

            if (typeof ev.progress === "number") {
              setProgress(ev.progress);
            }

            if (ev.event === "result") {
              setResult(ev.payload);
              setProgress(100);
              setState("done");
            } else if (ev.event === "error") {
              setError(ev.message ?? "评审失败");
              setState("error");
            } else if (ev.event === "review_failed") {
              // P0-1: 全员失败 abort,不让 UI 自动推进到 Phase 3
              setError(ev.message ?? "评审失败");
              setState("error");
            }
            // review_degraded 不改 state,只留在 events 里供 UI 读取展示
          }
        }

        // 流正常结束(服务端 close)— 如果还没进 done/error,标记为 done
        setState((cur) => (cur === "running" ? "done" : cur));
      } catch (e) {
        const err = e as { name?: string; message?: string };
        if (err.name === "AbortError") {
          setState("cancelled");
        } else {
          setError(err.message ?? "连接失败");
          setState("error");
        }
      } finally {
        if (abortRef.current === controller) {
          abortRef.current = null;
        }
      }
    },
    [],
  );

  const lastEvent = events.length > 0 ? events[events.length - 1]! : null;

  return {
    state,
    events,
    lastEvent,
    progress,
    result,
    error,
    start,
    cancel,
    reset,
  };
}
