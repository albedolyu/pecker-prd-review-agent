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

export const metadata = {
  title: "Pecker 使用说明",
};

// RoleKey → BirdId 映射(和 Phase4ReportV8 / Phase3ConfirmV8 同源)
const ROLE_TO_BIRD_ID: Record<RoleKey, BirdId> = {
  structure: 1, // 业务(责编)
  data_quality: 2, // 数据
  quality: 3, // 体验(审校)
  ai_coding: 4, // 风险(技编)
  "final-reviewer": 5, // 意见收口
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
    title: "开始前要准备什么",
    subtitle: "选择资料库、上传 PRD,确认这次评审的范围和深度",
    keys: ["editor-in-chief"],
  },
  {
    tag: "检查",
    title: "重点检查四件事",
    subtitle: "业务目标、字段口径、使用体验和实现风险会分开给出意见",
    keys: ["structure", "quality", "ai_coding", "data_quality"],
  },
  {
    tag: "收口",
    title: "把意见合并成可确认清单",
    subtitle: "合并重复意见、弱化证据不足的判断,补上明显遗漏的问题",
    keys: ["final-reviewer"],
  },
  {
    tag: "沉淀",
    title: "让下一次评审更准",
    subtitle: "把 PM 的接受、驳回、补充意见沉淀为后续规则和样例",
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
    label: "业务",
    title: "业务完整性",
    body: "目标、范围、验收标准是否说清",
    birdId: 1,
    tone: "reviewer",
  },
  {
    label: "数据",
    title: "字段口径",
    body: "数据源、字段映射、枚举和指标是否一致",
    birdId: 2,
    tone: "reviewer",
  },
  {
    label: "体验",
    title: "使用体验",
    body: "主流程、异常、空态、文案是否完整",
    birdId: 3,
    tone: "reviewer",
  },
  {
    label: "风险",
    title: "实现风险",
    body: "实现方案、边界条件、依赖和追溯是否清楚",
    birdId: 4,
    tone: "reviewer",
  },
];

const SUPPORT_TOPOLOGY: TopologyStep[] = [
  {
    title: "反馈回流",
    body: "PM 的接受、驳回和补充会用于减少后续误报",
    birdId: 7,
    tone: "support",
  },
  {
    title: "资料库维护",
    body: "持续清理过期资料和互相矛盾的定义",
    birdId: 9,
    tone: "support",
  },
  {
    title: "回归评测",
    body: "用固定样例检查优化后有没有退步",
    birdId: 8,
    tone: "support",
  },
  {
    title: "安全门禁",
    body: "上线前检查隐私、权限和不该外发的材料",
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
            使用说明
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
            PRD 评审工作台怎么用
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
            适合在 PRD 发给研发评审前使用。它会把目标范围、字段口径、异常边界和实现依赖拆开检查,最后收成一份可确认、可导出、可同步的修改清单。
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
              工具定位
            </div>
            <p
              style={{
                fontSize: 14,
                lineHeight: 1.75,
                color: "var(--text-default)",
                margin: 0,
              }}
            >
              Pecker 不是替 PM 写 PRD,而是帮 PM 在提交前做一次结构化检查。它会把“这份文档哪里还不够清楚”拆成可处理条目,让你知道哪些必须补、哪些可以解释、哪些可以暂时不改。
            </p>
            <p
              style={{
                fontSize: 14,
                lineHeight: 1.75,
                color: "var(--text-default)",
                margin: "12px 0 0",
              }}
            >
              你只需要完成三件事:上传 PRD,逐条确认意见,导出报告。接受、驳回和补充都会被记录下来,用于后续减少误报、补齐资料库,让团队反复使用时越来越贴近真实工作口径。
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
            tag="流程"
            title="一次评审从上传到报告"
            subtitle="先检查资料是否足够,再生成分方向意见,最后由 PM 确认并导出报告。"
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
              开始评审
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
      body: "上传 PRD,选择资料库和评审模式",
      icon: FileText,
      tone: "input",
    },
    {
      label: "准备",
      title: "资料预检",
      body: "检查背景资料是否足够,提前提示明显缺口",
      birdId: 6,
      tone: "input",
    },
  ];
  const finalSteps: TopologyStep[] = [
    {
      label: "收口",
      title: "意见合并",
      body: "合并重复意见,弱化证据不足的判断",
      birdId: 5,
      tone: "final",
    },
    {
      label: "检查",
      title: "结果完整性",
      body: "确认本次结果是否完整,避免拿残缺结论决策",
      icon: ShieldCheck,
      tone: "quality",
    },
    {
      label: "确认",
      title: "PM 确认",
      body: "逐条接受、驳回、改写或补充遗漏意见",
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
        title="四个方向并行检查"
        body="每个方向只看自己的责任范围,最后统一合并成一份清单。"
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
            不影响当次结论,但会让下一次评审更贴近团队口径。
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
