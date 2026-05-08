/**
 * PhaseNav · v8 顶部常驻进度条
 *
 * 6 个节点:0·1·1.5·2·3·4
 * - 1.5 是 v8 新增"运行质量检查"强制节点,用警示三角符号区分
 * - 当前高亮(accent underline + dot-halo 动画 only for phase 2)
 * - 已完成可回跳(done 色 + 点击触发 onNavigate)
 * - 未来节点弱化(neutral-300 灰)
 * - failed 节点显示 × 标记
 *
 * 规范源:design-system/啄木鸟-pecker-v8/components/phase-nav.jsx
 */

"use client";

import { Fragment } from "react";

export type PhaseId = 0 | 1 | 1.5 | 2 | 3 | 4;

interface PhaseDef {
  id: PhaseId;
  label: string;
  desc: string;
  critical?: boolean;
}

export const PHASES: readonly PhaseDef[] = Object.freeze([
  { id: 0, label: "上传 PRD", desc: "接入文档" },
  { id: 1, label: "资料预检", desc: "背景是否足够" },
  { id: 2, label: "生成意见", desc: "分方向检查" },
  { id: 1.5, label: "结果完整性", desc: "是否可继续", critical: true },
  { id: 3, label: "逐条确认", desc: "接受或驳回" },
  { id: 4, label: "导出报告", desc: "同步与归档" },
]);

type PhaseState = "current" | "done" | "future" | "failed";

interface PhaseNavProps {
  current: PhaseId;
  completed?: PhaseId[];
  failed?: PhaseId[];
  onNavigate?: (phaseId: PhaseId) => void;
  className?: string;
  style?: React.CSSProperties;
}

export function PhaseNav({
  current,
  completed = [],
  failed = [],
  onNavigate,
  className,
  style,
}: PhaseNavProps) {
  return (
    <nav
      className={className}
      style={{
        display: "flex",
        alignItems: "stretch",
        background: "var(--surface-raised)",
        borderBottom: "1px solid var(--border-default)",
        padding: "0 16px",
        fontFamily: "var(--font-sans)",
        // 窄屏允许横向滚动,不挤压文字
        overflowX: "auto",
        whiteSpace: "nowrap",
        scrollbarWidth: "thin",
        ...style,
      }}
      aria-label="评审阶段进度"
    >
      {PHASES.map((p, i) => {
        const isDone = completed.includes(p.id);
        const isCur = current === p.id;
        const isFail = failed.includes(p.id);
        const state: PhaseState = isFail
          ? "failed"
          : isCur
            ? "current"
            : isDone
              ? "done"
              : "future";
        return (
          <Fragment key={p.id}>
            <PhaseNode
              phase={p}
              state={state}
              onClick={() => onNavigate?.(p.id)}
            />
            {i < PHASES.length - 1 && (
              <PhaseConnector leftDone={isDone || isCur} />
            )}
          </Fragment>
        );
      })}
    </nav>
  );
}

interface PhaseNodeProps {
  phase: PhaseDef;
  state: PhaseState;
  onClick: () => void;
}

function PhaseNode({ phase, state, onClick }: PhaseNodeProps) {
  const colors = {
    current: {
      dot: "var(--accent-500)",
      label: "var(--text-strong)",
      ring: `0 0 0 3px color-mix(in oklch, var(--accent-500) 20%, transparent)`,
    },
    done: {
      dot: "var(--status-done-dot)",
      label: "var(--text-default)",
      ring: "none",
    },
    future: {
      dot: "var(--neutral-300)",
      label: "var(--text-faint)",
      ring: "none",
    },
    failed: {
      dot: "var(--status-failed-dot)",
      label: "var(--status-failed-fg)",
      ring: "none",
    },
  }[state];

  const clickable = state === "done" || state === "current";
  const isCritical = phase.critical;
  // Phase 2 current 态带 halo 动画,暗示"系统在跑"
  const isRunning = state === "current" && phase.id === 2;

  return (
    <button
      type="button"
      onClick={clickable ? onClick : undefined}
      disabled={!clickable}
      style={{
        display: "flex",
        alignItems: "center",
        gap: 10,
        padding: "14px 16px",
        background: "transparent",
        border: 0,
        cursor: clickable ? "pointer" : "default",
        fontFamily: "inherit",
        position: "relative",
        borderBottom:
          state === "current"
            ? "2px solid var(--accent-500)"
            : "2px solid transparent",
        marginBottom: -1,
        color: "inherit",
      }}
    >
      {/* 节点编号 / 状态符号 */}
      <span style={{ position: "relative", display: "flex" }}>
        {isCritical && state !== "current" ? (
          // 警示三角 · 只在 1.5 非当前态时出现
          <svg
            width="18"
            height="18"
            viewBox="0 0 18 18"
            style={{
              color:
                state === "done"
                  ? "var(--status-done-dot)"
                  : "var(--status-warn-dot)",
            }}
            aria-hidden
          >
            <path
              d="M9 2 L16 15 L2 15 Z"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.6"
              strokeLinejoin="round"
            />
            <circle cx="9" cy="12" r="0.9" fill="currentColor" />
            <rect x="8.3" y="6" width="1.4" height="4" fill="currentColor" />
          </svg>
        ) : (
          <span
            style={{
              width: 18,
              height: 18,
              borderRadius: "50%",
              background:
                state === "current" ? "var(--surface-raised)" : colors.dot,
              border:
                state === "current" ? `2px solid ${colors.dot}` : "none",
              boxShadow: colors.ring,
              color: "var(--surface-raised)",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              fontSize: 10,
              fontWeight: 700,
              fontFamily: "var(--font-mono)",
              animation: isRunning ? "dot-halo 2s ease-out infinite" : "none",
            }}
          >
            {state === "done" ? (
              <svg width="10" height="10" viewBox="0 0 10 10" aria-hidden>
                <path
                  d="M1.5 5 L4 7.5 L8.5 2.5"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="1.8"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </svg>
            ) : state === "failed" ? (
              "×"
            ) : state === "current" ? (
              <span
                style={{
                  width: 8,
                  height: 8,
                  borderRadius: "50%",
                  background: colors.dot,
                }}
              />
            ) : (
              ""
            )}
          </span>
        )}
      </span>

      {/* 标签 */}
      <span
        style={{
          display: "flex",
          flexDirection: "column",
          alignItems: "flex-start",
          lineHeight: 1.1,
        }}
      >
        <span
          style={{
            fontSize: 13,
            fontWeight: state === "current" ? 600 : 500,
            color: colors.label,
          }}
        >
          {phase.label}
          {phase.critical && (
            <span
              style={{
                fontSize: 10,
                marginLeft: 6,
                padding: "1px 5px",
                background: "var(--status-warn-bg)",
                color: "var(--status-warn-fg)",
                borderRadius: "var(--r-2)",
                fontWeight: 600,
              }}
            >
              必经
            </span>
          )}
        </span>
        <span
          style={{
            fontSize: 11,
            color: "var(--text-faint)",
            marginTop: 2,
          }}
        >
          {phase.desc}
        </span>
      </span>
    </button>
  );
}

interface PhaseConnectorProps {
  leftDone: boolean;
}

function PhaseConnector({ leftDone }: PhaseConnectorProps) {
  return (
    <span
      aria-hidden
      style={{
        alignSelf: "center",
        width: 20,
        height: 1,
        background: leftDone ? "var(--neutral-300)" : "var(--neutral-150)",
      }}
    />
  );
}
