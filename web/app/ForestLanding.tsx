"use client";

/**
 * ForestLanding · v8 · 登录前首页(工作台气质)
 *
 * v7 是"赛博童话森林"Canvas 数字雨 + 大啄木鸟 · v8 切到极简 landing:
 * - 顶部 brand + 登录 / 进入入口
 * - 中部一句话产品介绍 + 10 鸟头像横向展示
 * - 底部:关于 / 快速开始 / 登录 三档 CTA
 *
 * 不依赖后端(/api/me 不在这里调),可作为未登录第一眼。
 */

import Link from "next/link";
import { useRouter } from "next/navigation";
import { BirdAvatar, type BirdId } from "@/components/birds/BirdAvatar";
import { BIRD_META } from "@/components/birds/BirdBadge";

const ALL_BIRDS: BirdId[] = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10];

export function ForestLanding() {
  const router = useRouter();

  return (
    <main
      style={{
        minHeight: "calc(100vh - 60px)",
        display: "flex",
        flexDirection: "column",
        fontFamily: "var(--font-sans)",
        background: "var(--surface-canvas)",
      }}
    >
      {/* ── 主体 ── */}
      <section
        style={{
          flex: 1,
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          padding: "60px 24px 40px",
          textAlign: "center",
        }}
      >
        {/* eyebrow */}
        <div
          style={{
            fontSize: 11,
            fontFamily: "var(--font-mono)",
            fontWeight: 600,
            color: "var(--accent-600)",
            textTransform: "uppercase",
            letterSpacing: "0.14em",
            marginBottom: 14,
          }}
        >
          PRD Review · Agent Workbench · v8
        </div>

        {/* title */}
        <h1
          style={{
            fontSize: 40,
            fontWeight: 600,
            color: "var(--text-strong)",
            margin: 0,
            letterSpacing: "-0.03em",
            lineHeight: 1.1,
            maxWidth: 680,
          }}
        >
          10 只鸟 · 帮 PM 把{" "}
          <span style={{ color: "var(--accent-500)" }}>PRD</span> 评到能落地
        </h1>

        {/* subtitle */}
        <p
          style={{
            fontSize: 15,
            color: "var(--text-muted)",
            marginTop: 14,
            maxWidth: 560,
            lineHeight: 1.6,
          }}
        >
          四位评审鸟并行审稿,苍鹰复核漏报与误判 — 10 分钟出一份可追溯的 PRD 评审报告,每条意见都有来源、有依据、可签收。
        </p>

        {/* 10 只鸟展示 */}
        <div
          style={{
            display: "flex",
            gap: 10,
            marginTop: 40,
            padding: "16px 20px",
            borderRadius: "var(--r-4)",
            border: "1px solid var(--border-default)",
            background: "var(--surface-raised)",
          }}
        >
          {ALL_BIRDS.map((id) => (
            <BirdAvatar
              key={id}
              id={id}
              size="lg"
              placeholder={id > 5}
            />
          ))}
        </div>

        {/* 角色一句话 */}
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(5, 1fr)",
            gap: 8,
            marginTop: 12,
            maxWidth: 680,
            fontSize: 11,
            fontFamily: "var(--font-mono)",
            color: "var(--text-faint)",
            textTransform: "uppercase",
            letterSpacing: "0.06em",
          }}
        >
          {[1, 2, 3, 4, 5].map((id) => (
            <div key={id} style={{ textAlign: "center" }}>
              {BIRD_META[id as BirdId].label}
            </div>
          ))}
        </div>

        {/* CTA */}
        <div
          style={{
            display: "flex",
            gap: 10,
            marginTop: 40,
            flexWrap: "wrap",
            justifyContent: "center",
          }}
        >
          <button
            type="button"
            onClick={() => router.push("/review")}
            style={btnPrimary}
          >
            进入评审 →
          </button>
          <Link href="/login" style={btnSecondary}>
            登录
          </Link>
          <Link href="/about" style={btnGhost}>
            关于 Pecker
          </Link>
        </div>

        {/* feature row */}
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(3, minmax(200px, 1fr))",
            gap: 16,
            marginTop: 56,
            maxWidth: 880,
            width: "100%",
          }}
        >
          <Feature
            tag="评审运行"
            title="评审运行状态可视化"
            desc="实时看到每个评审员审到哪了,谁返回了多少条意见,哪只鸟出了状况一目了然"
          />
          <Feature
            tag="质量检查"
            title="不让你在残缺结果上决策"
            desc="评审跑完先看运行健康度,有评审员未完整返回时强制提示重跑,避免遗漏问题"
          />
          <Feature
            tag="逐条确认"
            title="左对照原文,右逐条决策"
            desc="按维度和严重度筛选,接受 / 驳回 / 改写一键完成,低置信意见自动弱化"
          />
        </div>
      </section>

      {/* footer */}
      <footer
        style={{
          padding: "20px 24px",
          borderTop: "1px solid var(--border-subtle)",
          fontSize: 11,
          color: "var(--text-faint)",
          fontFamily: "var(--font-mono)",
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          gap: 12,
          flexWrap: "wrap",
        }}
      >
        <span>Pecker · PRD 评审工作台 · 2026</span>
        <span style={{ display: "flex", gap: 12 }}>
          <Link
            href="/runs/diff"
            title="运行对比 · 内部"
            style={{ color: "inherit", textDecoration: "none" }}
          >
            运行对比
          </Link>
          <Link
            href="/v8-preview"
            title="组件预览 · 内部"
            style={{ color: "inherit", textDecoration: "none" }}
          >
            组件预览
          </Link>
          <Link
            href="/review?v=7"
            title="老版回退入口"
            style={{ color: "inherit", textDecoration: "none" }}
          >
            老版回退
          </Link>
        </span>
      </footer>
    </main>
  );
}

// ============================================================

function Feature({
  tag,
  title,
  desc,
}: {
  tag: string;
  title: string;
  desc: string;
}) {
  return (
    <div
      style={{
        padding: "14px 16px",
        borderRadius: "var(--r-4)",
        border: "1px solid var(--border-default)",
        background: "var(--surface-raised)",
        textAlign: "left",
      }}
    >
      <div
        style={{
          fontSize: 10,
          fontFamily: "var(--font-mono)",
          fontWeight: 600,
          color: "var(--accent-600)",
          textTransform: "uppercase",
          letterSpacing: "0.08em",
          marginBottom: 6,
        }}
      >
        {tag}
      </div>
      <div
        style={{
          fontSize: 14,
          fontWeight: 600,
          color: "var(--text-strong)",
          marginBottom: 4,
        }}
      >
        {title}
      </div>
      <div
        style={{
          fontSize: 12,
          color: "var(--text-muted)",
          lineHeight: 1.55,
        }}
      >
        {desc}
      </div>
    </div>
  );
}

// ============================================================
// styles

const btnPrimary: React.CSSProperties = {
  height: 38,
  padding: "0 18px",
  border: 0,
  borderRadius: "var(--r-3)",
  background: "var(--accent-500)",
  color: "var(--accent-fg)",
  fontSize: 14,
  fontWeight: 600,
  cursor: "pointer",
  fontFamily: "var(--font-sans)",
};

const btnSecondary: React.CSSProperties = {
  height: 38,
  padding: "0 16px",
  border: "1px solid var(--border-default)",
  borderRadius: "var(--r-3)",
  background: "var(--surface-raised)",
  color: "var(--text-default)",
  fontSize: 14,
  fontWeight: 500,
  cursor: "pointer",
  fontFamily: "var(--font-sans)",
  textDecoration: "none",
  display: "inline-flex",
  alignItems: "center",
};

const btnGhost: React.CSSProperties = {
  height: 38,
  padding: "0 14px",
  border: 0,
  borderRadius: "var(--r-3)",
  background: "transparent",
  color: "var(--text-muted)",
  fontSize: 14,
  fontWeight: 500,
  cursor: "pointer",
  fontFamily: "var(--font-sans)",
  textDecoration: "none",
  display: "inline-flex",
  alignItems: "center",
};
