"use client";

/**
 * /system/prompts · v8 Sprint 5(v2 预留)
 *
 * Prompt / Rule 透明度 · 让 PM 看见每只鸟当前用的 prompt 摘要 + 激活的 rule 集。
 * 数据来源:
 *   - GET /api/prompts/:bird_id(prompt 版本 + 摘要)
 *   - GET /api/feedback/rules?dim=structure(该维度当前激活 rule)
 *   - POST /api/feedback/rules/:rule_id/override(临时覆盖权重,reload 后失效)
 * 当前用 sample 数据演示 UI 壳。
 */

import { useState } from "react";
import Link from "next/link";
import { BirdAvatar, type BirdId } from "@/components/birds/BirdAvatar";
import { BirdBadge, BIRD_META } from "@/components/birds/BirdBadge";

// ============================================================
// sample data

interface PromptMeta {
  version: string;
  updated: string;
  model: string;
  temperature: number;
  maxTokens: number;
  summary: string;
  /** 当前 session 注入的动态规则(反馈闭环 EMA 结果) */
  injectedRules: string[];
}

interface RuleEntry {
  id: string;
  name: string;
  weight: number;
  hits7d: number;
  rejects7d: number;
  severity: "must" | "should" | "suggest";
  status: "active" | "shadow" | "disabled";
}

const PROMPTS: Record<BirdId, PromptMeta | null> = {
  1: {
    version: "biz-v2.3",
    updated: "2026-04-15",
    model: "sonnet-4-6",
    temperature: 0.2,
    maxTokens: 4096,
    summary:
      "你是业务鸟,只看业务完整性。检查业务目标 → 目标人群 → 核心场景 → 关键指标的闭环。对以下内容零容忍:目标没有数字 / 人群画像缺失 / 核心场景无触发条件 / 指标无计算口径。",
    injectedRules: ["R042", "R133", "R087"],
  },
  2: {
    version: "data-v1.8",
    updated: "2026-04-17",
    model: "sonnet-4-6",
    temperature: 0.15,
    maxTokens: 4096,
    summary:
      "你是数据鸟,只看字段口径和跨表一致性。DDL 核对 / JOIN 关联键 / 口径冲突是你的三个主战场。如果 PRD 引用了字段却没说来自哪张表,这是零容忍。",
    injectedRules: ["R203", "R211", "R224"],
  },
  3: {
    version: "ux-v2.1",
    updated: "2026-04-12",
    model: "sonnet-4-6",
    temperature: 0.3,
    maxTokens: 4096,
    summary:
      "你是体验鸟(原审校),看 UX 流程和交互一致性。文案歧义 / 状态缺失 / 异常流未定义是主要 findings。",
    injectedRules: ["R091", "R105"],
  },
  4: {
    version: "risk-v1.5",
    updated: "2026-04-16",
    model: "opus-4", // 深推理
    temperature: 0.25,
    maxTokens: 6144,
    summary:
      "你是风险鸟(原 AI coding),看技术风险 / 依赖 SLA / 合规。下游服务未标 SLA 是零容忍。涉及跨 team 依赖时必须列清责任边界。",
    injectedRules: ["R109", "R154", "R168"],
  },
  5: {
    version: "eagle-v3.0",
    updated: "2026-04-18",
    model: "opus-4",
    temperature: 0.1,
    maxTokens: 8192,
    summary:
      "你是苍鹰(meta-reviewer),4 worker 跑完之后才登场。你只做一件事:交叉校验 worker 产出。撤回证据不足的 / 补充明显遗漏的(最多 2 条 · 硬上限)。你 **绝对不** 重审已经说过的内容。",
    injectedRules: ["META-001", "META-002", "META-dedup"],
  },
  6: null,
  7: null,
  8: null,
  9: null,
  10: null,
};

const RULES: Record<BirdId, RuleEntry[]> = {
  1: [
    { id: "R042", name: "业务目标必须有数字", weight: 0.92, hits7d: 42, rejects7d: 3, severity: "must", status: "active" },
    { id: "R133", name: "目标人群画像完整性", weight: 0.84, hits7d: 28, rejects7d: 5, severity: "should", status: "active" },
    { id: "R087", name: "注册流程文案歧义(shadow)", weight: 0.62, hits7d: 8, rejects7d: 11, severity: "suggest", status: "shadow" },
    { id: "R057", name: "北极星指标对齐", weight: 0.7, hits7d: 15, rejects7d: 4, severity: "should", status: "active" },
  ],
  2: [
    { id: "R203", name: "跨表 user_level 口径", weight: 0.88, hits7d: 34, rejects7d: 2, severity: "must", status: "active" },
    { id: "R211", name: "补偿逻辑定义", weight: 0.58, hits7d: 12, rejects7d: 8, severity: "should", status: "shadow" },
    { id: "R224", name: "DDL 字段缺失扫描", weight: 0.81, hits7d: 22, rejects7d: 3, severity: "must", status: "active" },
  ],
  3: [
    { id: "R091", name: "异常流未定义", weight: 0.76, hits7d: 18, rejects7d: 5, severity: "should", status: "active" },
    { id: "R105", name: "文案 i18n 一致性", weight: 0.65, hits7d: 10, rejects7d: 3, severity: "suggest", status: "active" },
  ],
  4: [
    { id: "R109", name: "下游服务 SLA 声明", weight: 0.78, hits7d: 20, rejects7d: 4, severity: "must", status: "active" },
    { id: "R154", name: "跨 team 责任边界", weight: 0.72, hits7d: 16, rejects7d: 6, severity: "should", status: "active" },
    { id: "R168", name: "合规敏感字段", weight: 0.85, hits7d: 9, rejects7d: 1, severity: "must", status: "active" },
  ],
  5: [
    { id: "META-001", name: "依据必须可验证 · Side Query", weight: 1.0, hits7d: 87, rejects7d: 0, severity: "must", status: "active" },
    { id: "META-002", name: "漏报补充 ≤ 2 条(硬上限)", weight: 1.0, hits7d: 45, rejects7d: 0, severity: "must", status: "active" },
    { id: "META-dedup", name: "去重保留最高 confidence", weight: 0.95, hits7d: 52, rejects7d: 2, severity: "should", status: "active" },
  ],
  6: [],
  7: [],
  8: [],
  9: [],
  10: [],
};

// ============================================================

const BIRD_TABS: BirdId[] = [1, 2, 3, 4, 5];

export default function SystemPromptsPage() {
  const [selected, setSelected] = useState<BirdId>(1);
  const prompt = PROMPTS[selected];
  const rules = RULES[selected] ?? [];

  return (
    <div
      style={{
        maxWidth: 1120,
        margin: "0 auto",
        padding: "28px 24px 80px",
        fontFamily: "var(--font-sans)",
        background: "var(--surface-canvas)",
        minHeight: "100vh",
      }}
    >
      <header style={{ marginBottom: 16 }}>
        <div
          style={{
            fontSize: 10,
            fontFamily: "var(--font-mono)",
            fontWeight: 600,
            textTransform: "uppercase",
            letterSpacing: "0.1em",
            color: "var(--accent-600)",
            marginBottom: 4,
          }}
        >
          Harness · Prompts & Rules
        </div>
        <h1
          style={{
            fontSize: 22,
            fontWeight: 600,
            color: "var(--text-strong)",
            margin: 0,
            letterSpacing: "-0.015em",
          }}
        >
          Prompt / Rule 透明度
        </h1>
        <p
          style={{
            fontSize: 13,
            color: "var(--text-muted)",
            marginTop: 4,
            lineHeight: 1.55,
          }}
        >
          看每只鸟当前的 prompt 摘要 + 激活的 rule 集 + 本周 hit/reject · 未来支持&ldquo;临时覆盖权重&rdquo;做实验
        </p>
      </header>

      <div
        style={{
          marginBottom: 16,
          padding: "8px 14px",
          borderRadius: "var(--r-3)",
          border: "1px dashed var(--border-default)",
          background: "var(--status-warn-bg)",
          color: "var(--status-warn-fg)",
          fontSize: 12,
        }}
      >
        <strong style={{ fontWeight: 600 }}>Sprint 5 · v2 预留</strong> · sample 数据。真实接入{" "}
        <code style={{ fontFamily: "var(--font-mono)" }}>/api/prompts/:bird_id</code> +{" "}
        <code style={{ fontFamily: "var(--font-mono)" }}>/api/feedback/rules</code> 在 v2 做。
      </div>

      {/* 鸟 tabs */}
      <div
        style={{
          display: "flex",
          gap: 8,
          flexWrap: "wrap",
          marginBottom: 16,
        }}
      >
        {BIRD_TABS.map((id) => (
          <button
            key={id}
            type="button"
            onClick={() => setSelected(id)}
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 6,
              padding: "6px 12px",
              borderRadius: "var(--r-3)",
              border: `1px solid ${
                selected === id
                  ? "var(--accent-500)"
                  : "var(--border-default)"
              }`,
              background:
                selected === id
                  ? "var(--accent-50)"
                  : "var(--surface-raised)",
              color:
                selected === id
                  ? "var(--accent-700)"
                  : "var(--text-default)",
              fontSize: 13,
              fontWeight: 500,
              cursor: "pointer",
              fontFamily: "var(--font-sans)",
              transition: "all var(--dur-fast) var(--ease-out)",
            }}
          >
            <BirdAvatar id={id} size="sm" />
            <span>{BIRD_META[id].label}鸟</span>
            <span
              style={{
                fontFamily: "var(--font-mono)",
                fontSize: 10,
                color:
                  selected === id
                    ? "var(--accent-600)"
                    : "var(--text-muted)",
              }}
            >
              ({(RULES[id] ?? []).length})
            </span>
          </button>
        ))}
      </div>

      {prompt ? (
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "1fr 380px",
            gap: 16,
          }}
        >
          {/* prompt 摘要 */}
          <section style={cardStyle}>
            <header
              style={{
                padding: "14px 18px",
                borderBottom: "1px solid var(--border-subtle)",
                display: "flex",
                alignItems: "center",
                gap: 10,
              }}
            >
              <BirdAvatar id={selected} size="lg" />
              <div>
                <div
                  style={{
                    fontSize: 14,
                    fontWeight: 600,
                    color: "var(--text-strong)",
                  }}
                >
                  {BIRD_META[selected].label}鸟 · Prompt
                </div>
                <div
                  style={{
                    fontSize: 11,
                    fontFamily: "var(--font-mono)",
                    color: "var(--text-muted)",
                    marginTop: 2,
                  }}
                >
                  {prompt.version} · updated {prompt.updated}
                </div>
              </div>
              <span style={{ flex: 1 }} />
              <BirdBadge id={selected} />
            </header>
            <div
              style={{
                padding: "14px 18px",
                display: "grid",
                gridTemplateColumns: "repeat(4, 1fr)",
                gap: 12,
                borderBottom: "1px solid var(--border-subtle)",
              }}
            >
              <MetaField label="model" value={prompt.model} />
              <MetaField
                label="temperature"
                value={prompt.temperature.toFixed(2)}
                mono
              />
              <MetaField
                label="max tokens"
                value={String(prompt.maxTokens)}
                mono
              />
              <MetaField
                label="injected rules"
                value={String(prompt.injectedRules.length)}
                mono
              />
            </div>
            <div style={{ padding: "14px 18px" }}>
              <div
                style={{
                  fontSize: 10,
                  fontFamily: "var(--font-mono)",
                  fontWeight: 600,
                  color: "var(--text-faint)",
                  textTransform: "uppercase",
                  letterSpacing: "0.08em",
                  marginBottom: 8,
                }}
              >
                prompt summary
              </div>
              <p
                style={{
                  margin: 0,
                  fontSize: 13,
                  lineHeight: 1.7,
                  color: "var(--text-default)",
                }}
              >
                {prompt.summary}
              </p>
              <div
                style={{
                  marginTop: 14,
                  display: "flex",
                  gap: 8,
                  flexWrap: "wrap",
                }}
              >
                {prompt.injectedRules.map((r) => (
                  <code
                    key={r}
                    style={{
                      fontFamily: "var(--font-mono)",
                      fontSize: 11,
                      padding: "2px 8px",
                      borderRadius: "var(--r-2)",
                      background: "var(--accent-50)",
                      color: "var(--accent-700)",
                      fontWeight: 600,
                    }}
                  >
                    {r}
                  </code>
                ))}
              </div>
            </div>
          </section>

          {/* side · 操作 */}
          <aside
            style={{
              ...cardStyle,
              padding: "14px 18px",
              height: "fit-content",
            }}
          >
            <div
              style={{
                fontSize: 13,
                fontWeight: 600,
                color: "var(--text-strong)",
                marginBottom: 6,
              }}
            >
              临时覆盖(v2)
            </div>
            <p
              style={{
                fontSize: 12,
                color: "var(--text-muted)",
                lineHeight: 1.55,
                margin: "0 0 12px",
              }}
            >
              下次 run 可以临时调整某条 rule 的权重 · 只影响本次 session,reload 后失效 · 方便做 AB 实验
            </p>
            <button
              type="button"
              disabled
              style={{
                width: "100%",
                height: 32,
                border: "1px dashed var(--border-default)",
                borderRadius: "var(--r-3)",
                background: "var(--surface-sunken)",
                color: "var(--text-muted)",
                fontSize: 12,
                fontWeight: 500,
                cursor: "not-allowed",
                fontFamily: "var(--font-sans)",
              }}
            >
              发起一次临时覆盖 · v2 启用
            </button>
          </aside>

          {/* rules 表 */}
          <section style={{ ...cardStyle, gridColumn: "1 / -1" }}>
            <header
              style={{
                padding: "12px 18px",
                borderBottom: "1px solid var(--border-subtle)",
                display: "flex",
                alignItems: "baseline",
                gap: 8,
              }}
            >
              <div
                style={{
                  fontSize: 13,
                  fontWeight: 600,
                  color: "var(--text-strong)",
                }}
              >
                激活 rule 集
              </div>
              <div style={{ fontSize: 11, color: "var(--text-muted)" }}>
                {rules.length} 条 · 本周 hit/reject · 按权重降序
              </div>
            </header>
            <table
              style={{
                width: "100%",
                borderCollapse: "collapse",
                fontSize: 12,
              }}
            >
              <thead>
                <tr>
                  {[
                    "rule",
                    "name",
                    "severity",
                    "status",
                    "weight",
                    "hits 7d",
                    "rejects 7d",
                    "reject %",
                  ].map((h) => (
                    <th
                      key={h}
                      style={{
                        textAlign: "left",
                        padding: "10px 14px",
                        fontSize: 10,
                        fontFamily: "var(--font-mono)",
                        color: "var(--text-faint)",
                        textTransform: "uppercase",
                        letterSpacing: "0.08em",
                        borderBottom: "1px solid var(--border-subtle)",
                        fontWeight: 600,
                      }}
                    >
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {[...rules]
                  .sort((a, b) => b.weight - a.weight)
                  .map((r) => {
                    const rejectRate =
                      r.rejects7d / (r.hits7d + r.rejects7d);
                    const highReject = rejectRate > 0.4;
                    return (
                      <tr key={r.id}>
                        <td style={tdStyle}>
                          <code
                            style={{
                              fontFamily: "var(--font-mono)",
                              fontSize: 12,
                              color: "var(--text-strong)",
                              fontWeight: 600,
                            }}
                          >
                            {r.id}
                          </code>
                        </td>
                        <td style={tdStyle}>{r.name}</td>
                        <td style={tdStyle}>
                          <SeverityChip severity={r.severity} />
                        </td>
                        <td style={tdStyle}>
                          <StatusChip status={r.status} />
                        </td>
                        <td
                          style={{
                            ...tdStyle,
                            fontFamily: "var(--font-mono)",
                            fontVariantNumeric: "tabular-nums",
                          }}
                        >
                          {r.weight.toFixed(2)}
                        </td>
                        <td
                          style={{
                            ...tdStyle,
                            fontFamily: "var(--font-mono)",
                            fontVariantNumeric: "tabular-nums",
                          }}
                        >
                          {r.hits7d}
                        </td>
                        <td
                          style={{
                            ...tdStyle,
                            fontFamily: "var(--font-mono)",
                            fontVariantNumeric: "tabular-nums",
                            color: highReject
                              ? "var(--status-failed-fg)"
                              : "var(--text-default)",
                          }}
                        >
                          {r.rejects7d}
                        </td>
                        <td
                          style={{
                            ...tdStyle,
                            fontFamily: "var(--font-mono)",
                            fontVariantNumeric: "tabular-nums",
                            color: highReject
                              ? "var(--status-failed-fg)"
                              : "var(--text-muted)",
                            fontWeight: highReject ? 600 : 400,
                          }}
                        >
                          {(rejectRate * 100).toFixed(0)}%
                          {highReject && " ⚠"}
                        </td>
                      </tr>
                    );
                  })}
              </tbody>
            </table>
          </section>
        </div>
      ) : (
        <div
          style={{
            ...cardStyle,
            padding: "40px 20px",
            textAlign: "center",
            color: "var(--text-muted)",
          }}
        >
          该鸟尚未上线 · 无 prompt / rule 数据
        </div>
      )}

      {/* footer */}
      <footer
        style={{
          marginTop: 20,
          paddingTop: 16,
          borderTop: "1px solid var(--border-subtle)",
          display: "flex",
          justifyContent: "space-between",
          fontSize: 11,
          color: "var(--text-faint)",
          fontFamily: "var(--font-mono)",
        }}
      >
        <Link
          href="/system/health"
          style={{ color: "var(--text-muted)", textDecoration: "none" }}
        >
          ← /system/health
        </Link>
        <span>pecker · harness v8 · system/prompts · sample</span>
      </footer>
    </div>
  );
}

// ============================================================

function MetaField({
  label,
  value,
  mono,
}: {
  label: string;
  value: string;
  mono?: boolean;
}) {
  return (
    <div>
      <div
        style={{
          fontSize: 10,
          fontFamily: "var(--font-mono)",
          color: "var(--text-faint)",
          textTransform: "uppercase",
          letterSpacing: "0.08em",
        }}
      >
        {label}
      </div>
      <div
        style={{
          fontSize: 13,
          color: "var(--text-default)",
          marginTop: 2,
          fontFamily: mono ? "var(--font-mono)" : "var(--font-sans)",
          fontVariantNumeric: "tabular-nums",
          wordBreak: "break-all",
        }}
      >
        {value}
      </div>
    </div>
  );
}

function SeverityChip({
  severity,
}: {
  severity: "must" | "should" | "suggest";
}) {
  const cfg = {
    must: {
      bg: "var(--status-failed-bg)",
      fg: "var(--status-failed-fg)",
    },
    should: {
      bg: "var(--status-warn-bg)",
      fg: "var(--status-warn-fg)",
    },
    suggest: { bg: "var(--neutral-100)", fg: "var(--text-muted)" },
  }[severity];
  return (
    <span
      style={{
        fontSize: 10,
        padding: "1px 6px",
        borderRadius: "var(--r-2)",
        background: cfg.bg,
        color: cfg.fg,
        fontWeight: 600,
        fontFamily: "var(--font-mono)",
        textTransform: "uppercase",
        letterSpacing: "0.04em",
      }}
    >
      {severity}
    </span>
  );
}

function StatusChip({
  status,
}: {
  status: "active" | "shadow" | "disabled";
}) {
  const cfg = {
    active: { bg: "var(--status-done-bg)", fg: "var(--status-done-fg)" },
    shadow: {
      bg: "var(--status-info-bg)",
      fg: "var(--status-info-fg)",
    },
    disabled: { bg: "var(--neutral-100)", fg: "var(--text-muted)" },
  }[status];
  return (
    <span
      style={{
        fontSize: 10,
        padding: "1px 6px",
        borderRadius: "var(--r-2)",
        background: cfg.bg,
        color: cfg.fg,
        fontWeight: 600,
        fontFamily: "var(--font-mono)",
      }}
    >
      {status}
    </span>
  );
}

const cardStyle: React.CSSProperties = {
  background: "var(--surface-raised)",
  border: "1px solid var(--border-default)",
  borderRadius: "var(--r-4)",
  overflow: "hidden",
};

const tdStyle: React.CSSProperties = {
  padding: "10px 14px",
  borderBottom: "1px solid var(--border-subtle)",
  color: "var(--text-default)",
};
