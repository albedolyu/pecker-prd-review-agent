"use client";

/**
 * RoleCard — 单个编辑的卡片
 *
 * Phase 2 的 4 个并行 worker 卡 + 1 个终审卡复用这个组件。
 *
 * 视觉(Phase F 编辑部主题 · 去 AI 味):
 * - 纸质卡片 shadow-paper,hover 时极微 lift(-0.5px + shadow-lift)
 * - 左侧 3px 状态竖条(before 伪元素)—— 像纸质文档的"状态书签"
 * - Badge 用 Mono + tabular-nums,数字像印刷的版次号
 * - running 态 peck 震颤动画(每张卡 --peck-delay 不同,4 只鸟不同步)
 * - weight=heavy 变体:头版头条,字号 +1 档 + 顶部"本期·头版"红笔小标
 * - 支持外层 className pass-through(col-span / 错位 mt)
 *
 * 彩蛋: hover 显示 tooltip,里面写原鸟名和一句职责描述。
 */

import type { CSSProperties } from "react";
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
  /** 头版头条变体:字号 +1 档 + 顶部"本期 · 头版"小标 */
  weight?: "normal" | "heavy";
  /** peck 动画的 delay(秒),4 张卡各不同,防止同步 */
  peckDelay?: number;
  /** pass-through 外层 className(用于 col-span / 错位 mt-X 等) */
  className?: string;
}

export function RoleCard({
  role,
  state,
  itemsCount,
  errorText,
  weight = "normal",
  peckDelay = 0,
  className,
}: RoleCardProps) {
  const isHeavy = weight === "heavy";
  return (
    <Tooltip>
      <TooltipTrigger
        render={
          <div
            className={cn(
              "block rounded-md text-left outline-none focus-visible:ring-2 focus-visible:ring-ring/50",
              className,
            )}
          />
        }
      >
        <Card
          className={cn(
            // 基础:纸质卡片
            "group relative overflow-hidden rounded-md border bg-card",
            "shadow-paper transition-[transform,box-shadow,border-color,background-color] duration-300 ease-[cubic-bezier(0.22,0.61,0.36,1)]",
            "hover:-translate-y-0.5 hover:shadow-lift",
            // idle:虚线浅边,像未启用的工位
            state === "idle" &&
              "border-dashed border-pecker-idle-border bg-card/60 text-pecker-idle-fg hover:border-border",
            // running:浅墨青底 + 实线边 + 左侧 3px 竖条 + peck 动画(取代 breathe)
            state === "running" &&
              "border-pecker-running/40 bg-pecker-running-bg animate-pecker-peck before:absolute before:inset-y-0 before:left-0 before:w-[3px] before:bg-pecker-running",
            // done:暖绿边 + 极淡底 + 左侧竖条
            state === "done" &&
              "border-pecker-success-border bg-pecker-success-bg before:absolute before:inset-y-0 before:left-0 before:w-[3px] before:bg-pecker-success",
            // error:深校稿红 + 左侧竖条
            state === "error" &&
              "border-destructive/50 bg-destructive/[0.04] before:absolute before:inset-y-0 before:left-0 before:w-[3px] before:bg-destructive",
          )}
          style={
            state === "running"
              ? ({ "--peck-delay": `${peckDelay}s` } as CSSProperties)
              : undefined
          }
        >
          <CardContent
            className={cn(
              "flex items-start gap-3",
              isHeavy ? "p-6" : "p-5",
            )}
          >
            <StateIcon state={state} />
            <div className="min-w-0 flex-1">
              {isHeavy && (
                <div className="mb-2 flex items-center gap-2">
                  <span className="font-mono text-[9px] uppercase tracking-[0.2em] text-pecker-red/90">
                    本期 · 头版
                  </span>
                  <span className="h-px flex-1 bg-pecker-red/40" />
                </div>
              )}
              <div className="flex items-center gap-2">
                <span
                  className={cn(
                    "font-serif font-medium leading-tight tracking-tight text-foreground",
                    isHeavy ? "text-[17px]" : "text-[15px]",
                  )}
                >
                  {role.label}
                </span>
                {state === "done" && typeof itemsCount === "number" && (
                  <Badge
                    variant="outline"
                    className="h-5 rounded-sm border-pecker-success-border bg-transparent px-1.5 font-mono text-[10px] font-medium tabular-nums text-pecker-success animate-pecker-fade-in"
                  >
                    {itemsCount} 条
                  </Badge>
                )}
                {state === "running" && (
                  <Badge
                    variant="outline"
                    className="h-5 rounded-sm border-pecker-running/40 bg-transparent px-1.5 font-mono text-[10px] font-medium uppercase tracking-wide text-pecker-running"
                  >
                    Running
                  </Badge>
                )}
              </div>
              <p className="mt-1.5 truncate text-xs leading-relaxed text-muted-foreground">
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
    return <Loader2 className={cn(base, "animate-spin text-pecker-running")} />;
  if (state === "done")
    return <CheckCircle2 className={cn(base, "text-pecker-success")} />;
  return <XCircle className={cn(base, "text-destructive")} />;
}
