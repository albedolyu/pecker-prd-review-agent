/**
 * @deprecated-v7
 *
 * PhaseHead — v7"现代散文"杂志刊头 · v8 已废弃
 *
 * v8 方向是"工作台"气质,不再用 eyebrow + Fraunces 大标 + lead 的刊头式页头。
 * 新页面用 PhaseNav(web/components/nav/PhaseNav.tsx)+ 页面内直接展开内容,
 * 禁用本组件。
 *
 * 保留仅为让 Phase 0-4 旧组件不崩;Sprint 2-3 重做这 5 个 phase 时移除对它的引用。
 *
 * ─── 原 v7 视觉 ───
 * - eyebrow: JetBrains Mono · 小号 · moss 绿 · 带下划线
 * - title: Fraunces serif · 大号 · 行内 italic em(moss 色)
 * - lead: 细衬线 · 行高 1.9 · 居中 · 可内嵌 "/" 分隔符
 */

import type { ReactNode } from "react";

export interface PhaseHeadProps {
  eyebrow: string;
  title: ReactNode;
  lead?: ReactNode;
  align?: "center" | "left";
  className?: string;
}

export function PhaseHead({
  eyebrow,
  title,
  lead,
  align = "center",
  className = "",
}: PhaseHeadProps) {
  const textAlign = align === "center" ? "text-center" : "text-left";
  const leadMx = align === "center" ? "mx-auto" : "";
  return (
    <div className={`${textAlign} ${className}`}>
      <div
        className="mb-4 inline-block border-b pb-[6px] font-mono text-[11px] uppercase tracking-[0.28em]"
        style={{
          color: "var(--pecker-moss-deep)",
          borderColor: "var(--pecker-moss-deep)",
        }}
      >
        {eyebrow}
      </div>
      <h1
        className="font-serif text-[38px] font-normal leading-[1.2] tracking-[-0.015em] sm:text-[46px]"
        style={{ fontFamily: "var(--font-fraunces), 'PingFang SC', serif" }}
      >
        {title}
      </h1>
      {lead && (
        <p
          className={`mt-4 max-w-[36rem] text-[15.5px] font-light leading-[1.9] tracking-[0.008em] text-foreground/60 ${leadMx}`}
        >
          {lead}
        </p>
      )}
    </div>
  );
}

/**
 * 散文分隔符 —— v7 里常见的 "/" 灰字斜杠
 */
export function LeadSep() {
  return <span className="mx-[0.4em] text-foreground/30">/</span>;
}
