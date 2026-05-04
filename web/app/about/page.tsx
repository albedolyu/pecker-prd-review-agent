/**
 * /about · v8 · 10 鸟家族介绍(工作台气质)
 *
 * v7 是"编辑部名册"刊头 · drop cap · 美纹胶带 · tilt 错位卡
 * v8 切到极简工作文档气质:保留 10 鸟 + 起源核心叙事,去刊物装饰。
 */

import Link from "next/link";
import { ROLES, type RoleKey, type Role } from "@/lib/roles";
import { BirdAvatar, type BirdId } from "@/components/birds/BirdAvatar";
import { BirdBadge } from "@/components/birds/BirdBadge";

export const metadata = {
  title: "关于 Pecker · 10 只鸟",
};

// RoleKey → BirdId 映射(和 Phase4ReportV8 / Phase3ConfirmV8 同源)
const ROLE_TO_BIRD_ID: Record<RoleKey, BirdId> = {
  structure: 1, // 业务(责编)
  data_quality: 2, // 数据
  quality: 3, // 体验(审校)
  ai_coding: 4, // 风险(技编)
  "final-reviewer": 5, // 苍鹰 meta
  "editor-in-chief": 6,
  "reader-feedback": 7,
  "sample-reader": 8,
  archivist: 9,
  "qa-gatekeeper": 10,
};

interface RoleSection {
  tag: string;
  title: string;
  subtitle: string;
  keys: RoleKey[];
}

const SECTIONS: RoleSection[] = [
  {
    tag: "orchestrator",
    title: "主控层",
    subtitle: "编辑部主编,只负责分稿、催稿、收稿,自己不审",
    keys: ["editor-in-chief"],
  },
  {
    tag: "worker",
    title: "Worker 层 · 并行审稿",
    subtitle: "4 位评审员同时工作,每位只管自己那一维度,互不干扰",
    keys: ["structure", "quality", "ai_coding", "data_quality"],
  },
  {
    tag: "meta-reviewer",
    title: "Meta 层 · 交叉校验",
    subtitle: "4 位评审员跑完才登场,不重审,只做交叉校验和漏报补充",
    keys: ["final-reviewer"],
  },
  {
    tag: "background",
    title: "后台 · 看不见但一直在工作",
    subtitle: "反馈采集、评审质量回归、知识库维护、推送前安全检查",
    keys: ["reader-feedback", "sample-reader", "archivist", "qa-gatekeeper"],
  },
];

export default function AboutPage() {
  return (
    <main
      style={{
        fontFamily: "var(--font-sans)",
        background: "var(--surface-canvas)",
        minHeight: "calc(100vh - 60px)",
      }}
    >
      <div
        style={{
          maxWidth: 960,
          margin: "0 auto",
          padding: "40px 24px 80px",
        }}
      >
        {/* ── header ── */}
        <header style={{ marginBottom: 36 }}>
          <div
            style={{
              fontSize: 11,
              fontFamily: "var(--font-mono)",
              fontWeight: 600,
              color: "var(--accent-600)",
              textTransform: "uppercase",
              letterSpacing: "0.14em",
              marginBottom: 10,
            }}
          >
            About · Agent 家族
          </div>
          <h1
            style={{
              fontSize: 34,
              fontWeight: 600,
              color: "var(--text-strong)",
              margin: 0,
              letterSpacing: "-0.02em",
              lineHeight: 1.15,
            }}
          >
            啄木鸟编辑部 ·{" "}
            <span style={{ color: "var(--accent-500)" }}>10 只鸟</span>
          </h1>
          <p
            style={{
              fontSize: 14,
              color: "var(--text-muted)",
              marginTop: 8,
              maxWidth: 640,
              lineHeight: 1.6,
            }}
          >
            一份 PRD,4 位评审员并行审稿,1 只苍鹰交叉校验,4 位后台鸟常年维护反馈闭环和知识库。这里是 10 只鸟的职能分工和协作拓扑。
          </p>
        </header>

        {/* ── 起源 ── */}
        <section
          style={{
            display: "grid",
            gridTemplateColumns: "1fr",
            gap: 24,
            padding: "20px 24px",
            borderRadius: "var(--r-4)",
            border: "1px solid var(--border-default)",
            background: "var(--surface-raised)",
            marginBottom: 32,
          }}
        >
          <div>
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
              起源
            </div>
            <p
              style={{
                fontSize: 14,
                lineHeight: 1.75,
                color: "var(--text-default)",
                margin: 0,
              }}
            >
              这个产品叫&ldquo;啄木鸟&rdquo;,不是因为可爱——是因为啄木鸟做一件事做一辈子,而且每次敲下去都会听回声。一只鸟加无数次回声,比一百只鸟凭直觉乱啄要可靠得多。
            </p>
            <p
              style={{
                fontSize: 14,
                lineHeight: 1.75,
                color: "var(--text-default)",
                margin: "12px 0 0",
              }}
            >
              PRD 评审也一样:4 位评审员各管一维度并行审,苍鹰最后交叉校验,撤掉证据不足的、补上漏掉的。10 只鸟里有 5 只在台前(4 位评审员 + 1 只苍鹰),5 只在后台(反馈采集、质量回归、知识库维护、推送门禁、主控调度),构成一个完整的反馈闭环——每一次评审的下游信号都会回流到下一次评审的规则权重里。
            </p>
          </div>
        </section>

        {/* ── 4 层分组展示 ── */}
        {SECTIONS.map((section) => (
          <section key={section.tag} style={{ marginBottom: 32 }}>
            <SectionHead
              tag={section.tag}
              title={section.title}
              subtitle={section.subtitle}
            />
            <div
              style={{
                display: "grid",
                gridTemplateColumns:
                  section.keys.length === 1
                    ? "minmax(0, 1fr)"
                    : section.keys.length === 2
                      ? "repeat(2, minmax(0, 1fr))"
                      : "repeat(auto-fit, minmax(280px, 1fr))",
                gap: 10,
              }}
            >
              {section.keys.map((key) => (
                <RoleCardV8 key={key} role={ROLES[key]} />
              ))}
            </div>
          </section>
        ))}

        {/* ── 拓扑图 ── */}
        <section style={{ marginBottom: 32 }}>
          <SectionHead
            tag="topology"
            title="Agent 协作拓扑"
            subtitle="主编 → 4 评审员 → 苍鹰终审 · 评审员之间互不干扰"
          />
          <div
            style={{
              padding: "20px 24px",
              borderRadius: "var(--r-4)",
              border: "1px solid var(--border-default)",
              background: "var(--surface-raised)",
              fontFamily: "var(--font-mono)",
              fontSize: 12,
              lineHeight: 1.8,
              color: "var(--text-default)",
              whiteSpace: "pre",
              overflow: "auto",
            }}
          >
{`  ┌──────────────────────────────────────┐
  │      主编(调度层)                       │
  │      啄木鸟 · 分稿 / 催稿 / 收稿        │
  └──────────────────────────────────────┘
                  │
                  ↓
  ┌──────┬──────┬──────┬──────┐
  │ 业务 │ 数据 │ 体验 │ 风险 │  ← 4 位评审员(并行)
  │ 织布 │ 鸬鹚 │ 猫头 │ 渡鸦 │    互不干扰
  └──────┴──────┴──────┴──────┘
      │     │     │     │
      └──┬──┴──┬──┴──┬──┘
            ↓
  ┌──────────────────────────────────────┐
  │      苍鹰(终审)                         │
  │      交叉校验 · 漏报补充(最多 2-3 条)   │
  └──────────────────────────────────────┘
                  │
                  ↓
            PM 逐条确认
                  │
                  ↓
  ┌──────────────────────────────────────┐
  │      4 位后台鸟(常年运行)                │
  │ 信鸽(用户反馈 → 规则权重微调)          │
  │ 杜鹃(评审质量回归 · 上线前自检)        │
  │ 鸮鹦(知识库维护 · 找断链与过时)        │
  │ 伯劳(推送前安全检查 · 密钥与隐私)      │
  └──────────────────────────────────────┘`}
          </div>
        </section>

        {/* ── colophon ── */}
        <footer
          style={{
            paddingTop: 20,
            borderTop: "1px solid var(--border-subtle)",
            fontSize: 12,
            color: "var(--text-faint)",
            display: "flex",
            justifyContent: "space-between",
            flexWrap: "wrap",
            gap: 12,
          }}
        >
          <span>Pecker · 评审工作台 · 2026</span>
          <span style={{ display: "flex", gap: 14 }}>
            <Link
              href="/"
              style={{ color: "inherit", textDecoration: "none" }}
            >
              ← 首页
            </Link>
            <Link
              href="/review"
              style={{ color: "inherit", textDecoration: "none" }}
            >
              进入评审
            </Link>
            <Link
              href="/runs/diff"
              style={{ color: "inherit", textDecoration: "none" }}
            >
              运行对比
            </Link>
          </span>
        </footer>
      </div>
    </main>
  );
}

// ============================================================

function SectionHead({
  tag,
  title,
  subtitle,
}: {
  tag: string;
  title: string;
  subtitle: string;
}) {
  return (
    <div style={{ marginBottom: 14 }}>
      <div
        style={{
          display: "flex",
          alignItems: "baseline",
          gap: 10,
          marginBottom: 4,
        }}
      >
        <span
          style={{
            fontSize: 11,
            fontWeight: 600,
            color: "var(--accent-600)",
            padding: "2px 8px",
            borderRadius: "var(--r-pill)",
            background: "var(--accent-50)",
            letterSpacing: "0.04em",
          }}
        >
          {tag}
        </span>
        <h2
          style={{
            fontSize: 17,
            fontWeight: 600,
            color: "var(--text-strong)",
            margin: 0,
            letterSpacing: "-0.01em",
          }}
        >
          {title}
        </h2>
      </div>
      <p
        style={{
          fontSize: 12,
          color: "var(--text-muted)",
          margin: 0,
          lineHeight: 1.55,
        }}
      >
        {subtitle}
      </p>
    </div>
  );
}

function RoleCardV8({ role }: { role: Role }) {
  const birdId = ROLE_TO_BIRD_ID[role.key];
  return (
    <article
      style={{
        padding: "14px 16px",
        borderRadius: "var(--r-4)",
        border: "1px solid var(--border-default)",
        background: "var(--surface-raised)",
        display: "flex",
        flexDirection: "column",
        gap: 10,
      }}
    >
      <header style={{ display: "flex", alignItems: "center", gap: 10 }}>
        {/* id > 5 是未上线后台鸟,走 placeholder 灰圆;
           1-5 是上线鸟,走 hand-drawn lg PNG 头像 */}
        <BirdAvatar id={birdId} size="lg" placeholder={birdId > 5} />
        <div style={{ flex: 1, minWidth: 0 }}>
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 6,
              flexWrap: "wrap",
            }}
          >
            <span
              style={{
                fontSize: 14,
                fontWeight: 600,
                color: "var(--text-strong)",
              }}
            >
              {role.label}
            </span>
            <span
              style={{
                fontSize: 11,
                fontFamily: "var(--font-mono)",
                color: "var(--text-faint)",
                padding: "1px 5px",
                borderRadius: "var(--r-2)",
                background: "var(--surface-sunken)",
              }}
            >
              {role.birdName}
            </span>
          </div>
          <div
            style={{
              fontSize: 11,
              color: "var(--text-muted)",
              marginTop: 2,
            }}
          >
            {role.responsibility}
          </div>
        </div>
        {role.isWorker && <BirdBadge id={birdId} size="sm" />}
      </header>
      <p
        style={{
          fontSize: 13,
          lineHeight: 1.65,
          color: "var(--text-default)",
          margin: 0,
        }}
      >
        {role.description}
      </p>
    </article>
  );
}
