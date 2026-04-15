"use client";

/**
 * /review — 5 阶段 wizard 外壳
 *
 * 职责:
 * - 登录 guard(/api/me 401 / 网络失败 → 跳 /login)
 * - 根据 store.phase 分发到对应的 Phase N 组件
 * - 顶部放一个阶段进度条(显示 0→4)
 *
 * 实际业务在 components/phases/Phase*.tsx。
 */

import { useEffect } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";

import { authApi } from "@/lib/api";
import { useReviewStore } from "@/lib/store";
import { Phase0Upload } from "@/components/phases/Phase0Upload";
import { Phase1Precheck } from "@/components/phases/Phase1Precheck";
import { Phase2Running } from "@/components/phases/Phase2Running";
import { Phase3Confirm } from "@/components/phases/Phase3Confirm";
import { Phase4Report } from "@/components/phases/Phase4Report";
import { PhaseStepper } from "@/components/PhaseStepper";

export default function ReviewPage() {
  const router = useRouter();
  const phase = useReviewStore((s) => s.phase);
  const reviewer = useReviewStore((s) => s.reviewer);
  const setUserInput = useReviewStore((s) => s.setUserInput);

  const {
    data: me,
    isLoading,
    error,
  } = useQuery({
    queryKey: ["me"],
    queryFn: () => authApi.me(),
    retry: false,
    staleTime: 60 * 1000,
  });

  // 登录成功后把 reviewer 同步进 store(Phase 0-4 都会用)
  useEffect(() => {
    if (me?.reviewer && me.reviewer !== reviewer) {
      setUserInput({ reviewer: me.reviewer });
    }
  }, [me, reviewer, setUserInput]);

  // 任何 error(401 / 网络 / 后端未启)都跳登录,不能让页面空白
  useEffect(() => {
    if (error) {
      router.replace("/login");
    }
  }, [error, router]);

  if (isLoading) {
    return (
      <div className="mx-auto mt-20 max-w-4xl px-6 text-center text-sm text-muted-foreground">
        加载登录态……
      </div>
    );
  }

  // 走到这里 me 还没有但也没 error,说明 useEffect 还没触发 redirect
  // 给一个显式 fallback UI,避免 return null 导致空白屏
  if (!me) {
    return (
      <div className="mx-auto mt-24 flex max-w-md flex-col items-center gap-4 px-6 text-center">
        <div className="font-mono text-[10px] uppercase tracking-[0.24em] text-pecker-red/80">
          ✱ 需 要 登 录
        </div>
        <h2 className="font-serif text-[1.6rem] italic tracking-tight">
          先去登录口签到
        </h2>
        <p className="text-sm leading-relaxed text-muted-foreground">
          评审系统需要先识别你是谁才能进入。如果你还没登录,或者后端暂时
          没连上,请先去登录页。
        </p>
        <div className="mt-2 flex gap-3">
          <Link
            href="/login"
            className="rounded-[2px] border border-foreground/70 bg-foreground px-4 py-2 font-serif text-[14px] italic text-background shadow-print transition-shadow hover:shadow-print-lift"
          >
            去登录
          </Link>
          <Link
            href="/"
            className="rounded-[2px] border border-foreground/30 px-4 py-2 font-serif text-[14px] italic text-foreground/75 transition-colors hover:border-foreground/60"
          >
            回森林首页
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-[64rem] px-6 py-10 sm:px-10 sm:py-14 space-y-10">
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
