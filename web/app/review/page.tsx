"use client";

/**
 * /review — 5 阶段 wizard 外壳
 *
 * v8 已是默认:
 * - /review        → v8 主线(PhaseNav + Phase 0-4 V8 + Phase 1.5 健康度内嵌 Phase 2)
 * - /review?v=7    → v7 老版降级入口(PhaseStepper + 杂志散文 UI · 保留 1 个版本回退路径)
 *
 * 职责:
 * - 登录 guard(/api/me 401 / 网络失败 → 跳 /login)
 * - 根据 store.phase 分发到对应的 Phase N 组件
 * - 顶部渲染阶段进度条(v8 PhaseNav / v7 PhaseStepper)
 */

import { Suspense, useEffect } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";

import { authApi } from "@/lib/api";
import { useReviewStore } from "@/lib/store";
import { Phase0Upload } from "@/components/phases/Phase0Upload";
import { Phase0UploadV8 } from "@/components/phases/Phase0UploadV8";
import { Phase1Precheck } from "@/components/phases/Phase1Precheck";
import { Phase1PrecheckV8 } from "@/components/phases/Phase1PrecheckV8";
import { Phase2Running } from "@/components/phases/Phase2Running";
import { Phase2RunningV8 } from "@/components/phases/Phase2RunningV8";
import { Phase3Confirm } from "@/components/phases/Phase3Confirm";
import { Phase3ConfirmV8 } from "@/components/phases/Phase3ConfirmV8";
import { Phase4Report } from "@/components/phases/Phase4Report";
import { Phase4ReportV8 } from "@/components/phases/Phase4ReportV8";
import { PhaseStepper } from "@/components/PhaseStepper";
import { PHASES, PhaseNav, type PhaseId } from "@/components/nav/PhaseNav";
import { ReviewDemoFlow } from "@/components/demo/ReviewDemoFlow";

export default function ReviewPage() {
  return (
    <Suspense fallback={null}>
      <ReviewPageInner />
    </Suspense>
  );
}

function ReviewPageInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  // v7=7 显式回退,其他一律 v8 主线
  const useLegacy = searchParams.get("v") === "7";
  const useDemo = searchParams.get("demo") === "1";

  const phase = useReviewStore((s) => s.phase);
  const reviewer = useReviewStore((s) => s.reviewer);
  const setUserInput = useReviewStore((s) => s.setUserInput);
  const setPhase = useReviewStore((s) => s.setPhase);

  const {
    data: me,
    isLoading,
    error,
  } = useQuery({
    queryKey: ["me"],
    queryFn: () => authApi.me(),
    retry: false,
    enabled: !useDemo,
    staleTime: 60 * 1000,
  });

  useEffect(() => {
    if (me?.reviewer && me.reviewer !== reviewer) {
      setUserInput({ reviewer: me.reviewer });
    }
  }, [me, reviewer, setUserInput]);

  useEffect(() => {
    if (!useDemo && error) {
      router.replace("/login");
    }
  }, [error, router, useDemo]);

  if (useDemo) {
    return <ReviewDemoFlow />;
  }

  if (isLoading) {
    return (
      <div className="mx-auto mt-20 max-w-4xl px-6 text-center text-sm text-muted-foreground">
        加载登录态……
      </div>
    );
  }

  if (!me) {
    return (
      <div className="mx-auto mt-24 flex max-w-md flex-col items-center gap-4 px-6 text-center">
        <div className="font-mono text-[10px] uppercase tracking-[0.24em] text-pecker-red/80">
          ✱ 需 要 登 录
        </div>
        <h2 className="text-[1.6rem] font-semibold tracking-tight">
          先去登录口签到
        </h2>
        <p className="text-sm leading-relaxed text-muted-foreground">
          评审系统需要先识别你是谁才能进入。如果你还没登录,或者后端暂时
          没连上,请先去登录页。
        </p>
        <div className="mt-2 flex gap-3">
          <Link
            href="/login"
            className="rounded-[6px] border border-foreground/70 bg-foreground px-4 py-2 text-sm text-background"
          >
            去登录
          </Link>
          <Link
            href="/review?demo=1"
            className="rounded-[6px] border border-foreground/30 px-4 py-2 text-sm text-foreground/75 hover:border-foreground/60"
          >
            先看演示流程
          </Link>
          <Link
            href="/"
            className="rounded-[6px] border border-foreground/30 px-4 py-2 text-sm text-foreground/75 hover:border-foreground/60"
          >
            回首页
          </Link>
        </div>
      </div>
    );
  }

  // ═══════════ v7 legacy 回退分支(显式 ?v=7) ═══════════
  if (useLegacy) {
    return (
      <div className="mx-auto max-w-[64rem] px-6 py-10 sm:px-10 sm:py-14 space-y-10">
        {/* legacy 标识 · 提醒 PM 这是回退版 */}
        <div
          style={{
            padding: "8px 14px",
            borderRadius: "var(--r-3)",
            border: "1px dashed var(--border-default)",
            background: "var(--status-warn-bg)",
            color: "var(--status-warn-fg)",
            fontSize: 12,
            fontFamily: "var(--font-sans)",
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            gap: 12,
          }}
        >
          <span>
            <strong style={{ fontWeight: 600 }}>legacy v7</strong> · 这是老版
            UI 的回退入口,默认 UI 请访问{" "}
            <Link
              href="/review"
              style={{
                color: "var(--text-link)",
                textDecoration: "underline",
              }}
            >
              /review
            </Link>
          </span>
        </div>
        <PhaseStepper current={phase} />
        <div>
          {phase === 0 && <Phase0Upload />}
          {phase === 1 && <Phase1Precheck />}
          {phase === 2 && <Phase2Running />}
          {phase === 3 && <Phase3Confirm />}
          {phase === 4 && <Phase4Report />}
        </div>
      </div>
    );
  }

  // ═══════════ v8 主线(默认) ═══════════
  const currentPhaseId: PhaseId = phase as PhaseId;
  const phaseOrder = PHASES.map((p) => p.id);
  const currentPhaseIndex = phaseOrder.indexOf(currentPhaseId);
  const completed: PhaseId[] = phaseOrder.slice(
    0,
    Math.max(0, currentPhaseIndex),
  );

  return (
    <div>
      <PhaseNav
        current={currentPhaseId}
        completed={completed}
        failed={[]}
        onNavigate={(id) => {
          // Phase 1.5 是 Phase 2 内嵌节点,不是独立的 store phase
          if (id === 1.5) return;
          setPhase(id as 0 | 1 | 2 | 3 | 4);
        }}
      />
      <div>
        {phase === 0 && <Phase0UploadV8 />}
        {phase === 1 && <Phase1PrecheckV8 />}
        {phase === 2 && <Phase2RunningV8 />}
        {phase === 3 && <Phase3ConfirmV8 />}
        {phase === 4 && <Phase4ReportV8 />}
      </div>
    </div>
  );
}
