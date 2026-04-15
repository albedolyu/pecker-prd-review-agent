"use client";

/**
 * Phase 2 — 评审进行中(SSE 流式)
 *
 * 视觉中心:
 * - 顶部 ProgressRail(8 milestone 进度条)
 * - 中间 4 张 RoleCard 网格(织布鸟/猫头鹰/渡鸦/鸬鹚 的并行状态)
 * - 下方 1 张终审 RoleCard(苍鹰)
 *
 * 流程:
 * - 进入时通过 useReviewStream 打开 POST /api/review/run
 * - 订阅事件流,按 dim_key 更新对应 RoleCard 的 state
 * - state 到 "done" 时,写入 reviewResult,延迟 600ms 自动进入 Phase 3
 * - state 到 "error" 时,展示错误 + 重试/返回
 *
 * 离开页面 / 点击"取消"会 AbortController.abort(),后端 semaphore 释放。
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowLeft,
  ArrowRight,
  XCircle,
  RefreshCw,
  AlertTriangle,
  Clock,
} from "lucide-react";
import { toast } from "sonner";

import { useReviewStore } from "@/lib/store";
import { ROLES, WORKER_ROLE_KEYS, type RoleKey } from "@/lib/roles";
import {
  useReviewStream,
  type WorkerDoneEvent,
} from "@/lib/useReviewStream";

import { ProgressRail } from "@/components/ProgressRail";
import { RoleCard, type RoleCardState } from "@/components/RoleCard";
import { Button } from "@/components/ui/button";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Card, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";

export function Phase2Running() {
  // ========== store ==========
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

  // ========== SSE hook ==========
  const stream = useReviewStream();

  // ========== 运行时长 ==========
  const [elapsed, setElapsed] = useState(0);
  const startedAtRef = useRef<number | null>(null);

  // ========== 触发评审 ==========
  const startReview = useCallback(() => {
    startedAtRef.current = Date.now();
    setElapsed(0);
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

  // 首次进入自动触发一次
  const triggered = useRef(false);
  useEffect(() => {
    if (!triggered.current && stream.state === "idle") {
      triggered.current = true;
      startReview();
    }
  }, [startReview, stream.state]);

  // 运行时长计时
  useEffect(() => {
    if (stream.state !== "running" && stream.state !== "connecting") return;
    const id = setInterval(() => {
      if (startedAtRef.current) {
        setElapsed(Math.floor((Date.now() - startedAtRef.current) / 1000));
      }
    }, 500);
    return () => clearInterval(id);
  }, [stream.state]);

  // ========== 完成后:写入 reviewResult + 自动推进 Phase 3 ==========
  useEffect(() => {
    if (stream.state === "done" && stream.result) {
      setReviewResult(stream.result);
      toast.success("评审完成,进入确认");
      const t = setTimeout(() => setPhase(3), 600);
      return () => clearTimeout(t);
    }
  }, [stream.state, stream.result, setReviewResult, setPhase]);

  // ========== 派生:每个 worker 当前状态 ==========
  const workerStates = useMemo(() => {
    const states = new Map<RoleKey, RoleCardState>();
    // 初始态
    for (const k of WORKER_ROLE_KEYS) states.set(k, "idle");

    // workers_started 后,还没 worker_done 的都是 running
    const sawWorkersStarted = stream.events.some(
      (e) => e.event === "workers_started",
    );
    if (sawWorkersStarted) {
      for (const k of WORKER_ROLE_KEYS) {
        if (states.get(k) === "idle") states.set(k, "running");
      }
    }

    // 遍历 worker_done 事件更新具体卡片
    for (const e of stream.events) {
      if (e.event === "worker_done") {
        const ev = e as WorkerDoneEvent;
        const k = ev.dim_key as RoleKey;
        if (WORKER_ROLE_KEYS.includes(k)) {
          states.set(k, ev.success ? "done" : "error");
        }
      }
    }

    // 失败态: 整个流 error 时未完成的 worker 标 error
    if (stream.state === "error") {
      for (const k of WORKER_ROLE_KEYS) {
        if (states.get(k) === "running") states.set(k, "error");
      }
    }

    return states;
  }, [stream.events, stream.state]);

  const workerItemCounts = useMemo(() => {
    const m = new Map<RoleKey, number>();
    for (const e of stream.events) {
      if (e.event === "worker_done") {
        const ev = e as WorkerDoneEvent;
        m.set(ev.dim_key as RoleKey, ev.items_count);
      }
    }
    return m;
  }, [stream.events]);

  const workerErrors = useMemo(() => {
    const m = new Map<RoleKey, string>();
    for (const e of stream.events) {
      if (e.event === "worker_done") {
        const ev = e as WorkerDoneEvent;
        if (ev.error) m.set(ev.dim_key as RoleKey, ev.error);
      }
    }
    return m;
  }, [stream.events]);

  // ========== 终审(苍鹰)状态 ==========
  const finalState: RoleCardState = useMemo(() => {
    if (stream.state === "error") return "error";
    const started = stream.events.some(
      (e) => e.event === "final_reviewer_started",
    );
    const done = stream.events.some((e) => e.event === "final_reviewer_done");
    if (done) return "done";
    if (started) return "running";
    return "idle";
  }, [stream.events, stream.state]);

  // ========== 操作 ==========
  const handleCancel = () => {
    stream.cancel();
    toast.info("评审已取消");
  };

  const handleBack = () => {
    if (stream.state === "running") stream.cancel();
    setPhase(1);
  };

  const handleRetry = () => {
    stream.reset();
    triggered.current = false;
    setTimeout(() => {
      triggered.current = true;
      startReview();
    }, 50);
  };

  // ========== UI ==========
  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center justify-between">
            <span>评审进行中</span>
            <span className="flex items-center gap-1.5 text-xs font-normal text-muted-foreground">
              <Clock className="h-3.5 w-3.5" />
              {formatElapsed(elapsed)}
            </span>
          </CardTitle>
          <CardDescription>
            {mode === "standard"
              ? "严格模式 — 4 位编辑并行 + 终审,预计 90-150 秒"
              : "快速模式 — 轻量版,预计 40-60 秒"}
          </CardDescription>
        </CardHeader>
      </Card>

      {/* ========== 进度条 ========== */}
      <Card>
        <div className="p-6">
          <ProgressRail
            progress={stream.progress}
            error={stream.state === "error"}
          />
        </div>
      </Card>

      {/* ========== 4 位编辑 ========== */}
      <div>
        <h3 className="mb-2 text-sm font-medium">并行编辑</h3>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {WORKER_ROLE_KEYS.map((k) => (
            <RoleCard
              key={k}
              role={ROLES[k]}
              state={workerStates.get(k) ?? "idle"}
              itemsCount={workerItemCounts.get(k)}
              errorText={workerErrors.get(k)}
            />
          ))}
        </div>
      </div>

      {/* ========== 终审(苍鹰) ========== */}
      {mode === "standard" && (
        <div>
          <h3 className="mb-2 text-sm font-medium">终审</h3>
          <RoleCard role={ROLES["final-reviewer"]} state={finalState} />
        </div>
      )}

      {/* ========== 错误态 ========== */}
      {stream.state === "error" && (
        <Alert variant="destructive">
          <AlertTriangle className="h-4 w-4" />
          <AlertTitle>评审失败</AlertTitle>
          <AlertDescription>
            {stream.error ?? "未知错误,请重试或返回上一步"}
          </AlertDescription>
        </Alert>
      )}

      {/* ========== 取消态 ========== */}
      {stream.state === "cancelled" && (
        <Alert>
          <XCircle className="h-4 w-4" />
          <AlertTitle>已取消</AlertTitle>
          <AlertDescription>评审被主动终止,当前进度已丢弃</AlertDescription>
        </Alert>
      )}

      {/* ========== 底部操作 ========== */}
      <div className="flex items-center justify-between">
        <Button variant="ghost" onClick={handleBack}>
          <ArrowLeft className="mr-1 h-4 w-4" />
          返回
        </Button>

        <div className="flex gap-2">
          {(stream.state === "running" || stream.state === "connecting") && (
            <Button variant="outline" onClick={handleCancel}>
              <XCircle className="mr-1 h-4 w-4" />
              取消
            </Button>
          )}
          {(stream.state === "error" || stream.state === "cancelled") && (
            <Button variant="outline" onClick={handleRetry}>
              <RefreshCw className="mr-1 h-4 w-4" />
              重新评审
            </Button>
          )}
          {stream.state === "done" && (
            <Button onClick={() => setPhase(3)}>
              进入确认
              <ArrowRight className="ml-1 h-4 w-4" />
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}

function formatElapsed(sec: number): string {
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return `${m}:${s.toString().padStart(2, "0")}`;
}
