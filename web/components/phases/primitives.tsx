/**
 * @deprecated-v7
 *
 * Phase primitives — v7 线稿现代散文组件原子 · v8 已全部废弃
 *
 * v8 方向从"杂志气质"切到"工作台气质",以下全部不再使用,由 v8 新组件替代:
 * - PaperCard(半透纸卡) → 直接用 var(--surface-raised) + 1px border + --r-4(8px)
 * - PaperHead(刊头三件套) → PhaseNav(顶部常驻)+ 页面内简单 h1
 * - NumberedField(01/02/03 手工学) → 标准无衬线 label + input
 * - UnderlineInput(下划线输入) → 标准 shadcn Input / Base UI input
 * - CtaArrow(1.5px 墨色右箭头) → 标准 Button with --accent-500
 * - SubmitRow(签名分隔线) → 底部标准按钮行
 * - Signature(手写签名尾) → 直接删掉,v8 不要"署名"叙事
 *
 * 保留仅为让 Phase 0-4 老组件不崩;Sprint 2-3 重做 phase 时清理对它们的引用。
 */

import type { InputHTMLAttributes, ReactNode } from "react";

// ============================================================
// PaperCard — 统一的纸片卡片
// 纸白底 + 1px 墨色边 + 12px radius · 无 tilt · 无 shadow
// ============================================================
export function PaperCard({
  children,
  className = "",
  dashed = false,
}: {
  children: ReactNode;
  className?: string;
  dashed?: boolean;
}) {
  return (
    <div
      className={`rounded-[12px] border ${dashed ? "border-dashed" : ""} ${className}`}
      style={{
        borderColor: dashed
          ? "rgba(58,66,56,0.3)"
          : "rgba(58,66,56,0.22)",
        background: "rgba(255,253,247,0.45)",
      }}
    >
      {children}
    </div>
  );
}

// ============================================================
// PaperHead — 表单顶部的 "副标题 / 大标题 / 版次号"
// ============================================================
export function PaperHead({
  subtitle,
  title,
  rev,
}: {
  subtitle: string;
  title: ReactNode;
  rev?: string;
}) {
  return (
    <div className="mb-9 flex items-baseline justify-between gap-4 border-b border-foreground/[0.18] pb-6">
      <div>
        <div
          className="mb-[6px] font-mono text-[10.5px] uppercase tracking-[0.24em]"
          style={{ color: "var(--pecker-moss-deep)" }}
        >
          {subtitle}
        </div>
        <h2
          className="font-serif text-[26px] font-medium leading-[1.25] tracking-[-0.012em]"
          style={{ fontFamily: "var(--font-fraunces), 'PingFang SC', serif" }}
        >
          {title}
        </h2>
      </div>
      {rev && (
        <div className="font-mono text-[11.5px] tracking-[0.1em] text-foreground/50">
          {rev}
        </div>
      )}
    </div>
  );
}

// ============================================================
// NumberedField — 01 · 标签 · 右侧提示 + 下方内容
// ============================================================
export function NumberedField({
  num,
  label,
  hint,
  children,
  className = "",
}: {
  num: string;
  label: string;
  hint?: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={`mb-8 ${className}`}>
      <div className="mb-3 flex items-baseline gap-[14px]">
        <span
          className="w-[22px] font-mono text-[11px] tracking-[0.1em]"
          style={{ color: "var(--pecker-moss-deep)" }}
        >
          {num}
        </span>
        <span
          className="font-serif text-[15px] font-medium tracking-[-0.003em]"
          style={{ fontFamily: "var(--font-fraunces), 'PingFang SC', serif" }}
        >
          {label}
        </span>
        {hint && (
          <span
            className="ml-auto text-[12.5px] font-light italic text-foreground/45"
            style={{ fontFamily: "var(--font-fraunces), serif" }}
          >
            {hint}
          </span>
        )}
      </div>
      {children}
    </div>
  );
}

// ============================================================
// UnderlineInput — 下划线式文本输入
// ============================================================
export function UnderlineInput(props: InputHTMLAttributes<HTMLInputElement>) {
  const { className = "", style, ...rest } = props;
  return (
    <input
      {...rest}
      className={`w-full border-0 border-b border-foreground/[0.25] bg-transparent px-[2px] pb-[10px] pt-[6px] font-serif text-[19px] tracking-[-0.005em] text-foreground outline-none transition-colors placeholder:italic placeholder:font-light placeholder:text-foreground/45 focus:border-foreground ${className}`}
      style={{
        fontFamily: "var(--font-fraunces), 'PingFang SC', serif",
        ...style,
      }}
    />
  );
}

// ============================================================
// CtaArrow — 1.5px border + 右箭头 hover 反白
// 小屏全宽,大屏自适应
// ============================================================
export function CtaArrow({
  children,
  onClick,
  disabled = false,
  type = "button",
  variant = "primary",
}: {
  children: ReactNode;
  onClick?: () => void;
  disabled?: boolean;
  type?: "button" | "submit";
  variant?: "primary" | "ghost";
}) {
  const isGhost = variant === "ghost";
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      className={`group inline-flex items-center gap-[14px] rounded-[8px] px-7 py-[13px] font-serif text-[15px] font-medium tracking-[0.02em] transition-all duration-200 disabled:cursor-not-allowed disabled:opacity-50 ${
        isGhost
          ? "border border-foreground/30 text-foreground/70 hover:border-foreground/60 hover:text-foreground"
          : "border-[1.5px] border-foreground bg-transparent text-foreground hover:bg-foreground hover:text-[#f7f1dd]"
      }`}
      style={{ fontFamily: "var(--font-fraunces), 'PingFang SC', serif" }}
    >
      {children}
      <span className="text-[17px] transition-transform group-hover:translate-x-1">
        →
      </span>
    </button>
  );
}

// ============================================================
// Signature — 评审人署名(EM: 小字 caps + 名字 serif)
// ============================================================
export function Signature({
  reviewer,
  date,
}: {
  reviewer: string;
  date?: string;
}) {
  return (
    <div
      className="font-serif text-[14px] leading-[1.5] text-foreground"
      style={{ fontFamily: "var(--font-fraunces), 'PingFang SC', serif" }}
    >
      <span className="mb-[3px] block font-mono text-[11px] uppercase tracking-[0.12em] text-foreground/45">
        评审人
      </span>
      {reviewer}
      {date && ` · ${date}`}
    </div>
  );
}

// ============================================================
// SubmitRow — 底部 "签名(左) + CTA(右)" 的分隔线组合
// ============================================================
export function SubmitRow({
  children,
  className = "",
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={`mt-11 flex items-center justify-between gap-6 border-t border-foreground/[0.18] pt-7 ${className}`}
    >
      {children}
    </div>
  );
}

// ============================================================
// Foot — 纸片底部的灰字说明
// ============================================================
export function Foot({
  children,
  align = "right",
}: {
  children: ReactNode;
  align?: "left" | "right" | "center";
}) {
  const cls =
    align === "center"
      ? "text-center"
      : align === "left"
        ? "text-left"
        : "text-right";
  return (
    <div
      className={`mt-5 text-[12px] font-light italic tracking-[0.02em] text-foreground/45 ${cls}`}
      style={{ fontFamily: "var(--font-fraunces), 'PingFang SC', serif" }}
    >
      {children}
    </div>
  );
}
