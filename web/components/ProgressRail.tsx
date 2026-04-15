"use client";

/**
 * ProgressRail — Phase 2 的进度条(Phase D 编辑部版)
 *
 * 对齐 api/stream.py MILESTONES:
 *   uploaded(0) → wiki_scanned(10) → workers_started(15)
 *   → worker_done ×4 (15→70) → final_reviewer_started(70)
 *   → final_reviewer_done(95) → result(100)
 *
 * 6 个"站点"(4 个 worker_done 合并为 "4 位编辑"):
 *   [已接收] [扫 wiki] [4 位编辑] [终审开始] [终审完成] [完成]
 *
 * 视觉:
 * - 顶部:当前 stage 名(serif)+ 大号 Mono 百分比
 * - 中段:2px 扁平 track + 深色 fill(700ms ease)
 * - 底部:站点 Mono 编号(01 / 02 / ...) + 竖线 marker + label
 * - active 站点下方有一道 1.5px 的墨青 underline
 */

import { cn } from "@/lib/utils";

interface Station {
  label: string;
  threshold: number; // 进度百分比阈值
}

const STATIONS: readonly Station[] = [
  { label: "已接收", threshold: 0 },
  { label: "扫 wiki", threshold: 10 },
  { label: "4 位编辑", threshold: 15 },
  { label: "终审开始", threshold: 70 },
  { label: "终审完成", threshold: 95 },
  { label: "完成", threshold: 100 },
] as const;

export interface ProgressRailProps {
  /** 当前进度 0-100 */
  progress: number;
  /** 是否失败,失败后 rail 变红 */
  error?: boolean;
}

export function ProgressRail({ progress, error }: ProgressRailProps) {
  const clamped = Math.max(0, Math.min(100, progress));

  // 当前 active station = 最后一个 threshold ≤ progress 的站点
  let activeIndex = 0;
  for (let i = 0; i < STATIONS.length; i++) {
    if (clamped >= STATIONS[i]!.threshold) {
      activeIndex = i;
    }
  }
  const activeStation = STATIONS[activeIndex] ?? STATIONS[0]!;

  return (
    <div className="space-y-5">
      {/* ========== 顶部:stage 名 + 大号百分比 ========== */}
      <div className="flex items-baseline justify-between gap-4">
        <div className="flex items-baseline gap-2 min-w-0">
          <span className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
            Stage
          </span>
          <span className="font-serif text-base font-medium tracking-tight text-foreground truncate">
            {activeStation.label}
          </span>
        </div>
        <span
          className={cn(
            "font-mono text-2xl font-medium tabular-nums",
            error ? "text-destructive" : "text-foreground",
          )}
        >
          {clamped}
          <span className="ml-0.5 text-sm text-muted-foreground">%</span>
        </span>
      </div>

      {/* ========== 进度条:扁平 2px track + fill ========== */}
      <div className="relative h-[2px] w-full bg-border">
        <div
          className={cn(
            "absolute inset-y-0 left-0 transition-[width] duration-700 ease-[cubic-bezier(0.22,0.61,0.36,1)]",
            error ? "bg-destructive" : "bg-foreground",
          )}
          style={{ width: `${clamped}%` }}
        />
      </div>

      {/* ========== 站点编号 + 竖线 + label ========== */}
      <ol className="relative grid grid-cols-6 gap-1">
        {STATIONS.map((station, i) => {
          const passed = clamped >= station.threshold;
          const active = i === activeIndex;
          return (
            <li
              key={station.threshold}
              className="flex flex-col items-start gap-1.5"
            >
              {/* 编号 + 竖线 marker */}
              <div className="flex items-center gap-1.5">
                <span
                  className={cn(
                    "font-mono text-[10px] font-medium tabular-nums tracking-wide transition-colors duration-300",
                    !passed && "text-muted-foreground/60",
                    passed && !active && "text-foreground",
                    active && !error && "text-pecker-running",
                    active && error && "text-destructive",
                  )}
                >
                  {String(i + 1).padStart(2, "0")}
                </span>
                <span
                  aria-hidden
                  className={cn(
                    "block h-3 w-px transition-colors duration-300",
                    !passed && "bg-border",
                    passed && !active && "bg-foreground",
                    active && !error && "bg-pecker-running",
                    active && error && "bg-destructive",
                  )}
                />
              </div>
              {/* station label */}
              <span
                className={cn(
                  "block text-[11px] leading-tight transition-colors duration-300",
                  !passed && "text-muted-foreground/70",
                  passed && !active && "text-foreground",
                  active && "font-medium text-foreground",
                )}
              >
                {station.label}
              </span>
              {/* active 站点下方的 underline marker */}
              {active && (
                <span
                  aria-hidden
                  className={cn(
                    "mt-0.5 h-[1.5px] w-4 animate-pecker-fade-in",
                    error ? "bg-destructive" : "bg-pecker-running",
                  )}
                />
              )}
            </li>
          );
        })}
      </ol>
    </div>
  );
}
