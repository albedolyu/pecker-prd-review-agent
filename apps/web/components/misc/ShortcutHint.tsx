/**
 * ShortcutHint · v8 键盘快捷键提示
 *
 * 11px pill + kbd 样式。贴在可操作元素右侧,或用 KeymapBar 做底部常驻条。
 * - inline 变体(默认):浅底,用在组件内部旁边
 * - dark 变体:暗底,用在 Phase 2 console 区域
 *
 * 规范源:design-system/Pecker-pecker-v8/components/shortcut-hint.jsx
 */

import { Fragment } from "react";

export type ShortcutVariant = "inline" | "dark";

interface ShortcutHintProps {
  /** 快捷键数组,多个键用 / 分隔(如 ["j"] / ["cmd", "enter"]) */
  keys: string[];
  /** 键后面的文字说明(如 "接受") */
  label?: string;
  variant?: ShortcutVariant;
  className?: string;
  style?: React.CSSProperties;
}

export function ShortcutHint({
  keys,
  label,
  variant = "inline",
  className,
  style,
}: ShortcutHintProps) {
  const isDark = variant === "dark";
  return (
    <span
      className={className}
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 4,
        fontSize: 11,
        color: isDark ? "var(--neutral-400)" : "var(--text-muted)",
        ...style,
      }}
    >
      {keys.map((k, i) => (
        <Fragment key={i}>
          <kbd
            style={{
              display: "inline-flex",
              alignItems: "center",
              justifyContent: "center",
              minWidth: 18,
              height: 18,
              padding: "0 4px",
              background: isDark
                ? "var(--neutral-100)"
                : "var(--neutral-50)",
              border: `1px solid ${isDark ? "var(--neutral-200)" : "var(--border-default)"}`,
              borderBottomWidth: 2,
              borderRadius: "var(--r-2)",
              fontFamily: "var(--font-mono)",
              fontSize: 10,
              fontWeight: 600,
              color: isDark ? "var(--neutral-700)" : "var(--text-strong)",
              lineHeight: 1,
            }}
          >
            {k}
          </kbd>
          {i < keys.length - 1 && <span style={{ opacity: 0.4 }}>/</span>}
        </Fragment>
      ))}
      {label && <span style={{ marginLeft: 2 }}>{label}</span>}
    </span>
  );
}

interface KeymapBarItem {
  keys: string[];
  label: string;
}

interface KeymapBarProps {
  items: KeymapBarItem[];
  className?: string;
  style?: React.CSSProperties;
}

/** 底部常驻快捷键条(Phase 3 用) */
export function KeymapBar({ items, className, style }: KeymapBarProps) {
  return (
    <div
      className={className}
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 16,
        padding: "8px 14px",
        background: "var(--surface-raised)",
        border: "1px solid var(--border-default)",
        borderRadius: "var(--r-4)",
        boxShadow: "var(--shadow-sm)",
        fontFamily: "var(--font-sans)",
        ...style,
      }}
    >
      {items.map((it, i) => (
        <ShortcutHint key={i} keys={it.keys} label={it.label} />
      ))}
    </div>
  );
}
