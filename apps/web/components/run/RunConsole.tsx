/**
 * RunConsole · v8 Phase 2 流式日志
 *
 * 深色局部卡(--surface-console)· 时间戳 · 来源 · 内容三列 · 流式光标
 * 顶部 macOS 风格红黄绿点 + "LIVE" 指示灯(running 时呼吸)
 *
 * 规范源:design-system/Pecker-pecker-v8/components/run-console.jsx
 */

import type { BirdId } from "@/components/birds/BirdAvatar";

export type ConsoleLevel = "info" | "warn" | "error" | "ok" | "accent";

export interface ConsoleSource {
  bird?: BirdId;
  name: string;
}

export interface ConsoleLine {
  /** 时间戳,如 "12.3s" 或 "12:34:56" */
  t: string;
  src?: ConsoleSource;
  level?: ConsoleLevel;
  text: string;
}

interface RunConsoleProps {
  lines: ConsoleLine[];
  live?: boolean;
  /** px 高度 */
  height?: number;
  className?: string;
  style?: React.CSSProperties;
}

export function RunConsole({
  lines,
  live = true,
  height = 280,
  className,
  style,
}: RunConsoleProps) {
  return (
    <div
      className={className}
      style={{
        background: "var(--surface-console)",
        color: "var(--surface-console-fg)",
        borderRadius: "var(--r-4)",
        fontFamily: "var(--font-mono)",
        fontSize: 12,
        lineHeight: 1.55,
        overflow: "hidden",
        display: "flex",
        flexDirection: "column",
        height,
        ...style,
      }}
    >
      {/* header */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "8px 14px",
          borderBottom: "1px solid rgba(255,255,255,0.06)",
          fontSize: 11,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{ display: "flex", gap: 5 }}>
            <span
              style={{
                width: 8,
                height: 8,
                borderRadius: "50%",
                background: "#ff5f57",
              }}
            />
            <span
              style={{
                width: 8,
                height: 8,
                borderRadius: "50%",
                background: "#febc2e",
              }}
            />
            <span
              style={{
                width: 8,
                height: 8,
                borderRadius: "50%",
                background: "#28c840",
              }}
            />
          </span>
          <span style={{ opacity: 0.6, letterSpacing: 0.3 }}>
            处理进度
          </span>
        </div>
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 6,
            opacity: live ? 0.9 : 0.4,
          }}
        >
          {live && (
            <>
              <span
                style={{
                  width: 6,
                  height: 6,
                  borderRadius: "50%",
                  background: "var(--accent-500)",
                  animation: "dot-breathe 1.4s ease-out infinite",
                }}
              />
              <span>实时</span>
            </>
          )}
        </div>
      </div>

      {/* body */}
      <div style={{ flex: 1, overflow: "auto", padding: "10px 14px" }}>
        {lines.length === 0 && !live && (
          <div
            style={{
              color: "rgba(255,255,255,0.35)",
              fontStyle: "italic",
              padding: "4px 0",
            }}
          >
            暂无进度
          </div>
        )}
        {lines.map((l, i) => (
          <ConsoleLineRow key={i} line={l} />
        ))}
        {live && (
          <div
            style={{ display: "flex", alignItems: "center", marginTop: 4 }}
          >
            <span style={{ color: "rgba(255,255,255,0.35)" }}>›</span>
            <span
              style={{
                display: "inline-block",
                width: 7,
                height: 14,
                marginLeft: 6,
                background: "var(--accent-500)",
                animation: "dot-breathe 1.1s linear infinite",
              }}
            />
          </div>
        )}
      </div>
    </div>
  );
}

function ConsoleLineRow({ line }: { line: ConsoleLine }) {
  const { t, src, level = "info", text } = line;

  const levelColor: Record<ConsoleLevel, string> = {
    info: "rgba(255,255,255,0.8)",
    warn: "#e9b450",
    error: "#ff8579",
    ok: "#5ec784",
    accent: "#ff8c4a",
  };

  const birdColor: Record<BirdId, string> = {
    1: "#ff8c4a",
    2: "#7aabee",
    3: "#5ec784",
    4: "#ff8579",
    5: "#b9a3ff",
    6: "rgba(255,255,255,0.5)",
    7: "rgba(255,255,255,0.5)",
    8: "rgba(255,255,255,0.5)",
    9: "rgba(255,255,255,0.5)",
    10: "rgba(255,255,255,0.5)",
  };

  const srcColor = src?.bird
    ? birdColor[src.bird]
    : "rgba(255,255,255,0.5)";

  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "64px 110px 1fr",
        gap: 10,
        padding: "1px 0",
      }}
    >
      <span
        style={{
          color: "rgba(255,255,255,0.35)",
          fontVariantNumeric: "tabular-nums",
        }}
      >
        {t}
      </span>
      <span style={{ color: srcColor, fontWeight: 500 }}>
        {src?.name ? `[${src.name}]` : "[进度]"}
      </span>
      <span
        style={{
          color: levelColor[level],
          whiteSpace: "pre-wrap",
          wordBreak: "break-word",
        }}
      >
        {text}
      </span>
    </div>
  );
}
