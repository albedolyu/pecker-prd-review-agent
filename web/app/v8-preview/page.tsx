/**
 * v8-preview · Sprint 1 + 2A 组件预览页
 *
 * 临时页,用来人工验证 v8 基础组件 + 文档气质主线组件。
 * Sprint 4 完成后可以删掉或改成完整 gallery。
 *
 * 打开:http://localhost:3000/v8-preview
 */

"use client";

import { useState } from "react";
import {
  BirdAvatar,
  type BirdId,
  type BirdStatus,
} from "@/components/birds/BirdAvatar";
import { BirdBadge, BIRD_META } from "@/components/birds/BirdBadge";
import { PhaseNav, type PhaseId } from "@/components/nav/PhaseNav";
import { ShortcutHint, KeymapBar } from "@/components/misc/ShortcutHint";
import { EvidenceBlock } from "@/components/review/EvidenceBlock";
import { CommentThread } from "@/components/review/CommentThread";
import {
  DocumentView,
  type DocBlock,
} from "@/components/doc/DocumentView";
import { AgentStatusCard } from "@/components/run/AgentStatusCard";
import { RunConsole } from "@/components/run/RunConsole";
import { RunHealthCheck } from "@/components/run/RunHealthCheck";
import { MissingReportButton } from "@/components/review/MissingReportButton";
import Link from "next/link";

const ALL_BIRDS: BirdId[] = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10];
const STATUSES: BirdStatus[] = ["queued", "running", "done", "failed", "warn"];

export default function V8PreviewPage() {
  const [current, setCurrent] = useState<PhaseId>(2);
  const completed: PhaseId[] =
    current === 0
      ? []
      : ([0, 1, 1.5] as PhaseId[]).filter((p) => p < current);

  // Phase 3 组合场景的锚点联动 state
  const [selectedAnchor, setSelectedAnchor] = useState<string | undefined>();
  const [commentStates, setCommentStates] = useState<
    Record<string, boolean | undefined>
  >({});
  const setAccepted = (id: string, v: boolean | undefined) =>
    setCommentStates((s) => ({ ...s, [id]: v }));

  return (
    <div style={{ minHeight: "100vh", background: "var(--surface-canvas)" }}>
      <PhaseNav
        current={current}
        completed={completed}
        failed={[]}
        onNavigate={(id) => setCurrent(id)}
      />

      <div
        style={{ maxWidth: 1200, margin: "0 auto", padding: "40px 32px 80px" }}
      >
        <header style={{ marginBottom: 40 }}>
          <h1
            style={{
              fontSize: 28,
              fontWeight: 600,
              color: "var(--text-strong)",
              margin: 0,
              letterSpacing: "-0.02em",
            }}
          >
            v8 · Sprint 1 + 2A 组件预览
          </h1>
          <p
            style={{
              fontSize: 13,
              color: "var(--text-muted)",
              marginTop: 6,
            }}
          >
            基础组件(BirdAvatar / BirdBadge / PhaseNav)+ 文档气质主线(DocumentView / CommentThread / EvidenceBlock / ShortcutHint)
          </p>
        </header>

        {/* ═══════════ Sprint 4 · harness 增量 ═══════════ */}

        <BigDivider label="Sprint 4 · harness 增量" />

        <Section title="MissingReportButton · 漏报反馈入口(P1⑦)">
          <p style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 0 }}>
            点按钮弹 modal · PM 填问题 + 位置 + 归哪只鸟 → 系统反查并进归因库
          </p>
          <div
            style={{
              padding: 18,
              borderRadius: "var(--r-4)",
              border: "1px solid var(--border-default)",
              background: "var(--surface-raised)",
              display: "flex",
              gap: 12,
              flexWrap: "wrap",
            }}
          >
            <MissingReportButton
              onSubmit={(payload) => {
                console.log("[preview · missing-report]", payload);
              }}
            />
            <span
              style={{
                fontSize: 11,
                color: "var(--text-faint)",
                fontFamily: "var(--font-mono)",
                alignSelf: "center",
              }}
            >
              submit → console.log(payload)
            </span>
          </div>
        </Section>

        <Section title="RunDiff 入口 · /runs/diff">
          <p style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 0 }}>
            独立管理页 · baseline 和 shadow 对比(当前用 sample 数据演示)
          </p>
          <Link
            href="/runs/diff"
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 6,
              padding: "8px 14px",
              borderRadius: "var(--r-3)",
              border: "1px solid var(--accent-500)",
              background: "var(--accent-50)",
              color: "var(--accent-700)",
              fontSize: 13,
              fontWeight: 600,
              textDecoration: "none",
              fontFamily: "var(--font-sans)",
            }}
          >
            打开 /runs/diff →
          </Link>
        </Section>

        {/* ═══════════ Sprint 3 · Agent 调度中心 ═══════════ */}

        <BigDivider label="Sprint 3 · Phase 2 调度中心" />

        <Section title="AgentStatusCard · 四态矩阵(worker + meta)">
          <p style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 0 }}>
            4 worker(上层)+ 1 苍鹰(meta 层)· 状态灯 + 进度条 + mono 元数据 + 失败 recovery。
          </p>
          <div
            data-phase2
            style={{
              padding: 24,
              borderRadius: "var(--r-4)",
              border: "1px solid var(--border-default)",
              background: "var(--surface-canvas)",
            }}
          >
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "repeat(4, 1fr)",
                gap: 12,
                marginBottom: 48,
              }}
            >
              <AgentStatusCard
                birdId={1}
                status="done"
                submissions={18}
                tokens="2.1k"
                elapsed="12.3s"
                model="sonnet-4-6"
              />
              <AgentStatusCard
                birdId={2}
                status="running"
                progress={62}
                submissions={8}
                tokens="1.4k"
                elapsed="14.8s"
                model="sonnet-4-6"
              />
              <AgentStatusCard
                birdId={3}
                status="queued"
                model="sonnet-4-6"
              />
              <AgentStatusCard
                birdId={4}
                status="failed"
                tokens="0.3k"
                elapsed="3.2s"
                failReason="empty_submission"
                model="opus-4"
                onRetry={() => {}}
              />
            </div>
            <div style={{ maxWidth: 680, margin: "0 auto" }}>
              <AgentStatusCard
                birdId={5}
                status="running"
                variant="meta"
                progress={40}
                note="漏报补充 2/5"
                model="opus-4"
                tokens="5.8k"
                elapsed="32.7s"
              />
            </div>
          </div>
        </Section>

        <Section title="RunConsole · 深色流式日志">
          <RunConsole
            live={true}
            height={240}
            lines={[
              { t: "0.0s", src: { name: "system" }, level: "info", text: "PRD 上传完成 · 开始扫 wiki" },
              { t: "1.2s", src: { name: "system" }, level: "info", text: "wiki 扫描完成 · 42 页" },
              { t: "1.4s", src: { name: "orchestrator" }, level: "accent", text: "4 worker 并行启动 · mode=standard" },
              { t: "8.3s", src: { name: "业务鸟", bird: 1 }, level: "ok", text: "done · items=18 · 7.1s · $0.0042" },
              { t: "9.7s", src: { name: "数据鸟", bird: 2 }, level: "ok", text: "done · items=12 · 8.5s · $0.0038" },
              { t: "12.1s", src: { name: "体验鸟", bird: 3 }, level: "warn", text: "超时降级 · items=0 · 15.0s" },
              { t: "13.8s", src: { name: "风险鸟", bird: 4 }, level: "error", text: "empty_submission · 走空兜底" },
              { t: "14.0s", src: { name: "苍鹰", bird: 5 }, level: "accent", text: "开始交叉校验 4 worker 产出" },
              { t: "24.2s", src: { name: "苍鹰", bird: 5 }, level: "ok", text: "交叉校验完成 · 漏报补充 2 条" },
            ]}
          />
        </Section>

        <Section title="RunHealthCheck · Phase 1.5 必经节点(partial_silent 告警)">
          <RunHealthCheck
            sessionClass="partial_silent"
            consistency={0.62}
            failures={{
              empty_submission: 1,
              timeout: 1,
              quota_exhausted: 0,
              tool_call_failed: 0,
              json_parse_error: 0,
            }}
            birds={[
              { id: 1, runs: 1, fails: 0, submissions: 18 },
              { id: 2, runs: 1, fails: 0, submissions: 12 },
              { id: 3, runs: 1, fails: 1, submissions: 0 },
              { id: 4, runs: 1, fails: 1, submissions: 0 },
              { id: 5, runs: 1, fails: 0, submissions: 0 },
            ]}
            onContinue={() => {}}
            onRetry={() => {}}
          />
        </Section>

        <Section title="RunHealthCheck · productive(正常态)">
          <RunHealthCheck
            sessionClass="productive"
            consistency={0.95}
            failures={{}}
            birds={[
              { id: 1, runs: 1, fails: 0, submissions: 18 },
              { id: 2, runs: 1, fails: 0, submissions: 12 },
              { id: 3, runs: 1, fails: 0, submissions: 8 },
              { id: 4, runs: 1, fails: 0, submissions: 6 },
              { id: 5, runs: 1, fails: 0, submissions: 2 },
            ]}
            onContinue={() => {}}
            onRetry={() => {}}
          />
        </Section>

        {/* ═══════════ Sprint 2A · 文档气质主线 ═══════════ */}

        <BigDivider label="Sprint 2A · 文档气质主线" />

        <Section title="Phase 3 组合场景 · 左原文 + 右评论 + 锚点联动">
          <p style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 0 }}>
            点左侧原文高亮 → 右侧对应评论强化(accent 边)· 点评论头部鸟名 → 左侧原文滚到对应锚点。
            覆盖所有 harness 视觉规则:苍鹰三态徽章 / 依据验证 3 态 / 低置信折叠 / 验证失败折叠。
          </p>
          <Phase3Scene
            selectedAnchor={selectedAnchor}
            onSelectAnchor={setSelectedAnchor}
            commentStates={commentStates}
            setAccepted={setAccepted}
          />
        </Section>

        <Section title="DocumentView · 独立 Phase 1 汇总条 + 高亮">
          <div style={{ height: 380 }}>
            <DocumentView
              title="用户等级体系改造 PRD"
              subtitle="workspace/对外投资 · v0.3 · 42 blocks · 2026-04-18"
              summary={{ strong: 18, weak: 6, gaps: 3 }}
              blocks={SAMPLE_BLOCKS}
              style={{ height: "100%" }}
            />
          </div>
        </Section>

        <Section title="CommentThread · 全状态矩阵">
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "1fr 1fr",
              gap: 12,
            }}
          >
            <CommentThread
              birdId={1}
              eagleMark="passed"
              dimension="业务目标"
              title="MAU 目标缺具体数字"
              body="业务目标段只说了'提升活跃',没给 30d MAU 的 OKR 对齐目标值。"
              evidence={{
                quote: "本次改造目标是提升用户等级体系对活跃度的提升效果。",
                source: "§1.1 · line 4",
                verification: "verified",
              }}
              meta={{ model: "sonnet-4-6", conf: 0.92, tokens: "2.1k", rule: "R042" }}
            />
            <CommentThread
              birdId={2}
              eagleMark="passed"
              dimension="字段口径"
              title="user_level 跨表口径不一致"
              body="dim_user.user_level 和 dwd_user.user_level 的计算口径不同(前者 T+1,后者实时),需在 PRD 里明确下游取哪个。"
              evidence={{
                quote: "使用 user_level 字段判断用户当前等级。",
                source: "§2.3 · line 18",
                verification: "verified",
              }}
              meta={{ model: "sonnet-4-6", conf: 0.85, tokens: "1.8k", rule: "R203" }}
            />
            <CommentThread
              birdId={4}
              eagleMark="added"
              dimension="风险 / 依赖"
              title="(苍鹰补充)下游 risk_service SLA 未声明"
              body="4 只 worker 都没提,苍鹰在交叉校验时补上。PRD 依赖 risk_service 做等级评估,但没给 P99 / 降级策略。"
              meta={{ model: "opus-4", conf: 0.78, tokens: "3.4k", rule: "R109" }}
            />
            <CommentThread
              birdId={3}
              eagleMark="revoked"
              dimension="UX 流程"
              title="注册第 2 步文案歧义"
              body="体验鸟原说有歧义,但苍鹰核对后认为该文案是 i18n 限制,不属于 PM 可改项。"
              evidence={{
                quote: "请填写您的用户等级偏好。",
                source: "§3.2 · line 27",
                verification: "failed",
              }}
              meta={{ model: "sonnet-4-6", conf: 0.62, tokens: "1.2k", rule: "R087" }}
            />
            <CommentThread
              birdId={2}
              eagleMark="passed"
              dimension="数据"
              title="补偿逻辑未定义"
              body="升级失败时是否补偿用户,PRD 没说。"
              meta={{ model: "haiku-4-5", conf: 0.58, tokens: "0.9k", rule: "R211" }}
            />
            <CommentThread
              birdId={1}
              eagleMark="passed"
              dimension="业务"
              title="已接受示例"
              body="这一条演示 accepted=true 的视觉效果。"
              meta={{ model: "sonnet-4-6", conf: 0.88, tokens: "1.5k" }}
              accepted={true}
            />
          </div>
        </Section>

        <Section title="EvidenceBlock · 3 态验证徽章">
          <div style={{ display: "flex", flexDirection: "column", gap: 12, maxWidth: 600 }}>
            <EvidenceBlock
              quote="本次改造目标是提升用户等级体系对活跃度的提升效果。"
              source="§1.1 · line 4"
              verification="verified"
            />
            <EvidenceBlock
              quote="请填写您的用户等级偏好。"
              source="§3.2 · line 27"
              verification="failed"
            />
            <EvidenceBlock
              quote="使用 user_level 字段判断用户当前等级。"
              source="§2.3 · line 18"
              verification="unverified"
            />
          </div>
        </Section>

        <Section title="ShortcutHint · 键盘提示 + KeymapBar">
          <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
            <div>
              <div style={labelStyle}>inline 变体(浅底 · 默认)</div>
              <div style={{ display: "flex", gap: 16 }}>
                <ShortcutHint keys={["j"]} label="下一条" />
                <ShortcutHint keys={["k"]} label="上一条" />
                <ShortcutHint keys={["y"]} label="接受" />
                <ShortcutHint keys={["n"]} label="拒绝" />
                <ShortcutHint keys={["cmd", "enter"]} label="批量接受" />
              </div>
            </div>
            <div>
              <div style={labelStyle}>dark 变体(暗底 · Phase 2 console 用)</div>
              <div
                style={{
                  display: "flex",
                  gap: 16,
                  padding: 12,
                  background: "var(--surface-console)",
                  borderRadius: "var(--r-4)",
                }}
              >
                <ShortcutHint keys={["r"]} label="重试" variant="dark" />
                <ShortcutHint keys={["c"]} label="清日志" variant="dark" />
                <ShortcutHint keys={["esc"]} label="退出" variant="dark" />
              </div>
            </div>
            <div>
              <div style={labelStyle}>KeymapBar · Phase 3 底部常驻条</div>
              <KeymapBar
                items={[
                  { keys: ["j"], label: "下一条" },
                  { keys: ["k"], label: "上一条" },
                  { keys: ["y"], label: "接受" },
                  { keys: ["n"], label: "拒绝" },
                  { keys: ["e"], label: "编辑" },
                  { keys: ["/"], label: "搜索" },
                ]}
              />
            </div>
          </div>
        </Section>

        {/* ═══════════ Sprint 1 · 基础层 ═══════════ */}

        <BigDivider label="Sprint 1 · 基础层" />

        <Section title="PhaseNav · 交互">
          <p style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 0 }}>
            点顶部节点切换(当前 <strong>{current}</strong>)· 已完成可回跳 · 1.5 带警示三角。
          </p>
          <div style={{ display: "flex", gap: 8, marginTop: 12, flexWrap: "wrap" }}>
            {([0, 1, 1.5, 2, 3, 4] as PhaseId[]).map((p) => (
              <button
                key={p}
                onClick={() => setCurrent(p)}
                style={{
                  padding: "6px 12px",
                  fontSize: 12,
                  fontFamily: "var(--font-mono)",
                  borderRadius: "var(--r-3)",
                  border: "1px solid var(--border-default)",
                  background:
                    current === p ? "var(--accent-50)" : "var(--surface-raised)",
                  color:
                    current === p ? "var(--accent-600)" : "var(--text-default)",
                  cursor: "pointer",
                }}
              >
                → {String(p).replace(".", "·")}
              </button>
            ))}
          </div>
        </Section>

        <Section title="BirdAvatar · 10 只 × 3 尺寸">
          <BirdAvatarGrid />
        </Section>

        <Section title="BirdAvatar · 5 种状态灯">
          <StatusGrid />
        </Section>

        <Section title="BirdAvatar · placeholder(id 6-10)">
          <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
            {[6, 7, 8, 9, 10].map((id) => (
              <BirdAvatar key={id} id={id as BirdId} size="lg" placeholder />
            ))}
          </div>
        </Section>

        <Section title="BirdBadge · 2 尺寸">
          <BirdBadgeGrid />
        </Section>

        <Section title="data-phase2 局部 overlay">
          <div
            data-phase2
            style={{
              background: "var(--surface-canvas)",
              padding: 24,
              borderRadius: "var(--r-4)",
              border: "1px solid var(--border-default)",
            }}
          >
            <div
              style={{
                fontSize: 13,
                color: "var(--text-default)",
                marginBottom: 12,
              }}
            >
              这块区域加了{" "}
              <code style={{ fontFamily: "var(--font-mono)", fontSize: 12 }}>
                data-phase2
              </code>
              ,底色应该比外层凉一档。
            </div>
            <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
              <BirdAvatar id={1} size="lg" status="running" />
              <BirdAvatar id={2} size="lg" status="done" />
              <BirdAvatar id={5} size="lg" status="queued" />
              <BirdBadge id={1} />
              <BirdBadge id={5} />
            </div>
          </div>
        </Section>
      </div>
    </div>
  );
}

// ============================================================
// Phase 3 组合场景

interface Phase3SceneProps {
  selectedAnchor: string | undefined;
  onSelectAnchor: (anchor: string | undefined) => void;
  commentStates: Record<string, boolean | undefined>;
  setAccepted: (id: string, v: boolean | undefined) => void;
}

const PHASE3_COMMENTS = [
  {
    id: "c1",
    birdId: 1 as BirdId,
    anchor: "a-mau",
    eagleMark: "passed" as const,
    dimension: "业务目标",
    title: "MAU 目标缺具体数字",
    body: "业务目标段只说了'提升活跃',没给 30d MAU 的 OKR 对齐目标值。",
    evidence: {
      quote: "本次改造目标是提升用户等级体系对活跃度的提升效果。",
      source: "§1.1 · line 4",
      verification: "verified" as const,
    },
    meta: { model: "sonnet-4-6", conf: 0.92, tokens: "2.1k", rule: "R042" },
  },
  {
    id: "c2",
    birdId: 2 as BirdId,
    anchor: "a-userlevel",
    eagleMark: "passed" as const,
    dimension: "字段口径",
    title: "user_level 跨表口径不一致",
    body: "dim_user.user_level 和 dwd_user.user_level 计算口径不同(前者 T+1,后者实时)。",
    evidence: {
      quote: "使用 user_level 字段判断用户当前等级。",
      source: "§2.3 · line 18",
      verification: "verified" as const,
    },
    meta: { model: "sonnet-4-6", conf: 0.85, tokens: "1.8k", rule: "R203" },
  },
  {
    id: "c3",
    birdId: 3 as BirdId,
    anchor: "a-copy",
    eagleMark: "revoked" as const,
    dimension: "UX 流程",
    title: "注册第 2 步文案歧义",
    body: "体验鸟原说有歧义,但苍鹰认为该文案是 i18n 限制,不属于 PM 可改项。",
    evidence: {
      quote: "请填写您的用户等级偏好。",
      source: "§3.2 · line 27",
      verification: "failed" as const,
    },
    meta: { model: "sonnet-4-6", conf: 0.62, tokens: "1.2k", rule: "R087" },
  },
  {
    id: "c4",
    birdId: 4 as BirdId,
    anchor: undefined,
    eagleMark: "added" as const,
    dimension: "风险 / 依赖",
    title: "(苍鹰补充)下游 risk_service SLA 未声明",
    body: "4 只 worker 都没提,苍鹰交叉校验时补上。",
    meta: { model: "opus-4", conf: 0.78, tokens: "3.4k", rule: "R109" },
  },
];

function Phase3Scene({
  selectedAnchor,
  onSelectAnchor,
  commentStates,
  setAccepted,
}: Phase3SceneProps) {
  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "1.1fr 1fr",
        gap: 16,
        height: 560,
      }}
    >
      <DocumentView
        title="用户等级体系改造 PRD"
        subtitle="v0.3 · 42 blocks"
        blocks={SAMPLE_BLOCKS}
        selectedAnchor={selectedAnchor}
        onAnchorClick={(anchor) =>
          onSelectAnchor(selectedAnchor === anchor ? undefined : anchor)
        }
        style={{ height: "100%" }}
      />
      <div
        style={{
          overflow: "auto",
          display: "flex",
          flexDirection: "column",
          gap: 10,
          paddingRight: 4,
        }}
      >
        {PHASE3_COMMENTS.map((c) => (
          <CommentThread
            key={c.id}
            birdId={c.birdId}
            eagleMark={c.eagleMark}
            dimension={c.dimension}
            title={c.title}
            body={c.body}
            evidence={c.evidence}
            meta={c.meta}
            selected={Boolean(c.anchor && c.anchor === selectedAnchor)}
            accepted={commentStates[c.id]}
            onAccept={() => setAccepted(c.id, true)}
            onReject={() => setAccepted(c.id, false)}
            onEdit={() => {}}
          />
        ))}
      </div>
    </div>
  );
}

// Sample PRD blocks · 带锚点高亮
const SAMPLE_BLOCKS: DocBlock[] = [
  { type: "h", content: "1. 业务背景" },
  {
    type: "p",
    content: "本次改造目标是提升用户等级体系对活跃度的提升效果。",
    highlights: [
      { kind: "weak", start: 9, end: 32, anchor: "a-mau" },
    ],
  },
  { type: "h", content: "2. 数据字段" },
  { type: "h2", content: "2.1 核心表" },
  {
    type: "li",
    content: "dim_user:维度表,包含 user_level 字段",
  },
  {
    type: "li",
    content: "dwd_user:明细表,同样包含 user_level 字段",
  },
  {
    type: "p",
    content: "使用 user_level 字段判断用户当前等级。",
    highlights: [
      { kind: "gap", start: 3, end: 13, anchor: "a-userlevel" },
    ],
  },
  { type: "h", content: "3. 交互流程" },
  { type: "h2", content: "3.2 注册" },
  {
    type: "p",
    content: "请填写您的用户等级偏好。",
    highlights: [
      { kind: "weak", start: 0, end: 12, anchor: "a-copy" },
    ],
  },
  { type: "h", content: "4. 风险 / 依赖" },
  {
    type: "p",
    content:
      "本方案依赖 risk_service 做等级评估。(下游 SLA 未声明,苍鹰补充)",
  },
  {
    type: "p",
    content:
      "(这里还有更多章节,为了演示简洁只列上面几个。真实 PRD 会有 42 个 blocks。)",
  },
];

// ============================================================
// Sprint 1 子组件

function BigDivider({ label }: { label: string }) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 12,
        marginBottom: 24,
        marginTop: 16,
      }}
    >
      <span
        style={{
          fontSize: 11,
          fontWeight: 700,
          textTransform: "uppercase",
          letterSpacing: "1.6px",
          color: "var(--accent-600)",
          padding: "4px 10px",
          borderRadius: "var(--r-pill)",
          background: "var(--accent-50)",
          border: "1px solid color-mix(in oklch, var(--accent-500) 25%, var(--border-subtle))",
          fontFamily: "var(--font-mono)",
        }}
      >
        {label}
      </span>
      <div style={{ flex: 1, height: 1, background: "var(--border-default)" }} />
    </div>
  );
}

function Section({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section style={{ marginBottom: 48 }}>
      <h2
        style={{
          fontSize: 11,
          fontWeight: 600,
          textTransform: "uppercase",
          letterSpacing: "1.2px",
          color: "var(--text-muted)",
          borderBottom: "1px solid var(--border-subtle)",
          paddingBottom: 6,
          marginBottom: 16,
        }}
      >
        {title}
      </h2>
      {children}
    </section>
  );
}

function BirdAvatarGrid() {
  return (
    <table
      style={{
        borderCollapse: "collapse",
        fontSize: 12,
        color: "var(--text-muted)",
      }}
    >
      <thead>
        <tr>
          <th style={thStyle}>id</th>
          <th style={thStyle}>label</th>
          <th style={thStyle}>lg 32</th>
          <th style={thStyle}>md 24</th>
          <th style={thStyle}>sm 16</th>
        </tr>
      </thead>
      <tbody>
        {ALL_BIRDS.map((id) => (
          <tr key={id}>
            <td style={tdStyle}>
              <code style={{ fontFamily: "var(--font-mono)" }}>{id}</code>
            </td>
            <td style={tdStyle}>{BIRD_META[id].label}</td>
            <td style={tdStyle}>
              <BirdAvatar id={id} size="lg" />
            </td>
            <td style={tdStyle}>
              <BirdAvatar id={id} size="md" />
            </td>
            <td style={tdStyle}>
              <BirdAvatar id={id} size="sm" />
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function StatusGrid() {
  return (
    <table
      style={{
        borderCollapse: "collapse",
        fontSize: 12,
        color: "var(--text-muted)",
      }}
    >
      <thead>
        <tr>
          <th style={thStyle}>bird</th>
          {STATUSES.map((s) => (
            <th key={s} style={thStyle}>
              <code style={{ fontFamily: "var(--font-mono)" }}>{s}</code>
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {[1, 2, 3, 4, 5].map((id) => (
          <tr key={id}>
            <td style={tdStyle}>
              <BirdBadge id={id as BirdId} size="sm" />
            </td>
            {STATUSES.map((s) => (
              <td key={s} style={tdStyle}>
                <BirdAvatar id={id as BirdId} size="lg" status={s} />
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function BirdBadgeGrid() {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div>
        <div style={labelStyle}>md(12px)</div>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          {ALL_BIRDS.map((id) => (
            <BirdBadge key={id} id={id} size="md" />
          ))}
        </div>
      </div>
      <div>
        <div style={labelStyle}>sm(11px)</div>
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
          {ALL_BIRDS.map((id) => (
            <BirdBadge key={id} id={id} size="sm" />
          ))}
        </div>
      </div>
    </div>
  );
}

const thStyle: React.CSSProperties = {
  textAlign: "left",
  padding: "8px 12px",
  fontWeight: 500,
  fontSize: 11,
  textTransform: "uppercase",
  letterSpacing: "0.8px",
  color: "var(--text-faint)",
  borderBottom: "1px solid var(--border-subtle)",
};

const tdStyle: React.CSSProperties = {
  padding: "8px 12px",
  borderBottom: "1px solid var(--border-subtle)",
  verticalAlign: "middle",
};

const labelStyle: React.CSSProperties = {
  fontSize: 11,
  fontFamily: "var(--font-mono)",
  color: "var(--text-faint)",
  marginBottom: 6,
};
