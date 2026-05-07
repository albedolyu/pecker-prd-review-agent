/**
 * /about · v8 · 10 鸟家族介绍(工作台气质)
 *
 * v7 是"编辑部名册"刊头 · drop cap · 美纹胶带 · tilt 错位卡
 * v8 切到极简工作文档气质:保留 10 鸟 + 起源核心叙事,去刊物装饰。
 */

import type { ReactNode } from "react";
import Link from "next/link";
import {
  CircleCheckBig,
  FileText,
  ShieldCheck,
  type LucideIcon,
} from "lucide-react";
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
  "final-reviewer": 5, // 苍鹰交叉校验
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
    tag: "准备",
    title: "入口与分工",
    subtitle: "评审前准备材料、安排评审方向,再把结果收拢成一份报告",
    keys: ["editor-in-chief"],
  },
  {
    tag: "并行评审",
    title: "四位评审员",
    subtitle: "业务、体验、风险、数据四个方向同时处理,每位只看自己的责任范围",
    keys: ["structure", "quality", "ai_coding", "data_quality"],
  },
  {
    tag: "交叉校验",
    title: "苍鹰复核",
    subtitle: "四位评审员完成后再登场,核对误报、冲突和明显遗漏",
    keys: ["final-reviewer"],
  },
  {
    tag: "持续维护",
    title: "反馈与知识库",
    subtitle: "把 PM 确认、质量回归、知识库更新和安全检查沉淀到下一次评审",
    keys: ["reader-feedback", "sample-reader", "archivist", "qa-gatekeeper"],
  },
];

interface TopologyStep {
  label?: string;
  title: string;
  body: string;
  birdId?: BirdId;
  icon?: LucideIcon;
  tone: "input" | "reviewer" | "final" | "quality" | "support";
}

interface TopologyToneStyle {
  background: string;
  border: string;
  dot: string;
  label: string;
}

const REVIEWER_TOPOLOGY: TopologyStep[] = [
  {
    label: "业务鸟",
    title: "业务完整性",
    body: "目标、范围、验收标准是否说清",
    birdId: 1,
    tone: "reviewer",
  },
  {
    label: "数据鸟",
    title: "字段口径",
    body: "数据源、字段映射、枚举和指标是否一致",
    birdId: 2,
    tone: "reviewer",
  },
  {
    label: "体验鸟",
    title: "使用体验",
    body: "主流程、异常、空态、文案是否完整",
    birdId: 3,
    tone: "reviewer",
  },
  {
    label: "风险鸟",
    title: "实现风险",
    body: "实现方案、边界条件、依赖和追溯是否清楚",
    birdId: 4,
    tone: "reviewer",
  },
];

const SUPPORT_TOPOLOGY: TopologyStep[] = [
  {
    title: "反馈回流",
    body: "PM 的确认、驳回和补充会影响后续规则权重",
    birdId: 7,
    tone: "support",
  },
  {
    title: "知识库维护",
    body: "持续清理断链、过期资料和互相打架的定义",
    birdId: 9,
    tone: "support",
  },
  {
    title: "回归评测",
    body: "用固定样例检查优化后有没有变差",
    birdId: 8,
    tone: "support",
  },
  {
    title: "安全门禁",
    body: "上线前检查密钥、隐私和不该外发的材料",
    birdId: 10,
    tone: "support",
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
            About · 评审团队
          </div>
          <h1
            style={{
              fontSize: 34,
              fontWeight: 600,
              color: "var(--text-strong)",
              margin: 0,
              letterSpacing: 0,
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
            一份 PRD,4 位评审员并行审稿,1 只苍鹰交叉校验,4 位长期维护反馈闭环和知识库。这里是 10 只鸟的职能分工和协作方式。
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
              这个产品叫&ldquo;啄木鸟&rdquo;,不是因为可爱,是因为啄木鸟做一件事做一辈子,而且每次敲下去都会听回声。一只鸟加无数次回声,比一百只鸟凭直觉乱啄要可靠得多。
            </p>
            <p
              style={{
                fontSize: 14,
                lineHeight: 1.75,
                color: "var(--text-default)",
                margin: "12px 0 0",
              }}
            >
              PRD 评审也一样:4 位评审员各管一维度并行审,苍鹰最后交叉校验,撤掉证据不足的、补上漏掉的。10 只鸟里有 5 只负责当次评审,5 只负责长期维护,构成一个完整的反馈闭环:每一次评审的下游信号都会回流到下一次评审的规则权重里。
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
            tag="协作流程"
            title="评审从提交到确认怎么流转"
            subtitle="先准备材料,再并行评审,最后复核与确认;长期维护能力放在侧边,不抢主流程。"
          />
          <TopologyDiagram />
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
            letterSpacing: 0,
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

function TopologyDiagram() {
  const entrySteps: TopologyStep[] = [
    {
      label: "入口",
      title: "提交 PRD",
      body: "接入 PRD、补充材料和当前工作区规则",
      icon: FileText,
      tone: "input",
    },
    {
      label: "准备",
      title: "评审准备",
      body: "加载资料库、做安全提醒、估算本次耗时",
      birdId: 6,
      tone: "input",
    },
  ];
  const finalSteps: TopologyStep[] = [
    {
      label: "复核",
      title: "苍鹰交叉校验",
      body: "检查误报、补漏和多位评审员之间的冲突",
      birdId: 5,
      tone: "final",
    },
    {
      label: "质检",
      title: "质量检查",
      body: "确认依据、运行健康和失败降级是否可靠",
      icon: ShieldCheck,
      tone: "quality",
    },
    {
      label: "确认",
      title: "PM 确认",
      body: "逐条确认、驳回或补充遗漏意见",
      icon: CircleCheckBig,
      tone: "quality",
    },
  ];

  return (
    <div
      aria-label="评审协作流程"
      style={{
        padding: "18px 20px",
        borderRadius: "var(--r-4)",
        border: "1px solid var(--border-default)",
        background: "var(--surface-raised)",
        display: "grid",
        gap: 16,
      }}
    >
      <FlowRow>
        <TopologyNode step={entrySteps[0]} />
        <FlowConnector label="进入准备" />
        <TopologyNode step={entrySteps[1]} />
      </FlowRow>

      <StageBand
        title="四位评审员并行处理"
        body="四个方向同时开始,彼此不互相改结论,最后统一交给苍鹰复核。"
      />

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(170px, 1fr))",
          gap: 10,
        }}
      >
        {REVIEWER_TOPOLOGY.map((step) => (
          <TopologyNode key={step.title} step={step} />
        ))}
      </div>

      <div
        aria-hidden
        style={{
          height: 18,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          color: "var(--text-faint)",
          fontSize: 18,
        }}
      >
        ↓
      </div>

      <FlowRow>
        <TopologyNode step={finalSteps[0]} />
        <FlowConnector label="进入检查" />
        <TopologyNode step={finalSteps[1]} />
        <FlowConnector label="交给 PM" />
        <TopologyNode step={finalSteps[2]} />
      </FlowRow>

      <div
        style={{
          paddingTop: 14,
          borderTop: "1px solid var(--border-subtle)",
          display: "grid",
          gap: 10,
        }}
      >
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            gap: 12,
            alignItems: "baseline",
            flexWrap: "wrap",
          }}
        >
          <div
            style={{
              fontSize: 13,
              fontWeight: 600,
              color: "var(--text-strong)",
            }}
          >
            长期维护能力
          </div>
          <div
            style={{
              fontSize: 12,
              color: "var(--text-muted)",
              lineHeight: 1.5,
            }}
          >
            不直接改变当次流程,但会让下一次评审更稳。
          </div>
        </div>
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
            gap: 8,
          }}
        >
          {SUPPORT_TOPOLOGY.map((step) => (
            <TopologyNode key={step.title} step={step} compact />
          ))}
        </div>
      </div>
    </div>
  );
}

function FlowRow({ children }: { children: ReactNode }) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "stretch",
        gap: 10,
        flexWrap: "wrap",
      }}
    >
      {children}
    </div>
  );
}

function FlowConnector({ label }: { label: string }) {
  return (
    <div
      aria-hidden
      style={{
        minWidth: 54,
        alignSelf: "center",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        gap: 2,
        color: "var(--text-faint)",
        fontSize: 11,
        lineHeight: 1.2,
      }}
    >
      <span style={{ fontSize: 18, color: "var(--accent-500)" }}>→</span>
      <span>{label}</span>
    </div>
  );
}

function StageBand({ title, body }: { title: string; body: string }) {
  return (
    <div
      style={{
        padding: "10px 14px",
        borderRadius: "var(--r-3)",
        background: "var(--accent-50)",
        border: "1px solid color-mix(in oklch, var(--accent-500) 24%, transparent)",
        display: "flex",
        justifyContent: "space-between",
        alignItems: "baseline",
        gap: 12,
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
        {title}
      </span>
      <span
        style={{
          fontSize: 12,
          color: "var(--text-muted)",
          lineHeight: 1.5,
        }}
      >
        {body}
      </span>
    </div>
  );
}

function TopologyNode({
  step,
  compact = false,
}: {
  step: TopologyStep;
  compact?: boolean;
}) {
  const tone = topologyToneStyle(step.tone);
  const Icon = step.icon;
  return (
    <article
      style={{
        flex: "1 1 180px",
        minWidth: 0,
        minHeight: compact ? 84 : 106,
        padding: compact ? "10px 12px" : "12px 14px",
        borderRadius: "var(--r-3)",
        border: `1px solid ${tone.border}`,
        background: tone.background,
        display: "flex",
        flexDirection: "column",
        gap: compact ? 7 : 9,
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 8,
          minWidth: 0,
        }}
      >
        {step.birdId ? (
          <BirdAvatar id={step.birdId} size="lg" />
        ) : Icon ? (
          <span
            aria-hidden
            style={{
              width: compact ? 18 : 24,
              height: compact ? 18 : 24,
              borderRadius: "50%",
              display: "inline-flex",
              alignItems: "center",
              justifyContent: "center",
              flexShrink: 0,
              background: "var(--surface-canvas)",
              border: `1px solid ${tone.border}`,
              color: tone.dot,
            }}
          >
            <Icon size={compact ? 12 : 15} strokeWidth={2} />
          </span>
        ) : null}
        <div style={{ minWidth: 0 }}>
          {step.label && (
            <div
              style={{
                fontSize: 10,
                color: tone.label,
                fontWeight: 600,
                lineHeight: 1.2,
              }}
            >
              {step.label}
            </div>
          )}
          <div
            style={{
              fontSize: compact ? 13 : 14,
              fontWeight: 600,
              color: "var(--text-strong)",
              lineHeight: 1.25,
            }}
          >
            {step.title}
          </div>
        </div>
      </div>
      <p
        style={{
          margin: 0,
          fontSize: compact ? 12 : 13,
          color: "var(--text-muted)",
          lineHeight: 1.55,
        }}
      >
        {step.body}
      </p>
    </article>
  );
}

function topologyToneStyle(tone: TopologyStep["tone"]): TopologyToneStyle {
  const sharedNeutral = {
    background: "var(--surface-canvas)",
    border: "var(--border-default)",
    dot: "var(--accent-500)",
    label: "var(--accent-600)",
  };
  const styles: Record<TopologyStep["tone"], TopologyToneStyle> = {
    input: sharedNeutral,
    reviewer: {
      background: "color-mix(in oklch, var(--surface-raised) 82%, var(--accent-50))",
      border: "var(--border-default)",
      dot: "var(--accent-500)",
      label: "var(--accent-600)",
    },
    final: {
      background: "color-mix(in oklch, var(--bird-5) 8%, var(--surface-raised))",
      border: "color-mix(in oklch, var(--bird-5) 28%, var(--border-default))",
      dot: "var(--bird-5)",
      label: "var(--bird-5)",
    },
    quality: {
      background: "color-mix(in oklch, var(--status-done-bg) 54%, var(--surface-raised))",
      border: "color-mix(in oklch, var(--status-done-dot) 22%, var(--border-default))",
      dot: "var(--status-done-dot)",
      label: "var(--status-done-fg)",
    },
    support: {
      background: "var(--surface-canvas)",
      border: "var(--border-subtle)",
      dot: "var(--text-muted)",
      label: "var(--text-muted)",
    },
  };
  return styles[tone];
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
        <BirdAvatar id={birdId} size="lg" />
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
