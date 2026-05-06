/**
 * AgentStatusCard · v8 Phase 2 核心
 *
 * Agent 调度中心里每只鸟一张卡:头像 + 职能 + 状态 pill + 进度条 + mono 元数据 + 失败 recovery。
 *
 * - variant: worker | meta(苍鹰)
 * - 四态:queued / running / done / failed
 * - failReason:quota_exhausted / tool_call_failed / json_parse_error / empty_submission / timeout
 * - 底部/顶部 anchor(依赖边连接点)
 *
 * 规范源:design-system/啄木鸟-pecker-v8/components/agent-status-card.jsx
 */

import { BirdAvatar, type BirdId } from "@/components/birds/BirdAvatar";

export type AgentStatus = "queued" | "running" | "done" | "failed";
export type AgentVariant = "worker" | "meta";
export type FailReason =
  | "quota_exhausted"
  | "tool_call_failed"
  | "json_parse_error"
  | "empty_submission"
  | "timeout";

interface AgentStatusCardProps {
  birdId: BirdId;
  status: AgentStatus;
  /** 0-100 */
  progress?: number;
  /** token 消耗,如 "2.1k" */
  tokens?: string;
  /** 耗时,如 "12.4s" */
  elapsed?: string;
  /** 模型,如 "sonnet-4-6" */
  model?: string;
  /** 已提交 items 数量 */
  submissions?: number;
  /** 子状态文案(苍鹰用:等待 worker 完成 / 交叉校验中 / 漏报补充 3/5) */
  note?: string;
  failReason?: FailReason;
  variant?: AgentVariant;
  onRetry?: () => void;
  className?: string;
  style?: React.CSSProperties;
}

const BIRD_LABELS: Record<BirdId, string> = {
  1: "业务",
  2: "数据",
  3: "体验",
  4: "风险",
  5: "苍鹰",
  6: "bird-06",
  7: "bird-07",
  8: "bird-08",
  9: "bird-09",
  10: "bird-10",
};

const BIRD_FUNCTIONS: Record<BirdId, string> = {
  1: "业务逻辑完整性",
  2: "数据字段 / 指标",
  3: "UX 流程 / 交互",
  4: "风险 / 合规 / 依赖",
  5: "交叉校验 + 漏报补充",
  6: "未上线",
  7: "未上线",
  8: "未上线",
  9: "未上线",
  10: "未上线",
};

export function AgentStatusCard({
  birdId,
  status,
  progress = 0,
  tokens,
  elapsed,
  model = "sonnet-4-6",
  submissions,
  note,
  failReason,
  variant = "worker",
  onRetry,
  className,
  style,
}: AgentStatusCardProps) {
  const label = BIRD_LABELS[birdId];
  const fn = BIRD_FUNCTIONS[birdId];
  const isMeta = variant === "meta";
  const showProgress = status === "running";
  const isFailed = status === "failed";

  return (
    <div
      className={className}
      style={{
        position: "relative",
        background: "var(--surface-raised)",
        border: `1px solid ${
          isFailed
            ? "color-mix(in oklch, var(--status-failed-dot) 30%, var(--border-default))"
            : "var(--border-default)"
        }`,
        borderRadius: "var(--r-4)",
        padding: "14px 16px",
        width: "100%",
        boxShadow: status === "running" ? "var(--shadow-sm)" : "none",
        display: "flex",
        flexDirection: "column",
        gap: 10,
        ...style,
      }}
    >
      {/* top row */}
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <BirdAvatar
          id={birdId}
          size="lg"
          status={dotStatus(status)}
        />
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            minWidth: 0,
            flex: 1,
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <span
              style={{
                fontSize: 14,
                fontWeight: 600,
                color: "var(--text-strong)",
              }}
            >
              {label}鸟
            </span>
            {isMeta && <MetaTag />}
          </div>
          <span
            style={{
              fontSize: 12,
              color: "var(--text-muted)",
              marginTop: 1,
            }}
          >
            {fn}
          </span>
        </div>
        <StatusPill status={status} note={note} />
      </div>

      {/* progress(仅 running) */}
      {showProgress && (
        <div
          style={{
            height: 4,
            background: "var(--neutral-100)",
            borderRadius: "var(--r-2)",
            overflow: "hidden",
            position: "relative",
          }}
        >
          <div
            style={{
              width: `${Math.min(100, Math.max(0, progress))}%`,
              height: "100%",
              background: "var(--accent-500)",
              transition: "width var(--dur-slow) var(--ease-out)",
            }}
          />
        </div>
      )}

      {/* 主指标:已提交意见数 + 失败原因(优先级最高,PM 第一眼看到的) */}
      {(submissions != null || (isFailed && failReason)) && (
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 8,
            flexWrap: "wrap",
            fontSize: 12,
            color: "var(--text-default)",
          }}
        >
          {submissions != null && (
            <span
              style={{
                display: "inline-flex",
                alignItems: "baseline",
                gap: 4,
              }}
            >
              <span
                style={{
                  fontSize: 18,
                  fontWeight: 600,
                  color: "var(--text-strong)",
                  fontVariantNumeric: "tabular-nums",
                  lineHeight: 1,
                }}
              >
                {submissions}
              </span>
              <span style={{ fontSize: 11, color: "var(--text-muted)" }}>
                条意见
              </span>
            </span>
          )}
          {isFailed && failReason && (
            <span
              style={{
                fontSize: 11,
                padding: "2px 8px",
                borderRadius: "var(--r-2)",
                background: "var(--status-failed-bg)",
                color: "var(--status-failed-fg)",
                fontWeight: 600,
              }}
              title={failReason}
            >
              {failMessage(failReason)}
            </span>
          )}
        </div>
      )}

      {/* 处理详情默认只露出耗时,避免把模型与 token 信息放到 PM 主视图里 */}
      {elapsed && (
        <div
          style={{
            display: "flex",
            flexWrap: "wrap",
            gap: "2px 10px",
            fontSize: 10,
            color: "var(--text-faint)",
            fontVariantNumeric: "tabular-nums",
          }}
          title={`处理详情 · 耗时 ${elapsed}${
            tokens ? ` · 处理量 ${tokens}` : ""
          }${model ? " · 模型由系统自动选择" : ""}`}
        >
          <span>耗时 {elapsed}</span>
        </div>
      )}

      {/* failure recovery */}
      {isFailed && (
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            padding: "8px 10px",
            background: "var(--status-failed-bg)",
            borderRadius: "var(--r-3)",
            border:
              "1px solid color-mix(in oklch, var(--status-failed-dot) 20%, transparent)",
            fontSize: 12,
            color: "var(--status-failed-fg)",
          }}
        >
          <span>{failMessage(failReason)}</span>
          {onRetry && (
            <button
              type="button"
              onClick={onRetry}
              style={{
                padding: "4px 10px",
                border: 0,
                borderRadius: "var(--r-3)",
                background: "var(--status-failed-fg)",
                color: "var(--neutral-0)",
                fontSize: 11,
                fontWeight: 600,
                cursor: "pointer",
                fontFamily: "inherit",
              }}
            >
              重跑
            </button>
          )}
        </div>
      )}

      {/* anchor · worker 在底部 / meta 在顶部(给依赖边 SVG 连线用) */}
      {!isMeta && (
        <span
          className="worker-anchor"
          data-bird-id={birdId}
          style={{
            position: "absolute",
            left: "50%",
            bottom: -5,
            transform: "translateX(-50%)",
            width: 8,
            height: 8,
            borderRadius: "50%",
            background:
              status === "done"
                ? "var(--status-done-dot)"
                : status === "running"
                  ? "var(--accent-500)"
                  : "var(--neutral-300)",
            border: "2px solid var(--surface-canvas)",
            zIndex: 1,
          }}
        />
      )}
      {isMeta && (
        <span
          className="meta-anchor"
          style={{
            position: "absolute",
            left: "50%",
            top: -6,
            transform: "translateX(-50%) rotate(45deg)",
            width: 10,
            height: 10,
            background:
              status === "queued" ? "var(--neutral-200)" : "var(--bird-5)",
            border: "2px solid var(--surface-canvas)",
            zIndex: 1,
          }}
        />
      )}
    </div>
  );
}

// ============================================================
// subcomponents

function dotStatus(s: AgentStatus) {
  return s;
}

function failMessage(r?: FailReason): string {
  if (!r) return "未完成";
  return {
    quota_exhausted: "评审额度不足",
    tool_call_failed: "评审服务异常",
    json_parse_error: "结果格式不完整",
    empty_submission: "暂未产出意见",
    timeout: "耗时过长",
  }[r];
}

function MetaTag() {
  return (
    <span
      style={{
        fontSize: 10,
        fontWeight: 600,
        padding: "1px 6px",
        borderRadius: "var(--r-2)",
        background: "color-mix(in oklch, var(--bird-5) 15%, transparent)",
        color: "var(--bird-5)",
      }}
    >
      交叉校验
    </span>
  );
}

interface StatusPillProps {
  status: AgentStatus;
  note?: string;
}

function StatusPill({ status, note }: StatusPillProps) {
  const map: Record<AgentStatus, { bg: string; fg: string; label: string }> = {
    queued: {
      bg: "var(--status-queued-bg)",
      fg: "var(--status-queued-fg)",
      label: note || "等待运行",
    },
    running: {
      bg: "var(--status-running-bg)",
      fg: "var(--status-running-fg)",
      label: note || "审稿中",
    },
    done: {
      bg: "var(--status-done-bg)",
      fg: "var(--status-done-fg)",
      label: note || "已完成",
    },
    failed: {
      bg: "var(--status-failed-bg)",
      fg: "var(--status-failed-fg)",
      label: note || "未完成",
    },
  };
  const tok = map[status];
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 6,
        padding: "3px 9px",
        borderRadius: "var(--r-pill)",
        background: tok.bg,
        color: tok.fg,
        fontSize: 11,
        fontWeight: 600,
        whiteSpace: "nowrap",
      }}
    >
      <span
        style={{
          width: 6,
          height: 6,
          borderRadius: "50%",
          background:
            status === "queued"
              ? "var(--status-queued-dot)"
              : status === "running"
                ? "var(--status-running-dot)"
                : status === "done"
                  ? "var(--status-done-dot)"
                  : "var(--status-failed-dot)",
          animation:
            status === "running"
              ? "dot-breathe 1.4s var(--ease-out) infinite"
              : "none",
        }}
      />
      {tok.label}
    </span>
  );
}
