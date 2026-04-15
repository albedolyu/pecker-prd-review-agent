"use client";

/**
 * ProgressRail — Phase 2 的 8 milestone 横向进度条
 *
 * 对齐 api/stream.py MILESTONES:
 *   uploaded(0) → wiki_scanned(10) → workers_started(15)
 *   → worker_done ×4 (15→70) → final_reviewer_started(70)
 *   → final_reviewer_done(95) → result(100)
 *
 * 实现上分成 6 个"站点"(把 4 个 worker_done 合成一个 "4 位编辑"):
 *   [已接收] [扫 wiki] [4 位编辑] [终审开始] [终审完成] [完成]
 *
 * 用 shadcn Progress 做底色条,站点用 dot 叠在上面。
 */

import { cn } from "@/lib/utils";
import { Progress } from "@/components/ui/progress";

interface Station {
  label: string;
  at: number; // 进度百分比阈值
}

const STATIONS: readonly Station[] = [
  { label: "已接收", at: 0 },
  { label: "扫 wiki", at: 10 },
  { label: "4 位编辑", at: 15 },
  { label: "终审开始", at: 70 },
  { label: "终审完成", at: 95 },
  { label: "完成", at: 100 },
] as const;

export interface ProgressRailProps {
  /** 当前进度 0-100 */
  progress: number;
  /** 是否失败,失败后 rail 变红 */
  error?: boolean;
}

export function ProgressRail({ progress, error }: ProgressRailProps) {
  const clamped = Math.max(0, Math.min(100, progress));

  return (
    <div className="space-y-2">
      <Progress
        value={clamped}
        className={cn("h-2", error && "[&>div]:bg-destructive")}
      />
      <ol className="relative flex justify-between px-0.5">
        {STATIONS.map((station) => {
          const passed = clamped >= station.at;
          const active =
            !error &&
            clamped >= station.at &&
            clamped < (STATIONS.find((s) => s.at > station.at)?.at ?? 101);
          return (
            <li
              key={station.at}
              className="flex flex-col items-center gap-1 text-[10px]"
            >
              <span
                className={cn(
                  "block h-2 w-2 rounded-full transition-colors",
                  !passed && "bg-muted-foreground/30",
                  passed && !error && "bg-primary",
                  active && "ring-2 ring-primary/40 ring-offset-1",
                  passed && error && "bg-destructive",
                )}
              />
              <span
                className={cn(
                  "whitespace-nowrap transition-colors",
                  passed ? "text-foreground" : "text-muted-foreground",
                )}
              >
                {station.label}
              </span>
            </li>
          );
        })}
      </ol>
      <div className="text-right text-xs text-muted-foreground tabular-nums">
        {clamped}%
      </div>
    </div>
  );
}
