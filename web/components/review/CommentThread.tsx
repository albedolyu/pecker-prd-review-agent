/**
 * CommentThread · v8 Phase 3 最高频组件
 *
 * PM 做 PRD review 90% 的时间都在这里。三元组结构:
 *   鸟头像 + 职能 + 苍鹰验证徽章 → 评审正文 → EvidenceBlock → mono 元数据 → 操作
 *
 * harness 视角关键视觉规则:
 * - 苍鹰验证徽章(EagleMark):passed ✓ / revoked ⊖ / added ＋
 * - 依据验证失败(evidence.verification === "failed")时默认折叠,需主动展开才能接受
 * - confidence < 0.7 视觉弱化
 *
 * 规范源:design-system/啄木鸟-pecker-v8/components/comment-thread.jsx
 */

"use client";

import { useState } from "react";
import { BirdLabel, type BirdId } from "@/components/birds/BirdAvatar";
import {
  EvidenceBlock,
  type EvidenceData,
} from "@/components/review/EvidenceBlock";
import { ShortcutHint } from "@/components/misc/ShortcutHint";

export type EagleMarkKind = "passed" | "revoked" | "added";

export interface CommentMeta {
  /** 用的模型(如 "sonnet-4-6") */
  model?: string;
  /** 置信度 0-1,< 0.7 视觉弱化 */
  conf?: number;
  /** token 消耗(如 "2.1k") */
  tokens?: string;
  /** 触发的 rule id(如 "R042") */
  rule?: string;
}

interface CommentThreadProps {
  birdId: BirdId;
  /** 苍鹰交叉校验结论 */
  eagleMark?: EagleMarkKind | null;
  /** 评审维度(如 "字段口径") */
  dimension?: string;
  /** 一句话摘要,粗体显示 */
  title?: string;
  /** 详细描述 */
  body?: string;
  /** 依据区:引用原文 + 验证状态 */
  evidence?: EvidenceData;
  /** 元数据(模型/conf/tokens/rule) */
  meta?: CommentMeta;
  /** 强制折叠默认值(覆盖自动折叠规则) */
  collapsedByDefault?: boolean;
  /** 当前被选中(锚点联动) */
  selected?: boolean;
  /** 已接受 / 已拒绝 / 未决 */
  accepted?: boolean;
  onAccept?: () => void;
  onReject?: () => void;
  onEdit?: () => void;
  className?: string;
  style?: React.CSSProperties;
}

export function CommentThread({
  birdId,
  eagleMark,
  dimension,
  title,
  body,
  evidence,
  meta = {},
  collapsedByDefault,
  selected = false,
  accepted,
  onAccept,
  onReject,
  onEdit,
  className,
  style,
}: CommentThreadProps) {
  const isFail = evidence?.verification === "failed";
  const lowConf = meta.conf != null && meta.conf < 0.7;
  const shouldCollapse = collapsedByDefault ?? isFail;
  const [collapsed, setCollapsed] = useState(shouldCollapse);
  const fade = isFail || lowConf;

  return (
    <article
      className={className}
      style={{
        background: selected
          ? "color-mix(in oklch, var(--accent-500) 6%, var(--surface-raised))"
          : "var(--surface-raised)",
        border: `1px solid ${
          selected
            ? "color-mix(in oklch, var(--accent-500) 35%, var(--border-default))"
            : "var(--border-default)"
        }`,
        borderLeft: selected ? "2px solid var(--accent-500)" : undefined,
        borderRadius: "var(--r-4)",
        padding: "12px 14px",
        display: "flex",
        flexDirection: "column",
        gap: 10,
        opacity:
          accepted === false ? 0.55 : fade && collapsed ? 0.7 : 1,
        ...style,
      }}
    >
      {/* ── top row · BirdLabel(色点 + 文字)代替 sm/md 头像 ── */}
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <BirdLabel id={birdId} size="md" />
        <div style={{ flex: 1, minWidth: 0 }}>
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 6,
              flexWrap: "wrap",
            }}
          >
            {dimension && (
              <span
                style={{
                  fontSize: 11,
                  padding: "1px 6px",
                  borderRadius: "var(--r-2)",
                  background: "var(--neutral-100)",
                  color: "var(--text-muted)",
                }}
              >
                {dimension}
              </span>
            )}
            {eagleMark && <EagleMark kind={eagleMark} />}
            {accepted === true && <span style={acceptedChip}>已接受</span>}
            {accepted === false && <span style={rejectedChip}>已拒绝</span>}
          </div>
        </div>
        {fade && (
          <button
            type="button"
            onClick={() => setCollapsed((c) => !c)}
            style={linkBtn}
          >
            {collapsed ? "展开" : "折叠"}
          </button>
        )}
      </div>

      {/* ── title ── */}
      {title && (
        <div
          style={{
            fontSize: 14,
            fontWeight: 500,
            color: "var(--text-strong)",
            lineHeight: 1.5,
            textWrap: "pretty",
          }}
        >
          {title}
        </div>
      )}

      {!collapsed && (
        <>
          {/* ── body ── */}
          {body && (
            <div
              style={{
                fontSize: 13,
                color: "var(--text-default)",
                lineHeight: 1.6,
              }}
            >
              {body}
            </div>
          )}

          {/* ── evidence ── */}
          {evidence && <EvidenceBlock {...evidence} />}

          {/* ── meta ── */}
          <div
            style={{
              display: "flex",
              flexWrap: "wrap",
              gap: "3px 12px",
              fontFamily: "var(--font-mono)",
              fontSize: 11,
              color: "var(--text-muted)",
              fontVariantNumeric: "tabular-nums",
            }}
          >
            {meta.model && <MetaChip k="model" v={meta.model} />}
            {meta.conf != null && (
              <MetaChip k="conf" v={meta.conf.toFixed(2)} emph={lowConf} />
            )}
            {meta.tokens && <MetaChip k="tokens" v={meta.tokens} />}
            {meta.rule && <MetaChip k="rule" v={meta.rule} />}
          </div>

          {/* ── actions ── */}
          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              gap: 8,
              marginTop: 2,
            }}
          >
            <div style={{ display: "flex", gap: 6 }}>
              <button
                type="button"
                style={btnAccept}
                disabled={accepted === true}
                onClick={onAccept}
              >
                接受
              </button>
              <button
                type="button"
                style={btnReject}
                disabled={accepted === false}
                onClick={onReject}
              >
                拒绝
              </button>
              <button type="button" style={btnEdit} onClick={onEdit}>
                编辑
              </button>
            </div>
            <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
              <ShortcutHint keys={["y"]} label="接受" />
              <ShortcutHint keys={["n"]} label="拒绝" />
            </div>
          </div>
        </>
      )}

      {collapsed && fade && (
        <div
          style={{
            fontSize: 11,
            color: "var(--text-muted)",
            padding: "2px 0",
          }}
        >
          {isFail ? "依据验证失败 · 需展开确认后才能接受" : "置信度偏低 · 已弱化"}
        </div>
      )}
    </article>
  );
}

/** 苍鹰交叉校验徽章 */
export function EagleMark({ kind }: { kind: EagleMarkKind }) {
  const map = {
    passed: {
      icon: "✓",
      bg: "color-mix(in oklch, var(--bird-5) 10%, var(--surface-sunken))",
      fg: "var(--bird-5)",
      label: "苍鹰通过",
    },
    revoked: {
      icon: "⊖",
      bg: "var(--status-failed-bg)",
      fg: "var(--status-failed-fg)",
      label: "苍鹰撤回",
    },
    added: {
      icon: "＋",
      bg: "color-mix(in oklch, var(--bird-5) 10%, var(--surface-sunken))",
      fg: "var(--bird-5)",
      label: "苍鹰补充",
    },
  }[kind];

  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 4,
        padding: "1px 7px",
        borderRadius: "var(--r-pill)",
        background: map.bg,
        color: map.fg,
        fontSize: 11,
        fontWeight: 600,
      }}
    >
      <span style={{ fontSize: 10, lineHeight: 1 }}>{map.icon}</span>
      {map.label}
    </span>
  );
}

interface MetaChipProps {
  k: string;
  v: string;
  /** emph: true 表示该元数据值需要强调(如 conf < 0.7) */
  emph?: boolean;
}

function MetaChip({ k, v, emph }: MetaChipProps) {
  return (
    <span
      style={{
        display: "inline-flex",
        gap: 3,
        color: emph ? "var(--status-warn-fg)" : "var(--text-muted)",
      }}
    >
      <span style={{ opacity: 0.6 }}>{k}=</span>
      <span style={{ color: emph ? "var(--status-warn-fg)" : "var(--text-default)" }}>
        {v}
      </span>
    </span>
  );
}

// ============================================================
// styles

const linkBtn: React.CSSProperties = {
  background: "transparent",
  border: 0,
  color: "var(--text-link)",
  fontSize: 11,
  cursor: "pointer",
  padding: 0,
  fontFamily: "var(--font-sans)",
  fontWeight: 500,
};
const btnAccept: React.CSSProperties = {
  padding: "5px 12px",
  border: 0,
  borderRadius: "var(--r-3)",
  background: "var(--accent-500)",
  color: "var(--accent-fg)",
  fontSize: 12,
  fontWeight: 600,
  cursor: "pointer",
  fontFamily: "var(--font-sans)",
};
const btnReject: React.CSSProperties = {
  padding: "5px 12px",
  border: "1px solid var(--border-default)",
  borderRadius: "var(--r-3)",
  background: "var(--surface-raised)",
  color: "var(--text-default)",
  fontSize: 12,
  fontWeight: 500,
  cursor: "pointer",
  fontFamily: "var(--font-sans)",
};
const btnEdit: React.CSSProperties = {
  ...btnReject,
  color: "var(--text-muted)",
};
const acceptedChip: React.CSSProperties = {
  fontSize: 10,
  padding: "1px 6px",
  borderRadius: "var(--r-2)",
  background: "var(--status-done-bg)",
  color: "var(--status-done-fg)",
  fontWeight: 600,
};
const rejectedChip: React.CSSProperties = {
  fontSize: 10,
  padding: "1px 6px",
  borderRadius: "var(--r-2)",
  background: "var(--neutral-100)",
  color: "var(--text-muted)",
  fontWeight: 600,
};
