"use client";

/**
 * Phase 2 · v8 · 运行中(Agent 调度中心气质 · data-phase2 局部色温 overlay)
 *
 * 数据契约和 v7 Phase2Running 一致:
 * - useReviewStream SSE 流
 * - 首次进入自动 startReview
 * - elapsed 计时
 * - workerStates / finalState 派生
 * - cancel / retry / back
 *
 * v8 核心视觉:
 * - 上层 4 个 AgentStatusCard 并行(worker 层)
 * - 下层 1 个苍鹰 AgentStatusCard(meta 层)
 * - SVG 依赖边:4 worker 底部 anchor → 苍鹰顶部 anchor,dash-flow 动画暗示数据流
 * - 底部 RunConsole 实时日志(从 stream events 合成 ConsoleLine)
 * - done 后不自动跳 Phase 3,切换到 RunHealthCheck 必经节点(harness 增量 P0-③)
 *   PM 看到 session 分类 + 5 色失败分类 + 5 鸟健康度后,主动点"继续"才进 Phase 3
 */

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { toast } from "sonner";

import { useReviewStore } from "@/lib/store";
import { WORKER_ROLE_KEYS, type RoleKey } from "@/lib/roles";
import {
  pmFacingReviewMessage,
  useReviewStream,
  type ReviewStreamEvent,
  type LangGraphCheckpointReadyEvent,
  type WorkerDoneEvent,
  type ReviewFailedEvent,
  type ReviewDegradedEvent,
  type ReviewJobReusedEvent,
  type ReviewQueuedEvent,
} from "@/lib/useReviewStream";
import { auditApi } from "@/lib/api";
import { saveReviewDraftSnapshot } from "@/lib/draft-persistence";
import type { BirdId } from "@/components/birds/BirdAvatar";
import {
  AgentStatusCard,
  type AgentStatus,
} from "@/components/run/AgentStatusCard";
import {
  RunConsole,
  type ConsoleLine,
} from "@/components/run/RunConsole";
import {
  RunHealthCheck,
  type BirdHealthData,
  type SessionClass,
  type FailureCategory,
} from "@/components/run/RunHealthCheck";
import {
  ROLE_TO_BIRD_ID,
  classifyFailure,
  classifyFailReason,
  deriveRunObservability,
  deriveFunnelState,
  extractWorkerErrors,
  formatDuration,
  formatElapsed,
  inferProgress,
  isAllWorkersDone,
  roleToBird,
  type FunnelStageKey,
  type FunnelState,
  type RunObservabilityState,
  type WorkerErrorBanner,
} from "@/lib/v8-run-helpers";
import {
  estimateReviewEtaLabel,
  reviewEtaSoftLimitSeconds,
} from "@/lib/review-eta";

// worker 侧 4 鸟 · 展示顺序和 parallel_review _DEFAULT_REVIEW_DIMENSIONS 一致
const WORKER_BIRDS: { roleKey: RoleKey; birdId: BirdId }[] =
  WORKER_ROLE_KEYS.map((roleKey) => ({
    roleKey,
    birdId: ROLE_TO_BIRD_ID[roleKey],
  }));
const META_BIRD_ID: BirdId = ROLE_TO_BIRD_ID["final-reviewer"];

export function Phase2RunningV8() {
  const reviewer = useReviewStore((s) => s.reviewer);
  const workspace = useReviewStore((s) => s.workspace);
  const prdName = useReviewStore((s) => s.prdName);
  const prdContent = useReviewStore((s) => s.prdContent);
  const rawMaterials = useReviewStore((s) => s.rawMaterials);
  const userNotes = useReviewStore((s) => s.userNotes);
  const mode = useReviewStore((s) => s.mode);
  const wikiPages = useReviewStore((s) => s.wikiPages);
  const setReviewResult = useReviewStore((s) => s.setReviewResult);
  const setPhase = useReviewStore((s) => s.setPhase);

  const stream = useReviewStream();

  const [elapsed, setElapsed] = useState(0);
  const startedAtRef = useRef<number | null>(null);
  const savedReviewIdRef = useRef<string | null>(null);
  const [showRunDetails, setShowRunDetails] = useState(false);
  const etaInput = {
    mode,
    prdContent,
    rawMaterials,
    wikiPageCount: Object.keys(wikiPages ?? {}).length,
  };
  const reviewEtaLabel = estimateReviewEtaLabel(etaInput);
  const softLimitSeconds = reviewEtaSoftLimitSeconds(etaInput);

  // 完成后是否已切到健康度页
  const [showHealthCheck, setShowHealthCheck] = useState(false);

  const startReview = useCallback(() => {
    startedAtRef.current = Date.now();
    setElapsed(0);
    setShowHealthCheck(false);
    void auditApi
      .log({
        event: "review_started",
        workspace,
        prd_name: prdName || "未命名",
        extra: { mode },
      })
      .catch(() => {});
    void stream.start({
      reviewer,
      workspace,
      prd_name: prdName || "未命名.md",
      prd_content: prdContent,
      raw_materials: rawMaterials,
      user_notes: userNotes,
      mode,
      wiki_pages: wikiPages,
    });
  }, [
    stream,
    reviewer,
    workspace,
    prdName,
    prdContent,
    rawMaterials,
    userNotes,
    mode,
    wikiPages,
  ]);

  const triggered = useRef(false);
  useEffect(() => {
    if (!triggered.current && stream.state === "idle") {
      triggered.current = true;
      // eslint-disable-next-line react-hooks/set-state-in-effect -- 首次进入触发外部评审任务,triggered.current 守卫防止重入
      startReview();
    }
  }, [startReview, stream.state]);

  // 每 500ms 刷新 elapsed
  useEffect(() => {
    if (stream.state !== "running" && stream.state !== "connecting") return;
    const id = setInterval(() => {
      if (startedAtRef.current) {
        setElapsed(Math.floor((Date.now() - startedAtRef.current) / 1000));
      }
    }, 500);
    return () => clearInterval(id);
  }, [stream.state]);

  // done 时:把 result 存 store + 切换到健康度页(不自动跳 Phase 3)
  useEffect(() => {
    const hasPreliminaryResult = stream.events.some(
      (e) => e.event === "preliminary_result",
    );
    if ((stream.state === "done" || hasPreliminaryResult) && stream.result) {
      setReviewResult(stream.result);
      if (savedReviewIdRef.current !== stream.result.review_id) {
        savedReviewIdRef.current = stream.result.review_id;
        void saveReviewDraftSnapshot({
          reviewer,
          phase: 3,
          prdName: prdName || "未命名.md",
          prdContent,
          workspace,
          mode,
          userNotes,
          rawMaterials,
          reviewResult: stream.result,
          decisions: {},
          confirmedReportMarkdown: "",
        }).catch(() => {
          toast.warning("评审结果已生成，但草稿保存失败。刷新前请先进入确认页。");
        });
      }
      // eslint-disable-next-line react-hooks/set-state-in-effect -- 只在 done 时切换一次到健康度页,条件收敛
      setShowHealthCheck(true);
    }
  }, [
    stream.state,
    stream.events,
    stream.result,
    setReviewResult,
    reviewer,
    prdName,
    prdContent,
    workspace,
    mode,
    userNotes,
    rawMaterials,
  ]);

  // ============================================================
  // 派生 worker / meta 状态

  const workerStates = useMemo(() => {
    const states = new Map<RoleKey, AgentStatus>();
    for (const k of WORKER_ROLE_KEYS) states.set(k, "queued");
    const sawWorkersStarted = stream.events.some(
      (e) => e.event === "workers_started",
    );
    if (sawWorkersStarted) {
      for (const k of WORKER_ROLE_KEYS) {
        if (states.get(k) === "queued") states.set(k, "running");
      }
    }
    for (const e of stream.events) {
      if (e.event === "worker_done") {
        const ev = e as WorkerDoneEvent;
        const k = ev.dim_key as RoleKey;
        if (WORKER_ROLE_KEYS.includes(k)) {
          if (!ev.success || ev.degraded || ev.timeout)
            states.set(k, "failed");
          else states.set(k, "done");
        }
      }
    }
    if (stream.state === "error") {
      for (const k of WORKER_ROLE_KEYS) {
        if (states.get(k) === "running") states.set(k, "failed");
      }
    }
    return states;
  }, [stream.events, stream.state]);

  const workerEvents = useMemo(() => {
    const m = new Map<RoleKey, WorkerDoneEvent>();
    for (const e of stream.events) {
      if (e.event === "worker_done") {
        const ev = e as WorkerDoneEvent;
        m.set(ev.dim_key as RoleKey, ev);
      }
    }
    return m;
  }, [stream.events]);

  const failedReviewEvent = useMemo(() => {
    for (let i = stream.events.length - 1; i >= 0; i--) {
      const e = stream.events[i];
      if (e?.event === "review_failed") return e as ReviewFailedEvent;
    }
    return null;
  }, [stream.events]);

  const degradedEvent = useMemo(() => {
    for (let i = stream.events.length - 1; i >= 0; i--) {
      const e = stream.events[i];
      if (e?.event === "review_degraded") return e as ReviewDegradedEvent;
    }
    return null;
  }, [stream.events]);

  const metaState: AgentStatus = useMemo(() => {
    if (stream.state === "error") return "failed";
    const started = stream.events.some(
      (e) => e.event === "final_reviewer_started",
    );
    const done = stream.events.some(
      (e) => e.event === "final_reviewer_done",
    );
    if (done) return "done";
    if (started) return "running";
    return "queued";
  }, [stream.events, stream.state]);

  const metaNote = useMemo(() => {
    if (metaState === "queued") return "等待四个方向完成";
    if (metaState === "running") return "合并意见中";
    if (metaState === "done") return "完成";
    return undefined;
  }, [metaState]);

  // ============================================================
  // console lines · 从 events 合成

  const consoleLines = useMemo(
    () => buildConsoleLines(stream.events),
    [stream.events],
  );

  // ============================================================
  // funnel 漏斗实时状态 (2026-04-28 step 1c)
  // 从 SSE event 派生 5 stage 进度,实时渲染 review pipeline panel.

  const funnelState = useMemo(
    () => deriveFunnelState(stream.events),
    [stream.events],
  );

  const runObservability = useMemo(
    () => deriveRunObservability(stream.events, stream.result),
    [stream.events, stream.result],
  );

  // worker error banners · 把 worker_done.error 抽出来分类成红条提示
  // (后端早就在 SSE 里写 error,但前端老 UI 只看 items_count 漏掉登录失效)
  const workerErrorBanners = useMemo(
    () => extractWorkerErrors(stream.events),
    [stream.events],
  );

  // ============================================================
  // health check 数据

  const healthData = useMemo(() => {
    const sessionClass: SessionClass = failedReviewEvent
      ? failedReviewEvent.reason === "quota_exhausted"
        ? "quota_exhausted"
        : "partial_silent"
      : degradedEvent
        ? "degraded"
        : (() => {
            const anyFailed = Array.from(workerStates.values()).some(
              (s) => s === "failed",
            );
            return anyFailed ? "partial_silent" : "productive";
          })();

    // 从 worker errors 推断 5 色失败
    const failures: Partial<Record<FailureCategory, number>> = {};
    for (const e of stream.events) {
      if (e.event === "worker_done") {
        const ev = e as WorkerDoneEvent;
        if (ev.success && !ev.degraded && !ev.timeout) continue;
        const cat = classifyFailure(ev);
        failures[cat] = (failures[cat] ?? 0) + 1;
      }
    }
    if (failedReviewEvent?.reason === "quota_exhausted") {
      failures.quota_exhausted =
        (failures.quota_exhausted ?? 0) +
        (failedReviewEvent.failed_count ?? 1);
    }

    // consistency:粗略用 items_count 有产出的 worker 比例
    const total = WORKER_ROLE_KEYS.length;
    const productive = WORKER_ROLE_KEYS.filter((k) => {
      const ev = workerEvents.get(k);
      return ev?.success && !ev.degraded && !ev.timeout && ev.items_count > 0;
    }).length;
    const consistency = total > 0 ? productive / total : 0;

    const birds: BirdHealthData[] = [
      ...WORKER_BIRDS.map(({ roleKey, birdId }) => {
        const ev = workerEvents.get(roleKey);
        const failed =
          ev && (!ev.success || ev.degraded || ev.timeout) ? 1 : 0;
        return {
          id: birdId,
          runs: 1,
          fails: failed,
          submissions: ev?.items_count ?? 0,
        };
      }),
      {
        id: META_BIRD_ID,
        runs: metaState === "queued" ? 0 : 1,
        fails: metaState === "failed" ? 1 : 0,
        submissions: 0,
      },
    ];

    return { sessionClass, failures, consistency, birds };
  }, [
    workerStates,
    workerEvents,
    failedReviewEvent,
    degradedEvent,
    stream.events,
    metaState,
  ]);

  // ============================================================
  // 操作

  const handleCancel = useCallback(() => {
    stream.cancel();
    toast.info("评审已取消");
  }, [stream]);

  const handleBack = useCallback(() => {
    if (stream.state === "running") stream.cancel();
    setPhase(1);
  }, [stream, setPhase]);

  const handleRetry = useCallback(() => {
    stream.reset();
    triggered.current = false;
    setTimeout(() => {
      triggered.current = true;
      startReview();
    }, 50);
  }, [stream, startReview]);

  const handleContinue = useCallback(() => {
    toast.success("评审完成,进入确认");
    if (stream.result) {
      void saveReviewDraftSnapshot({
        reviewer,
        phase: 3,
        prdName: prdName || "未命名.md",
        prdContent,
        workspace,
        mode,
        userNotes,
        rawMaterials,
        reviewResult: stream.result,
        decisions: {},
        confirmedReportMarkdown: "",
      }).catch(() => {});
    }
    setPhase(3);
  }, [
    setPhase,
    stream.result,
    reviewer,
    prdName,
    prdContent,
    workspace,
    mode,
    userNotes,
    rawMaterials,
  ]);

  // ============================================================
  // 渲染

  // ── 健康度检查页(Phase 1.5) ──
  if (showHealthCheck) {
    return (
      <div
        data-phase2
        style={{
          maxWidth: 1080,
          margin: "0 auto",
          padding: "28px 24px 80px",
          fontFamily: "var(--font-sans)",
          background: "var(--surface-canvas)",
          minHeight: "calc(100vh - 80px)",
        }}
      >
        <header style={{ marginBottom: 20 }}>
          <div
            style={{
              fontSize: 11,
              fontWeight: 600,
              color: "var(--accent-600)",
              marginBottom: 4,
            }}
          >
            必经节点 · 进入逐条确认前
          </div>
          <h1
            style={{
              fontSize: 22,
              fontWeight: 600,
              color: "var(--text-strong)",
              margin: 0,
              letterSpacing: "-0.015em",
            }}
          >
            结果完整性检查
          </h1>
          <p
            style={{
              fontSize: 13,
              color: "var(--text-muted)",
              marginTop: 4,
            }}
          >
            先确认本次结果是否完整,再决定继续逐条确认或重新评审
          </p>
        </header>

        <RunHealthCheck
          sessionClass={healthData.sessionClass}
          consistency={healthData.consistency}
          failures={healthData.failures}
          birds={healthData.birds}
          onContinue={handleContinue}
          onRetry={handleRetry}
        />
      </div>
    );
  }

  // ── 调度中心(运行中) ──
  const hasError = failedReviewEvent != null || stream.state === "error";

  return (
    <div
      data-phase2
      style={{
        maxWidth: 1200,
        margin: "0 auto",
        padding: "24px 24px 80px",
        fontFamily: "var(--font-sans)",
        background: "var(--surface-canvas)",
        minHeight: "calc(100vh - 80px)",
      }}
    >
      {/* ── header ── */}
      <header
        style={{
          display: "flex",
          alignItems: "baseline",
          justifyContent: "space-between",
          marginBottom: 20,
          gap: 16,
          flexWrap: "wrap",
        }}
      >
        <div>
          <h1
            style={{
              fontSize: 22,
              fontWeight: 600,
              color: "var(--text-strong)",
              margin: 0,
              letterSpacing: "-0.015em",
            }}
          >
            正在生成评审意见
          </h1>
          <p
            style={{
              fontSize: 13,
              color: "var(--text-muted)",
              marginTop: 4,
            }}
          >
            正在分方向检查 PRD,完成后会先确认结果是否完整
          </p>
        </div>
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 14,
            fontSize: 12,
            color: "var(--text-muted)",
            fontVariantNumeric: "tabular-nums",
          }}
        >
          <span>
            已用时{" "}
            <span style={{ color: "var(--text-default)", fontWeight: 500 }}>
              {formatElapsed(elapsed)}
            </span>
          </span>
          {(stream.state === "running" || stream.state === "connecting") && (
            <>
              <span
                style={{
                  width: 1,
                  height: 12,
                  background: "var(--border-default)",
                }}
              />
              <span
                style={{
                  color:
                    elapsed > softLimitSeconds
                      ? "var(--status-failed-dot)"
                      : "var(--text-muted)",
                }}
              >
                {elapsed > softLimitSeconds
                  ? "已超预期,仍在评审"
                  : `${reviewEtaLabel}完成`}
              </span>
            </>
          )}
          <span
            style={{
              fontSize: 11,
              padding: "2px 7px",
              borderRadius: "var(--r-2)",
              background: "var(--surface-sunken)",
              color: "var(--text-faint)",
            }}
            title={`评审模式 · ${mode === "quick" ? "快速" : "标准"}`}
          >
            {mode === "quick" ? "轻评审" : "深评审"}
          </span>
        </div>
      </header>

      {/* ── worker error banner · 分类提示登录失效/配额耗尽/其他 ── */}
      {workerErrorBanners.length > 0 && (
        <div style={{ marginBottom: 12, display: "flex", flexDirection: "column", gap: 8 }}>
          {workerErrorBanners.map((b, i) => (
            <WorkerErrorBannerView key={`${b.category}-${i}`} banner={b} />
          ))}
        </div>
      )}

      {/* ── review_failed / degraded 提示 ── */}
      {hasError && (
        <div
          style={{
            marginBottom: 16,
            padding: "10px 14px",
            borderRadius: "var(--r-4)",
            border: "1px solid var(--status-failed-dot)",
            background: "var(--status-failed-bg)",
            color: "var(--status-failed-fg)",
            fontSize: 13,
          }}
        >
          <strong style={{ fontWeight: 600 }}>
            {failedReviewEvent?.reason === "quota_exhausted"
              ? "评审额度不足,本次评审中断"
              : "本次评审失败"}
          </strong>
          {" · "}
          {failedReviewEvent?.message ?? stream.error ?? "评审服务暂时不可用,请返回上一步或重新评审"}
        </div>
      )}
      {!hasError && degradedEvent && (
        <div
          style={{
            marginBottom: 16,
            padding: "10px 14px",
            borderRadius: "var(--r-4)",
            border: "1px solid var(--status-warn-dot)",
            background: "var(--status-warn-bg)",
            color: "var(--status-warn-fg)",
            fontSize: 13,
          }}
        >
          <strong style={{ fontWeight: 600 }}>部分方向未完整返回</strong>
          {" · "}
          {degradedEvent.message}
        </div>
      )}

      {/* ── 分层可视化:上层 worker + 下层 meta + 依赖边 ── */}
      <RunObservabilityStrip state={runObservability} />

      <section style={{ position: "relative", marginBottom: 20 }}>
        {/* worker 层 · 桌面 4 列 / 平板 2 列 / 手机 1 列 */}
        <div
          className="pecker-worker-grid"
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(4, 1fr)",
            gap: 14,
            marginBottom: 48, // 给依赖边留空间
          }}
        >
          {WORKER_BIRDS.map(({ roleKey, birdId }) => {
            const status = workerStates.get(roleKey) ?? "queued";
            const ev = workerEvents.get(roleKey);
            return (
              <AgentStatusCard
                key={roleKey}
                birdId={birdId}
                status={status}
                submissions={ev?.items_count}
                elapsed={formatDuration(ev?.telemetry?.duration_ms)}
                failReason={ev ? classifyFailReason(ev) : undefined}
                onRetry={handleRetry}
                progress={status === "running" ? inferProgress(ev) : 0}
                variant="worker"
              />
            );
          })}
        </div>

        {/* 依赖边 SVG · 4 worker 底部 → 苍鹰顶部(A 变体 · dash-flow 动画) */}
        <DependencyEdges allDone={isAllWorkersDone(workerStates)} />

        {/* meta 层 · 苍鹰单卡 · 居中 */}
        <div style={{ maxWidth: 680, margin: "0 auto" }}>
          <AgentStatusCard
            birdId={META_BIRD_ID}
            status={metaState}
            note={metaNote}
            variant="meta"
            onRetry={handleRetry}
            progress={metaState === "running" ? 40 : 0}
          />
        </div>
      </section>

      {/* ── 评审漏斗实时进度 (step 1c) ── */}
      <FunnelPanel funnel={funnelState} />

      {/* ── 处理明细: 默认收起,避免 PM 首屏看到排障日志 ── */}
      <section
        style={{
          marginBottom: 16,
          border: "1px solid var(--border-default)",
          borderRadius: "var(--r-4)",
          background: "var(--surface-panel)",
          overflow: "hidden",
        }}
      >
        <button
          type="button"
          onClick={() => setShowRunDetails((value) => !value)}
          style={{
            width: "100%",
            border: 0,
            background: "transparent",
            padding: "12px 14px",
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            cursor: "pointer",
            color: "var(--text-default)",
            fontSize: 13,
            fontWeight: 600,
          }}
        >
          <span>
            {showRunDetails ? "收起处理明细" : "查看处理明细"}
          </span>
          <span
            style={{
              color: "var(--text-muted)",
              fontSize: 12,
              fontWeight: 400,
            }}
          >
            {showRunDetails
              ? "已显示本次评审的阶段记录"
              : "需要复盘时可查看每个阶段的处理记录"}
          </span>
        </button>
        {showRunDetails && (
          <RunConsole
            lines={consoleLines}
            live={stream.state === "running" || stream.state === "connecting"}
            height={240}
          />
        )}
      </section>

      {/* ── footer ── */}
      <footer
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 12,
          paddingTop: 12,
        }}
      >
        <button type="button" onClick={handleBack} style={btnGhost}>
          ← 返回上一步
        </button>
        <div style={{ display: "flex", gap: 8 }}>
          {(stream.state === "running" || stream.state === "connecting") && (
            <button type="button" onClick={handleCancel} style={btnSecondary}>
              取消评审
            </button>
          )}
          {(stream.state === "error" || failedReviewEvent) && (
            <button type="button" onClick={handleRetry} style={btnPrimary}>
              重新评审
            </button>
          )}
        </div>
      </footer>
    </div>
  );
}

// ============================================================
// helpers

function RunObservabilityStrip({ state }: { state: RunObservabilityState }) {
  if (
    !state.hasLangGraphCheckpoint &&
    !state.hasLangfuseTrace &&
    !state.langfuseScoreStatus &&
    !state.langfuseCheckpointStatus
  ) {
    return null;
  }

  const langGraphText = state.hasLangGraphCheckpoint
    ? state.langGraphThreadId
      ? `检查点已建立 · ${state.langGraphThreadId}`
      : "检查点已建立"
    : "未启用";
  const langfuseText = state.hasLangfuseTrace
    ? state.langfuseTraceId
      ? `Trace 已生成 · ${state.langfuseTraceId.slice(0, 8)}`
      : "Trace 已生成"
    : "结果生成后回填 Trace";

  return (
    <section
      aria-label="LangGraph 与 Langfuse 运行状态"
      style={{
        marginBottom: 16,
        padding: "10px 14px",
        borderRadius: "var(--r-4)",
        border: "1px solid var(--border-default)",
        background: "var(--surface-panel)",
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        gap: 12,
        flexWrap: "wrap",
      }}
    >
      <div
        style={{
          fontSize: 12,
          fontWeight: 600,
          color: "var(--text-strong)",
        }}
      >
        编排可观测性
      </div>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        <ObservabilityPill label="LangGraph" value={langGraphText} />
        <ObservabilityPill
          label="Langfuse"
          value={langfuseText}
          href={state.langfuseTraceUrl}
        />
        {state.langfuseScoreStatus ? (
          <ObservabilityPill
            label="Langfuse Score"
            value={state.langfuseScoreStatus}
          />
        ) : null}
        {state.langfuseCheckpointStatus ? (
          <ObservabilityPill
            label="Trace/Checkpoint"
            value={state.langfuseCheckpointStatus}
          />
        ) : null}
      </div>
    </section>
  );
}

function ObservabilityPill({
  label,
  value,
  href,
}: {
  label: string;
  value: string;
  href?: string | null;
}) {
  const content = (
    <>
      <span style={{ color: "var(--text-muted)" }}>{label}</span>
      <span style={{ color: "var(--text-default)", fontWeight: 600 }}>
        {value}
      </span>
    </>
  );
  const style: React.CSSProperties = {
    display: "inline-flex",
    alignItems: "center",
    gap: 6,
    minHeight: 26,
    padding: "4px 8px",
    borderRadius: "var(--r-3)",
    background: "var(--surface-sunken)",
    color: "var(--text-default)",
    fontSize: 12,
    textDecoration: "none",
  };

  if (href) {
    return (
      <a href={href} target="_blank" rel="noreferrer" style={style}>
        {content}
      </a>
    );
  }
  return <span style={style}>{content}</span>;
}

function buildConsoleLines(
  events: ReadonlyArray<ReviewStreamEvent>,
): ConsoleLine[] {
  const lines: ConsoleLine[] = [];
  let startTs: number | null = null;

  const tag = (): string => {
    if (startTs == null) {
      startTs = Date.now();
      return "0.0s";
    }
    const elapsed = (Date.now() - startTs) / 1000;
    return `${elapsed.toFixed(1)}s`;
  };

  events.forEach((e) => {
    const t = tag();
    switch (e.event) {
      case "job_reused": {
        const ev = e as ReviewJobReusedEvent;
        lines.push({
          t,
          src: { name: "进度" },
          level: "info",
          text: ev.message,
        });
        break;
      }
      case "uploaded":
        lines.push({
          t,
          src: { name: "进度" },
          level: "info",
          text: "PRD 已接入,正在加载资料库",
        });
        break;
      case "wiki_scanned":
        lines.push({
          t,
          src: { name: "进度" },
          level: "info",
          text: `资料库已加载 · ${"page_count" in e ? e.page_count : "?"} 页`,
        });
        break;
      case "review_queued": {
        const ev = e as ReviewQueuedEvent;
        lines.push({
          t,
          src: { name: "进度" },
          level: "info",
          text: ev.message ?? "已进入评审队列，等待空闲评审位",
        });
        break;
      }
      case "workers_started":
        lines.push({
          t,
          src: { name: "进度" },
          level: "accent",
          text: `四个方向开始并行检查(${"mode" in e && e.mode === "quick" ? "轻评审" : "深评审"})`,
        });
        break;
      case "langgraph_checkpoint_ready": {
        const ev = e as LangGraphCheckpointReadyEvent;
        lines.push({
          t,
          src: { name: "LangGraph" },
          level: "accent",
          text: `LangGraph 检查点已建立${ev.thread_id ? ` · ${ev.thread_id}` : ""}`,
        });
        break;
      }
      case "worker_done": {
        const ev = e as WorkerDoneEvent;
        const bird = roleToBird(ev.dim_key as RoleKey);
        const level: ConsoleLine["level"] = !ev.success
          ? "error"
          : ev.degraded || ev.timeout
            ? "warn"
            : "ok";
        const reason = !ev.success
          ? ev.error ?? "未完成"
          : ev.timeout
            ? "耗时过长,部分结果可用"
            : ev.degraded
              ? "结果不完整,已保留可用部分"
              : "已完成";
        lines.push({
          t,
          src: { name: ev.dim_name, bird },
          level,
          text: `${reason} · 提交 ${ev.items_count} 条意见${
            ev.telemetry?.duration_ms
              ? ` · 耗时 ${(ev.telemetry.duration_ms / 1000).toFixed(1)} 秒`
              : ""
          }`,
        });
        break;
      }
      case "final_reviewer_started":
        lines.push({
          t,
          src: { name: "收口", bird: 5 },
          level: "accent",
          text: "开始合并意见,核对依据与遗漏",
        });
        break;
      case "final_reviewer_done":
        lines.push({
          t,
          src: { name: "收口", bird: 5 },
          level: "ok",
          text: "意见合并完成",
        });
        break;
      case "preliminary_result":
        lines.push({
          t,
          src: { name: "进度" },
          level: "ok",
          text: `初稿已生成，可先确认 ${e.payload.items.length} 条意见；终审继续补充`,
        });
        break;
      case "goshawk_patch":
        lines.push({
          t,
          src: { name: "收口", bird: 5 },
          level: e.goshawk_status === "completed" ? "ok" : "warn",
          text:
            e.goshawk_status === "completed"
              ? `终审补丁已生成，当前共 ${e.payload.items.length} 条意见`
              : "终审补丁未完成，保留初稿结果",
        });
        break;
      case "result":
        lines.push({
          t,
          src: { name: "进度" },
          level: "ok",
          text: `评审完成,共 ${e.payload.items.length} 条意见待确认`,
        });
        break;
      case "error":
        lines.push({
          t,
          src: { name: "进度" },
          level: "error",
          text: `评审遇到异常:${pmFacingReviewMessage(e.message)}`,
        });
        break;
      case "review_failed": {
        const ev = e as ReviewFailedEvent;
        lines.push({
          t,
          src: { name: "进度" },
          level: "error",
          text: `评审中断 · ${ev.message}`,
        });
        break;
      }
      case "review_degraded": {
        const ev = e as ReviewDegradedEvent;
        lines.push({
          t,
          src: { name: "进度" },
          level: "warn",
          text: `部分方向未完整返回 · ${ev.message}`,
        });
        break;
      }
    }
  });

  return lines;
}

// ============================================================
// WorkerErrorBannerView · 顶部红条 · 分类提示登录失效/配额耗尽/其他

function WorkerErrorBannerView({ banner }: { banner: WorkerErrorBanner }) {
  const dimsLabel = banner.affectedDims
    .map((d) => d.dimName || d.dim)
    .join("、");
  return (
    <div
      data-testid={`worker-error-banner-${banner.category}`}
      role="alert"
      style={{
        padding: "10px 14px",
        borderRadius: "var(--r-4)",
        border: "1px solid var(--status-failed-dot)",
        background: "var(--status-failed-bg)",
        color: "var(--status-failed-fg)",
        fontSize: 13,
        lineHeight: 1.5,
      }}
    >
      <div style={{ display: "flex", alignItems: "baseline", gap: 8, flexWrap: "wrap" }}>
        <strong style={{ fontWeight: 600 }}>{banner.title}</strong>
        <span style={{ opacity: 0.85 }}>· {banner.hint}</span>
      </div>
      <div
        style={{
          marginTop: 4,
          fontSize: 12,
          opacity: 0.85,
          fontFamily: "var(--font-mono)",
        }}
      >
        影响 {banner.affectedDims.length} 个评审方向:{dimsLabel}
      </div>
      {banner.errorPreview && (
        <details
          style={{
            marginTop: 6,
            padding: "6px 8px",
            borderRadius: "var(--r-2)",
            background: "color-mix(in oklch, var(--status-failed-bg) 60%, var(--surface-canvas))",
            fontSize: 11,
            opacity: 0.9,
          }}
        >
          <summary style={{ cursor: "pointer", userSelect: "none" }}>
            查看处理建议
          </summary>
          <div
            style={{
              marginTop: 6,
              fontFamily: "var(--font-sans)",
              whiteSpace: "normal",
              wordBreak: "break-word",
            }}
          >
            该方向未完整返回,可以先重新评审;如果连续失败,请把本次评审记录发给工具负责人查看。
          </div>
        </details>
      )}
    </div>
  );
}

// ============================================================
// DependencyEdges · 4 worker 底部 anchor → 苍鹰顶部 anchor 的 SVG 连线

function DependencyEdges({ allDone }: { allDone: boolean }) {
  return (
    <svg
      width="100%"
      height="48"
      viewBox="0 0 1000 48"
      preserveAspectRatio="none"
      style={{
        position: "absolute",
        top: "calc(100% - 48px)",
        marginTop: -48,
        left: 0,
        right: 0,
        pointerEvents: "none",
      }}
      aria-hidden
    >
      {/* 4 条线:每个 worker 底部中心 → 中央苍鹰顶部 */}
      {[0.125, 0.375, 0.625, 0.875].map((x, i) => {
        const xStart = x * 1000;
        const xEnd = 500;
        return (
          <g key={i}>
            <path
              d={`M ${xStart} 0 Q ${xStart} 24 ${xEnd} 48`}
              fill="none"
              stroke={
                allDone
                  ? "color-mix(in oklch, var(--status-done-dot) 55%, transparent)"
                  : "color-mix(in oklch, var(--accent-500) 45%, transparent)"
              }
              strokeWidth="1.4"
              strokeDasharray="6 4"
              style={{
                animation: allDone ? "none" : "dash-flow 1.4s linear infinite",
              }}
            />
          </g>
        );
      })}
      <style>{`
        @keyframes dash-flow {
          to { stroke-dashoffset: -20; }
        }
      `}</style>
    </svg>
  );
}

// ============================================================
// FunnelPanel · 5 stage 漏斗横向进度条 (step 1c)
//
// 设计:
// - 5 个 stage tile 横排,每个显示 label + 大数字 + 细节 (撤回/降权/合并)
// - 顶部右侧三个 retention 比率 (来自 funnel_summary)
// - 没收到 funnel event 时整个 panel 折叠不显示, 留 fallback 文案
// - audit #4: wiki canonical/contextual 比例显示在 N2 tile 下方

function FunnelPanel({ funnel }: { funnel: FunnelState }) {
  if (!funnel.hasAnyEvent) {
    // fallback: 还没收到任何 funnel 事件 (评审刚开始 / 老版后端) — 折叠不渲染
    // 避免占空间但不挡 UI, 保留 console + agent card 主流程
    return null;
  }

  const stageOrder: FunnelStageKey[] = [
    "N0_worker_raw",
    "N1_after_dedup",
    "N2_after_evidence_verify",
    "N3_after_goshawk",
    "N4_after_pm_decision",
  ];

  return (
    <section
      style={{
        marginBottom: 16,
        padding: "14px 16px",
        borderRadius: "var(--r-3)",
        background: "var(--surface-raised)",
        border: "1px solid var(--border-subtle)",
      }}
      aria-label="评审漏斗实时进度"
      data-testid="funnel-panel"
    >
      {/* header */}
      <div
        style={{
          display: "flex",
          alignItems: "baseline",
          justifyContent: "space-between",
          marginBottom: 12,
          gap: 12,
          flexWrap: "wrap",
        }}
      >
        <div style={{ display: "flex", alignItems: "baseline", gap: 10 }}>
          <span style={{ fontSize: 14, fontWeight: 600, color: "var(--text-strong)" }}>
            意见筛选漏斗
          </span>
          <span style={{ fontSize: 12, color: "var(--text-muted)" }}>
            从初稿到最终确认,每一步保留多少条意见
          </span>
        </div>
        {funnel.retention && (
          <div
            style={{
              display: "flex",
              gap: 14,
              fontSize: 11,
              color: "var(--text-muted)",
              fontVariantNumeric: "tabular-nums",
            }}
          >
            <RetentionPill
              label="去重"
              value={funnel.retention.dedup_retention}
            />
            <RetentionPill
              label="依据校验"
              value={funnel.retention.evidence_verify_retention}
            />
            <RetentionPill
              label="意见收口"
              value={funnel.retention.goshawk_retention}
            />
          </div>
        )}
      </div>

      {/* 5 stage 横排 */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(5, 1fr)",
          gap: 8,
        }}
      >
        {stageOrder.map((key) => {
          const s = funnel.stages[key];
          return (
            <div
              key={key}
              data-testid={`funnel-stage-${key}`}
              style={{
                padding: "10px 12px",
                borderRadius: "var(--r-2)",
                background: s.received ? "var(--surface-canvas)" : "transparent",
                border: `1px solid ${
                  s.received ? "var(--border-default)" : "var(--border-subtle)"
                }`,
                opacity: s.received ? 1 : 0.45,
              }}
            >
              <div
                style={{
                  fontSize: 10,
                  fontFamily: "var(--font-mono)",
                  fontWeight: 500,
                  color: "var(--text-muted)",
                  marginBottom: 4,
                  whiteSpace: "nowrap",
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                }}
                title={s.label}
              >
                {s.label}
              </div>
              <div
                style={{
                  fontSize: 22,
                  fontWeight: 600,
                  color: s.received ? "var(--text-strong)" : "var(--text-faint)",
                  fontVariantNumeric: "tabular-nums",
                  fontFamily: "var(--font-mono)",
                  lineHeight: 1.1,
                }}
              >
                {s.count == null ? "—" : s.count}
              </div>
              {s.detail && (
                <div
                  style={{
                    marginTop: 4,
                    fontSize: 10,
                    color: "var(--text-muted)",
                    whiteSpace: "nowrap",
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                  }}
                  title={s.detail}
                >
                  {s.detail}
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* 知识库依据来源分布(收到 evidence_verify 才显示,降为辅助信息) */}
      {funnel.authorityDistribution && Object.keys(funnel.authorityDistribution).length > 0 && (
        <details
          style={{
            marginTop: 10,
          }}
          data-testid="wiki-authority-bar"
        >
          <summary
            style={{
              fontSize: 11,
              color: "var(--text-muted)",
              cursor: "pointer",
              userSelect: "none",
            }}
          >
            资料库依据来源
            {funnel.wikiMode && (
              <span
                style={{
                  marginLeft: 8,
                  padding: "1px 6px",
                  borderRadius: "var(--r-2)",
                  background:
                    funnel.wikiMode === "rich"
                      ? "var(--status-done-bg)"
                      : funnel.wikiMode === "sparse"
                        ? "var(--status-warn-bg)"
                        : "var(--neutral-100)",
                  color:
                    funnel.wikiMode === "rich"
                      ? "var(--status-done-fg)"
                      : funnel.wikiMode === "sparse"
                        ? "var(--status-warn-fg)"
                        : "var(--text-muted)",
                  fontSize: 10,
                  fontWeight: 600,
                }}
              >
                {funnel.wikiMode === "rich"
                  ? "资料库充足"
                  : funnel.wikiMode === "sparse"
                    ? "资料库稀疏"
                    : "未知"}
              </span>
            )}
          </summary>
          <div
            style={{
              marginTop: 6,
              padding: "8px 10px",
              borderRadius: "var(--r-2)",
              background: "var(--surface-canvas)",
              display: "flex",
              alignItems: "center",
              gap: 10,
              flexWrap: "wrap",
              fontSize: 11,
              color: "var(--text-muted)",
              fontVariantNumeric: "tabular-nums",
            }}
          >
            {Object.entries(funnel.authorityDistribution).map(([tier, n]) => (
              <span key={tier}>
                {tier}: <span style={{ color: "var(--text-default)" }}>{n}</span>
              </span>
            ))}
          </div>
        </details>
      )}
    </section>
  );
}

function RetentionPill({ label, value }: { label: string; value: number }) {
  // < 50% 提示降权过多 (suspicious_flags 触发条件之一); 50-80% 正常; > 80% 良好
  const tone =
    value < 0.5
      ? "var(--status-failed-fg)"
      : value < 0.8
        ? "var(--status-warn-fg)"
        : "var(--status-done-fg)";
  return (
    <span>
      <span style={{ opacity: 0.6 }}>{label}</span>{" "}
      <span style={{ color: tone }}>{(value * 100).toFixed(0)}%</span>
    </span>
  );
}

// ============================================================
// styles

const btnPrimary: React.CSSProperties = {
  height: 34,
  padding: "0 14px",
  border: 0,
  borderRadius: "var(--r-3)",
  background: "var(--accent-500)",
  color: "var(--accent-fg)",
  fontSize: 13,
  fontWeight: 600,
  cursor: "pointer",
  fontFamily: "var(--font-sans)",
};

const btnSecondary: React.CSSProperties = {
  height: 34,
  padding: "0 14px",
  border: "1px solid var(--border-default)",
  borderRadius: "var(--r-3)",
  background: "var(--surface-raised)",
  color: "var(--text-default)",
  fontSize: 13,
  fontWeight: 500,
  cursor: "pointer",
  fontFamily: "var(--font-sans)",
};

const btnGhost: React.CSSProperties = {
  height: 34,
  padding: "0 10px",
  border: 0,
  borderRadius: "var(--r-3)",
  background: "transparent",
  color: "var(--text-muted)",
  fontSize: 13,
  fontWeight: 500,
  cursor: "pointer",
  fontFamily: "var(--font-sans)",
};
