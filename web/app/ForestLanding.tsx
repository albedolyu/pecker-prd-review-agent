"use client";

/**
 * ForestLanding · 登录前首页(团队试用入口)
 *
 * 给 PM 同事看的第一屏只保留可理解入口,不暴露组件预览、版本代号、
 * 老版回退等内部调试信息。
 *
 * 不依赖后端(/api/me 不在这里调),可作为未登录第一眼。
 */

import Link from "next/link";
import { useRouter } from "next/navigation";
import { BirdAvatar, type BirdId } from "@/components/birds/BirdAvatar";

const ALL_BIRDS: BirdId[] = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10];
const LANDING_BIRD_LABELS: Record<BirdId, string> = {
  1: "完整性",
  2: "字段",
  3: "体验",
  4: "风险",
  5: "复核",
  6: "收口",
  7: "反馈",
  8: "样例",
  9: "资料",
  10: "质检",
};

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
          Pecker · PRD 评审工作台
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
          提交前,先把{" "}
          <span style={{ color: "var(--accent-500)" }}>PRD</span> 查清楚
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
          重点检查目标范围、字段口径、异常边界和实现依赖。跑完后得到一份可确认的修改清单,方便你补充 PRD、同步研发和沉淀报告。
        </p>

        {/* 10 只鸟展示 */}
        <div
          aria-label="啄木鸟评审团队"
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
            />
          ))}
        </div>

        {/* 角色一句话 */}
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(10, minmax(34px, 1fr))",
            gap: 8,
            marginTop: 12,
            maxWidth: 680,
            fontSize: 11,
            fontFamily: "var(--font-sans)",
            color: "var(--text-faint)",
            letterSpacing: 0,
          }}
        >
          {ALL_BIRDS.map((id) => (
            <div key={id} style={{ textAlign: "center" }}>
              {LANDING_BIRD_LABELS[id as BirdId]}
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
            开始评审 →
          </button>
          <Link href="/login" style={btnSecondary}>
            登录工作台
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
            tag="过程可见"
            title="先确认本次结果是否完整"
            desc="评审结束前先看各方向是否都返回了意见,结果不完整时会提醒重新评审,避免拿残缺结论做判断"
          />
          <Feature
            tag="结论可用"
            title="把问题整理成可处理清单"
            desc="每条意见对应位置、原因和建议,你可以直接接受、驳回或改写,不会被一大段泛泛建议淹没"
          />
          <Feature
            tag="交付可追溯"
            title="评审报告可以直接归档"
            desc="确认后的结果会生成报告和修订建议包,后续复盘、同步研发或交给测试同事都有依据"
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
        <span>Pecker · PRD 评审工作台 · 内部试用</span>
        <span>有问题请反馈给工具负责人</span>
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
