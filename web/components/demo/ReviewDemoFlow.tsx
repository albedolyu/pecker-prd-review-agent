"use client";

import { useMemo, useState } from "react";
import { ArrowLeft, ArrowRight, Download } from "lucide-react";

import {
  DEMO_DECISIONS,
  DEMO_PRECHECK,
  DEMO_PRD_CONTENT,
  DEMO_PRD_NAME,
  DEMO_REPORT_MARKDOWN,
  DEMO_REVIEW_RESULT,
  DEMO_WORKSPACE,
} from "@/lib/demo-review";
import { buildPmFriendlySnapshot } from "@/lib/pm-friendly";
import type { ReviewItem } from "@/lib/api";
import { normalizeDimensionKey } from "@/lib/roles";
import { PhaseNav, type PhaseId } from "@/components/nav/PhaseNav";
import { AgentStatusCard } from "@/components/run/AgentStatusCard";
import { RunConsole, type ConsoleLine } from "@/components/run/RunConsole";
import { RunHealthCheck } from "@/components/run/RunHealthCheck";
import { BirdLabel } from "@/components/birds/BirdAvatar";
import type { BirdId } from "@/components/birds/BirdAvatar";
import { ROLE_TO_BIRD_ID } from "@/lib/v8-run-helpers";

const DEMO_PHASES: PhaseId[] = [0, 1, 2, 1.5, 3, 4];

export function ReviewDemoFlow() {
  const [phase, setPhase] = useState<PhaseId>(0);
  const idx = DEMO_PHASES.indexOf(phase);
  const completed = DEMO_PHASES.slice(0, Math.max(0, idx));

  return (
    <div>
      <PhaseNav
        current={phase}
        completed={completed}
        failed={[]}
        onNavigate={(id) => setPhase(id)}
      />
      <DemoBanner phase={phase} onPrev={() => setPhase(DEMO_PHASES[Math.max(0, idx - 1)]!)} onNext={() => setPhase(DEMO_PHASES[Math.min(DEMO_PHASES.length - 1, idx + 1)]!)} />
      {phase === 0 && <DemoUpload />}
      {phase === 1 && <DemoPrecheck />}
      {phase === 2 && <DemoRunning />}
      {phase === 1.5 && <DemoHealth />}
      {phase === 3 && <DemoConfirm />}
      {phase === 4 && <DemoReport />}
    </div>
  );
}

function DemoBanner({
  phase,
  onPrev,
  onNext,
}: {
  phase: PhaseId;
  onPrev: () => void;
  onNext: () => void;
}) {
  const idx = DEMO_PHASES.indexOf(phase);
  return (
    <section
      style={{
        maxWidth: 1080,
        margin: "18px auto 0",
        padding: "0 24px",
        fontFamily: "var(--font-sans)",
      }}
    >
      <div
        style={{
          border: "1px solid color-mix(in oklch, var(--accent-500) 28%, var(--border-default))",
          background: "var(--accent-50)",
          borderRadius: "var(--r-4)",
          padding: "12px 14px",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 12,
          flexWrap: "wrap",
        }}
      >
        <div>
          <div
            style={{
              fontSize: 12,
              fontWeight: 700,
              color: "var(--accent-700)",
              marginBottom: 2,
            }}
          >
            演示模式
          </div>
          <div style={{ fontSize: 12, color: "var(--text-muted)" }}>
            使用内置样例查看完整 UI,不会上传 PRD、保存草稿或调用真实评审。
          </div>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <button
            type="button"
            onClick={onPrev}
            disabled={idx <= 0}
            style={buttonStyle(idx <= 0 ? "disabled" : "secondary")}
          >
            <ArrowLeft size={14} /> 上一步
          </button>
          <button
            type="button"
            onClick={onNext}
            disabled={idx >= DEMO_PHASES.length - 1}
            style={buttonStyle(idx >= DEMO_PHASES.length - 1 ? "disabled" : "primary")}
          >
            下一步 <ArrowRight size={14} />
          </button>
        </div>
      </div>
    </section>
  );
}

function DemoUpload() {
  return (
    <main style={pageStyle(780)}>
      <SectionHead
        title="新建一次 PRD 评审"
        desc="样例 PRD 已自动接入,你可以直接看后续每个阶段。"
      />
      <div style={fieldGridStyle}>
        <DemoField label="资料库" value={DEMO_WORKSPACE.replace(/^workspace-/, "")} hint="演示使用积分支付相关知识库" />
        <DemoField label="评审模式" value="深评审" hint="四个评审方向 + 苍鹰交叉校验" />
        <div style={cardStyle}>
          <div style={{ display: "flex", justifyContent: "space-between", gap: 12 }}>
            <div>
              <div style={eyebrowStyle}>PRD 正文</div>
              <h3 style={cardTitleStyle}>{DEMO_PRD_NAME}</h3>
            </div>
            <span style={pillStyle}>已读取 · {DEMO_PRD_CONTENT.length.toLocaleString()} 字</span>
          </div>
          <pre style={prdPreviewStyle}>{DEMO_PRD_CONTENT}</pre>
        </div>
      </div>
    </main>
  );
}

function DemoPrecheck() {
  return (
    <main style={pageStyle(980)}>
      <SectionHead
        title="盲区预检"
        desc="先看资料库覆盖情况,正式评审前就能知道哪些点需要补上下文。"
      />
      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 12 }}>
        <PrecheckColumn title="已覆盖" tone="done" items={DEMO_PRECHECK.strong} />
        <PrecheckColumn title="部分覆盖" tone="warn" items={DEMO_PRECHECK.weak} />
        <PrecheckColumn title="知识盲区" tone="fail" items={DEMO_PRECHECK.gaps} />
      </div>
      <div style={{ ...cardStyle, marginTop: 16 }}>
        <div style={eyebrowStyle}>补充说明</div>
        <p style={bodyTextStyle}>
          本次重点看支付失败返还、取消释放和金额字段口径,忽略营销活动配置。
        </p>
      </div>
    </main>
  );
}

function DemoRunning() {
  const lines: ConsoleLine[] = [
    { t: "0.0s", src: { name: "系统" }, level: "info", text: "PRD 已接入,正在加载知识库" },
    { t: "0.8s", src: { name: "调度" }, level: "accent", text: "四个评审方向开始并行检查(深评审)" },
    { t: "3.1s", src: { name: "结构", bird: 1 }, level: "ok", text: "已完成 · 提交 1 条意见 · 耗时 3.1 秒" },
    { t: "3.8s", src: { name: "数据质量", bird: 2 }, level: "ok", text: "已完成 · 提交 1 条意见 · 耗时 3.8 秒" },
    { t: "5.6s", src: { name: "苍鹰", bird: 5 }, level: "ok", text: "交叉校验完成" },
  ];

  return (
    <main style={pageStyle(1120)}>
      <SectionHead
        title="评审运行状态"
        desc="演示里直接展示完成态,真实评审会边跑边刷新。"
      />
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 14, marginBottom: 18 }}>
        {DEMO_REVIEW_RESULT.workers.map((worker) => (
          <AgentStatusCard
            key={worker.dimension}
            birdId={ROLE_TO_BIRD_ID[normalizeDimensionKey(worker.dimension)]}
            status="done"
            submissions={worker.items_count}
            elapsed="3.4s"
            variant="worker"
          />
        ))}
      </div>
      <RunConsole lines={lines} live={false} height={180} style={{ marginBottom: 18 }} />
    </main>
  );
}

function DemoHealth() {
  return (
    <main style={pageStyle(900)}>
      <SectionHead
        title="运行质量检查"
        desc="进入逐条确认前,先确认本次评审是否可信。"
      />
      <RunHealthCheck
        sessionClass="productive"
        consistency={0.92}
        failures={{}}
        birds={[
          { id: 1, runs: 1, fails: 0, submissions: 1 },
          { id: 2, runs: 1, fails: 0, submissions: 1 },
          { id: 3, runs: 1, fails: 0, submissions: 1 },
          { id: 4, runs: 1, fails: 0, submissions: 1 },
          { id: 5, runs: 1, fails: 0, submissions: 1 },
        ]}
        onContinue={() => {}}
        onRetry={() => {}}
      />
    </main>
  );
}

function DemoConfirm() {
  return (
    <main style={pageStyle(1200)}>
      <SectionHead
        title="逐条确认"
        desc="左边看 PRD 原文,右边处理评审意见;演示按钮不可提交。"
      />
      <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) 460px", gap: 16 }}>
        <div style={cardStyle}>
          <div style={eyebrowStyle}>PRD 原文</div>
          <pre style={{ ...prdPreviewStyle, maxHeight: 640 }}>{DEMO_PRD_CONTENT}</pre>
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          {DEMO_REVIEW_RESULT.items.map((item) => (
            <DemoItemCard key={item.id} item={item} />
          ))}
        </div>
      </div>
    </main>
  );
}

function DemoReport() {
  const snapshot = useMemo(
    () => buildPmFriendlySnapshot(DEMO_REVIEW_RESULT),
    [],
  );

  return (
    <main style={pageStyle(1080)}>
      <SectionHead
        title="评审报告"
        desc="这里展示 PM 摘要、织雀交接包和最终 markdown 出口。"
      />
      <div style={{ display: "grid", gridTemplateColumns: "1.1fr 0.9fr", gap: 16 }}>
        <div style={cardStyle}>
          <div style={eyebrowStyle}>PM 结论</div>
          <h3 style={cardTitleStyle}>{snapshot.pmSummary.verdict}</h3>
          <div style={metricGridStyle}>
            <Metric label="返工风险" value={snapshot.pmSummary.rework_risk} />
            <Metric label="阻塞项" value={snapshot.pmSummary.blocking_count} />
            <Metric label="意见总数" value={snapshot.pmSummary.total_items} />
            <Metric label="模式" value="深评审" />
          </div>
          <div style={{ marginTop: 14, display: "flex", flexDirection: "column", gap: 8 }}>
            {snapshot.pmSummary.priority_items.slice(0, 3).map((item) => (
              <div key={item.id} style={summaryItemStyle}>
                <strong>{item.location}</strong>
                <span>{item.issue}</span>
              </div>
            ))}
          </div>
        </div>
        <div style={cardStyle}>
          <div style={eyebrowStyle}>织雀测试用例交接</div>
          <div style={metricGridStyle}>
            <Metric
              label="可测性"
              value={testabilityVerdictLabel(snapshot.testabilitySummary.testability_verdict)}
            />
            <Metric label="覆盖度" value={snapshot.testabilitySummary.estimated_case_coverage} />
            <Metric label="阻塞缺口" value={snapshot.testabilitySummary.blocking_gap_count} />
            <Metric label="场景" value={snapshot.zhiquHandoff.scenario_matrix.length} />
          </div>
          <button type="button" disabled style={{ ...buttonStyle("secondary"), marginTop: 14 }}>
            <Download size={14} /> 下载交接包(演示)
          </button>
        </div>
      </div>
      <div style={{ ...cardStyle, marginTop: 16 }}>
        <div style={eyebrowStyle}>Markdown 预览</div>
        <pre style={prdPreviewStyle}>{DEMO_REPORT_MARKDOWN}</pre>
      </div>
    </main>
  );
}

function DemoItemCard({ item }: { item: ReviewItem }) {
  const role = normalizeDimensionKey(item.dimension);
  const birdId = ROLE_TO_BIRD_ID[role] as BirdId;
  const decision = DEMO_DECISIONS[item.id];
  const decisionLabel =
    decision?.action === "accept"
      ? "已接受"
      : decision?.action === "edit"
        ? "已改写"
        : decision?.action === "reject"
          ? "已拒绝"
          : "待处理";

  return (
    <article style={cardStyle}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
        <BirdLabel id={birdId} size="md" />
        <span style={severityStyle(item.severity)}>{severityLabel(item.severity)}</span>
        <span style={pillStyle}>{decisionLabel}</span>
      </div>
      <h3 style={{ ...cardTitleStyle, fontSize: 14 }}>{item.problem}</h3>
      {item.suggestion && (
        <p style={bodyTextStyle}>
          <strong>建议 </strong>
          {item.suggestion}
        </p>
      )}
      {item.evidence && (
        <blockquote style={quoteStyle}>依据: {item.evidence}</blockquote>
      )}
      <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
        <button type="button" disabled style={buttonStyle("disabled")}>接受</button>
        <button type="button" disabled style={buttonStyle("disabled")}>拒绝</button>
        <button type="button" disabled style={buttonStyle("disabled")}>编辑</button>
      </div>
    </article>
  );
}

function SectionHead({ title, desc }: { title: string; desc: string }) {
  return (
    <header style={{ marginBottom: 20 }}>
      <h1
        style={{
          fontSize: 22,
          fontWeight: 600,
          color: "var(--text-strong)",
          margin: 0,
          letterSpacing: "-0.015em",
        }}
      >
        {title}
      </h1>
      <p style={{ margin: "4px 0 0", fontSize: 13, color: "var(--text-muted)" }}>
        {desc}
      </p>
    </header>
  );
}

function DemoField({ label, value, hint }: { label: string; value: string; hint: string }) {
  return (
    <div style={cardStyle}>
      <div style={eyebrowStyle}>{label}</div>
      <div style={cardTitleStyle}>{value}</div>
      <div style={{ marginTop: 4, fontSize: 12, color: "var(--text-muted)" }}>{hint}</div>
    </div>
  );
}

function PrecheckColumn({
  title,
  tone,
  items,
}: {
  title: string;
  tone: "done" | "warn" | "fail";
  items: readonly string[];
}) {
  const color =
    tone === "done"
      ? "var(--status-done-fg)"
      : tone === "warn"
        ? "var(--status-warn-fg)"
        : "var(--status-failed-fg)";
  return (
    <section style={cardStyle}>
      <div style={{ ...eyebrowStyle, color }}>{title}</div>
      <div style={{ display: "flex", flexDirection: "column", gap: 8, marginTop: 10 }}>
        {items.map((item) => (
          <div key={item} style={listItemStyle}>
            {item}
          </div>
        ))}
      </div>
    </section>
  );
}

function Metric({ label, value }: { label: string; value: string | number }) {
  return (
    <span style={metricStyle}>
      <span style={{ fontSize: 10, color: "var(--text-faint)" }}>{label}</span>
      <strong style={{ fontSize: 18, color: "var(--text-strong)", fontVariantNumeric: "tabular-nums" }}>
        {value}
      </strong>
    </span>
  );
}

function pageStyle(maxWidth: number): React.CSSProperties {
  return {
    maxWidth,
    margin: "0 auto",
    padding: "28px 24px 80px",
    fontFamily: "var(--font-sans)",
  };
}

const fieldGridStyle: React.CSSProperties = {
  display: "grid",
  gridTemplateColumns: "1fr 1fr",
  gap: 12,
};

const cardStyle: React.CSSProperties = {
  border: "1px solid var(--border-default)",
  borderRadius: "var(--r-4)",
  background: "var(--surface-raised)",
  padding: "14px 16px",
};

const eyebrowStyle: React.CSSProperties = {
  fontSize: 11,
  fontWeight: 700,
  color: "var(--text-faint)",
  letterSpacing: "0.04em",
  marginBottom: 6,
};

const cardTitleStyle: React.CSSProperties = {
  margin: 0,
  fontSize: 16,
  fontWeight: 600,
  color: "var(--text-strong)",
  lineHeight: 1.45,
};

const pillStyle: React.CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  borderRadius: "var(--r-pill)",
  background: "var(--surface-sunken)",
  color: "var(--text-muted)",
  padding: "2px 8px",
  fontSize: 11,
  fontWeight: 600,
};

const bodyTextStyle: React.CSSProperties = {
  margin: "8px 0 0",
  fontSize: 13,
  lineHeight: 1.65,
  color: "var(--text-default)",
};

const prdPreviewStyle: React.CSSProperties = {
  margin: "12px 0 0",
  maxHeight: 360,
  overflow: "auto",
  whiteSpace: "pre-wrap",
  fontFamily: "var(--font-mono)",
  fontSize: 12,
  lineHeight: 1.65,
  color: "var(--text-default)",
  background: "var(--surface-sunken)",
  borderRadius: "var(--r-3)",
  padding: 12,
};

const listItemStyle: React.CSSProperties = {
  padding: "8px 10px",
  borderRadius: "var(--r-3)",
  background: "var(--surface-sunken)",
  fontSize: 12,
  color: "var(--text-default)",
  lineHeight: 1.55,
};

const quoteStyle: React.CSSProperties = {
  margin: "10px 0 0",
  padding: "8px 10px",
  borderLeft: "3px solid var(--accent-500)",
  background: "var(--surface-sunken)",
  color: "var(--text-muted)",
  fontSize: 12,
  lineHeight: 1.55,
};

const metricGridStyle: React.CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(4, minmax(0, 1fr))",
  gap: 8,
  marginTop: 12,
};

const metricStyle: React.CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: 2,
  padding: "9px 10px",
  border: "1px solid var(--border-subtle)",
  borderRadius: "var(--r-3)",
  background: "var(--surface-sunken)",
};

const summaryItemStyle: React.CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: 2,
  padding: "9px 10px",
  borderRadius: "var(--r-3)",
  background: "var(--surface-sunken)",
  fontSize: 12,
  lineHeight: 1.5,
  color: "var(--text-default)",
};

function buttonStyle(kind: "primary" | "secondary" | "disabled"): React.CSSProperties {
  const disabled = kind === "disabled";
  return {
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "center",
    gap: 6,
    height: 32,
    padding: "0 12px",
    borderRadius: "var(--r-3)",
    border: kind === "primary" ? 0 : "1px solid var(--border-default)",
    background:
      kind === "primary"
        ? "var(--accent-500)"
        : disabled
          ? "var(--neutral-100)"
          : "var(--surface-raised)",
    color:
      kind === "primary"
        ? "var(--accent-fg)"
        : disabled
          ? "var(--text-faint)"
          : "var(--text-default)",
    fontSize: 12,
    fontWeight: 600,
    cursor: disabled ? "not-allowed" : "pointer",
    fontFamily: "var(--font-sans)",
  };
}

function severityStyle(severity?: string): React.CSSProperties {
  const must = severity === "must";
  return {
    borderRadius: "var(--r-2)",
    background: must ? "var(--status-failed-bg)" : "var(--status-warn-bg)",
    color: must ? "var(--status-failed-fg)" : "var(--status-warn-fg)",
    padding: "2px 7px",
    fontSize: 11,
    fontWeight: 700,
  };
}

function severityLabel(severity?: string): string {
  if (severity === "must") return "必须修";
  if (severity === "should") return "建议修";
  return "参考";
}

function testabilityVerdictLabel(verdict: string): string {
  if (verdict === "blocked") return "需补充";
  if (verdict === "partial") return "部分可生成";
  if (verdict === "ready") return "可直接生成";
  return verdict;
}
