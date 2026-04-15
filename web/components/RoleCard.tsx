"use client";

/**
 * RoleCard — 单个编辑的卡片
 *
 * Phase 2 的 4 个并行 worker 卡 + 1 个终审卡复用这个组件。
 *
 * 状态:
 * - idle: 还没启动(灰)
 * - running: 正在跑(primary + 转圈)
 * - done: 完成 + items_count(绿 + check)
 * - error: 失败(红 + X,显示 error 摘要)
 *
 * 品牌彩蛋: hover 显示 tooltip,里面写原鸟名和一句职责描述。
 * 视觉当前是 "功能版",Phase D 会用 UI Designer agent 做美化。
 */

import { Loader2, CheckCircle2, XCircle, Circle } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { Badge } from "@/components/ui/badge";
import type { Role } from "@/lib/roles";
import { cn } from "@/lib/utils";

export type RoleCardState = "idle" | "running" | "done" | "error";

export interface RoleCardProps {
  role: Role;
  state: RoleCardState;
  itemsCount?: number;
  errorText?: string;
}

export function RoleCard({
  role,
  state,
  itemsCount,
  errorText,
}: RoleCardProps) {
  // base-ui 的 TooltipTrigger 默认渲染为 button,而 button 里不能嵌 Card(div)。
  // 方案: 把 Card 包在 TooltipTrigger 之前的一个 div 里,用 div 做 trigger。
  return (
    <Tooltip>
      <TooltipTrigger
        render={
          <div
            className={cn(
              "block rounded-xl text-left outline-none focus-visible:ring-2 focus-visible:ring-ring/50",
            )}
          />
        }
      >
        <Card
          className={cn(
            "relative overflow-hidden transition-all",
            state === "idle" &&
              "border-dashed border-border/60 bg-card/40 text-muted-foreground",
            state === "running" && "border-primary/60 bg-primary/5 shadow-sm",
            state === "done" &&
              "border-emerald-500/60 bg-emerald-50/60 dark:bg-emerald-950/20",
            state === "error" && "border-destructive/60 bg-destructive/5",
          )}
        >
          <CardContent className="flex items-start gap-3 p-4">
            <StateIcon state={state} />
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2">
                <span className="text-sm font-semibold leading-tight">
                  {role.label}
                </span>
                {state === "done" && typeof itemsCount === "number" && (
                  <Badge
                    variant="secondary"
                    className="h-5 bg-emerald-100 px-1.5 text-[10px] text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300"
                  >
                    {itemsCount} 条
                  </Badge>
                )}
                {state === "running" && (
                  <Badge
                    variant="secondary"
                    className="h-5 animate-pulse bg-primary/10 px-1.5 text-[10px] text-primary"
                  >
                    进行中
                  </Badge>
                )}
              </div>
              <p className="mt-1 truncate text-xs text-muted-foreground">
                {role.responsibility}
              </p>
              {state === "error" && errorText && (
                <p className="mt-1.5 line-clamp-2 text-[11px] text-destructive">
                  {errorText}
                </p>
              )}
            </div>
          </CardContent>
        </Card>
      </TooltipTrigger>
      <TooltipContent side="bottom" className="max-w-xs">
        <div className="space-y-1">
          <div className="font-semibold">
            {role.label}{" "}
            <span className="text-muted-foreground">
              · 又名 {role.birdEmoji} {role.birdName}
            </span>
          </div>
          <div className="text-xs opacity-90">{role.description}</div>
        </div>
      </TooltipContent>
    </Tooltip>
  );
}

function StateIcon({ state }: { state: RoleCardState }) {
  const base = "h-5 w-5 shrink-0 mt-0.5";
  if (state === "idle")
    return <Circle className={cn(base, "text-muted-foreground/40")} />;
  if (state === "running")
    return <Loader2 className={cn(base, "animate-spin text-primary")} />;
  if (state === "done")
    return <CheckCircle2 className={cn(base, "text-emerald-600")} />;
  return <XCircle className={cn(base, "text-destructive")} />;
}
