"use client";

/**
 * /runs/diff · v8 harness 增量 P1⑥
 *
 * Run 对比管理页 · 左右分栏 diff 两次 run。
 * 当前是 UI 壳 · 用 sample 数据演示。
 * 接 scripts/shadow_run.py 的产出在 Sprint 5(GET /api/runs/summary?id=...)。
 */

import Link from "next/link";
import {
  RunDiff,
  type RunSummary,
} from "@/components/run/RunDiff";

const BASELINE_RUN: RunSummary = {
  label: "原始评审 · 用户等级 PRD v0.3",
  subtitle: "评审编号 r_20260417_1425 · 常规模式",
  sessionClass: "productive",
  consistency: 0.88,
  totalTokens: 42300,
  costUsd: 0.187,
  durationSec: 62.4,
  items: [
    {
      id: "it-1",
      problem: "MAU 目标缺具体数字",
      birdId: 1,
      confidence: 0.9,
      severity: "should",
    },
    {
      id: "it-2",
      problem: "user_level 跨表口径不一致",
      birdId: 2,
      confidence: 0.85,
      severity: "must",
    },
    {
      id: "it-3",
      problem: "注册第 2 步文案歧义",
      birdId: 3,
      confidence: 0.62,
      severity: "suggest",
    },
    {
      id: "it-4",
      problem: "补偿逻辑未定义",
      birdId: 2,
      confidence: 0.58,
      severity: "should",
    },
    {
      id: "it-5",
      problem: "事件埋点命名不规范",
      birdId: 1,
      confidence: 0.7,
      severity: "suggest",
    },
  ],
};

const SHADOW_RUN: RunSummary = {
  label: "规则调整后 · 规则集 v2.1",
  subtitle: "评审编号 r_20260418_1042 · 常规模式",
  sessionClass: "productive",
  consistency: 0.92,
  totalTokens: 48900,
  costUsd: 0.21,
  durationSec: 58.1,
  items: [
    // 相同 problem,conf 变了
    {
      id: "s-1",
      problem: "MAU 目标缺具体数字",
      birdId: 1,
      confidence: 0.95,
      severity: "should",
    },
    {
      id: "s-2",
      problem: "user_level 跨表口径不一致",
      birdId: 2,
      confidence: 0.82,
      severity: "must",
    },
    // conf 变化大
    {
      id: "s-3",
      problem: "注册第 2 步文案歧义",
      birdId: 3,
      confidence: 0.88,
      severity: "should",
    },
    // 只在 shadow:苍鹰漏报补充
    {
      id: "s-6",
      problem: "下游 risk_service SLA 未声明",
      birdId: 4,
      confidence: 0.78,
      severity: "must",
    },
    // 事件埋点保持
    {
      id: "s-5",
      problem: "事件埋点命名不规范",
      birdId: 1,
      confidence: 0.72,
      severity: "suggest",
    },
  ],
  // 注意:it-4 补偿逻辑 只在 baseline,shadow 没出
};

export default function RunsDiffPage() {
  return (
    <div
      style={{
        maxWidth: 1120,
        margin: "0 auto",
        padding: "32px 24px 80px",
        fontFamily: "var(--font-sans)",
        background: "var(--surface-canvas)",
        minHeight: "100vh",
      }}
    >
      {/* header */}
      <header
        style={{
          marginBottom: 24,
          display: "flex",
          alignItems: "baseline",
          justifyContent: "space-between",
          gap: 16,
          flexWrap: "wrap",
        }}
      >
        <div>
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
            评审记录 · 结果对比
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
            两次评审对比
          </h1>
          <p
            style={{
              fontSize: 13,
              color: "var(--text-muted)",
              marginTop: 4,
              lineHeight: 1.55,
            }}
          >
            对比同一 PRD 在不同规则配置下的意见变化:新增、缺失和置信度变化
          </p>
        </div>
        <Link
          href="/review?v=8"
          style={{
            fontSize: 12,
            color: "var(--text-link)",
            textDecoration: "none",
            fontFamily: "var(--font-sans)",
          }}
        >
          ← 回评审主页
        </Link>
      </header>

      {/* WIP 提示 */}
      <div
        style={{
          marginBottom: 20,
          padding: "8px 14px",
          borderRadius: "var(--r-3)",
          border: "1px dashed var(--border-default)",
          background: "var(--status-warn-bg)",
          color: "var(--status-warn-fg)",
          fontSize: 12,
          fontFamily: "var(--font-sans)",
        }}
      >
        <strong style={{ fontWeight: 600 }}>演示数据</strong> ·{" "}
        <span style={{ color: "var(--text-default)" }}>
          当前展示样例评审结果,后续接入真实评审记录后可用于规则调整前后对比。
        </span>
      </div>

      <RunDiff left={BASELINE_RUN} right={SHADOW_RUN} />
    </div>
  );
}
