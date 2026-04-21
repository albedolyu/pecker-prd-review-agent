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

export interface FinalReviewerDoneEvent extends BaseEvent {
  readonly event: "final_reviewer_done";
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
  | ReviewDegradedEvent;

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
