"use client";

/**
 * PhaseStepper — 顶部 5 阶段横条进度指示
 *
 * 单纯展示,不做跳转交互 — 用户只能通过每个 Phase 的"下一步"前进,
 * 避免跳过校验。返回前一步通过各 Phase 组件里的"返回"按钮实现。
 */

import { CheckCircle2, Circle, Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";

interface StepDef {
  index: number;
  label: string;
  hint: string;
}

const STEPS: readonly StepDef[] = [
  { index: 0, label: "上传", hint: "拖入 PRD,选资料库" },
  { index: 1, label: "预检", hint: "读取资料 + 补充说明" },
  { index: 2, label: "评审", hint: "分向评审 + 复核" },
  { index: 3, label: "确认", hint: "逐条确认 / 驳回 / 改写" },
  { index: 4, label: "报告", hint: "下载 / 推送" },
] as const;

export function PhaseStepper({ current }: { current: number }) {
  return (
    <ol className="flex items-stretch gap-2">
      {STEPS.map((step, i) => {
        const state =
          step.index < current
            ? "done"
            : step.index === current
              ? "active"
              : "pending";
        const isLast = i === STEPS.length - 1;
        return (
          <li
            key={step.index}
            className={cn(
              "flex min-w-0 flex-1 items-center gap-3 rounded-lg border px-3 py-2.5 transition-colors",
              state === "done" &&
                "border-primary/30 bg-primary/5 text-foreground",
              state === "active" &&
                "border-primary bg-primary/10 text-foreground shadow-sm",
              state === "pending" && "border-border bg-card text-muted-foreground",
              isLast && "flex-none",
            )}
          >
            <StepIcon state={state} />
            <div className="min-w-0">
              <div className="text-sm font-medium leading-none">
                {step.index + 1}. {step.label}
              </div>
              <div className="mt-1 truncate text-[11px] opacity-80">
                {step.hint}
              </div>
            </div>
          </li>
        );
      })}
    </ol>
  );
}

function StepIcon({ state }: { state: "done" | "active" | "pending" }) {
  if (state === "done")
    return <CheckCircle2 className="h-5 w-5 shrink-0 text-primary" />;
  if (state === "active")
    return <Loader2 className="h-5 w-5 shrink-0 animate-spin text-primary" />;
  return <Circle className="h-5 w-5 shrink-0 text-muted-foreground/50" />;
}
