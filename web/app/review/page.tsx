"use client";

/**
 * /review — 5 阶段 wizard 外壳
 *
 * 职责:
 * - 登录 guard(/api/me 失败 → 跳 /login)
 * - 根据 store.phase 分发到对应的 Phase N 组件
 * - 顶部放一个阶段进度条(显示 0→4)
 *
 * 实际业务在 components/phases/Phase*.tsx。
 */

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";

import { authApi, ApiError } from "@/lib/api";
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

  // 401 → 跳登录
  useEffect(() => {
    const status = (error as ApiError | undefined)?.status;
    if (status === 401) {
      router.replace("/login");
    }
  }, [error, router]);

  if (isLoading) {
    return (
      <div className="mx-auto mt-20 max-w-4xl px-6 text-center text-sm text-muted-foreground">
        加载登录态...
      </div>
    );
  }

  if (!me) {
    // 还没跳转成功时渲染空
    return null;
  }

  return (
    <div className="mx-auto max-w-5xl px-6 py-8">
      <PhaseStepper current={phase} />
      <div className="mt-6">
        {phase === 0 && <Phase0Upload />}
        {phase === 1 && <Phase1Precheck />}
        {phase === 2 && <Phase2Running />}
        {phase === 3 && <Phase3Confirm />}
        {phase === 4 && <Phase4Report />}
      </div>
    </div>
  );
}
