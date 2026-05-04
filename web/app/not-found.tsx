import Link from "next/link";
import { LostBird } from "./not-found-bird";

/**
 * /not-found · 404 页面
 *
 * Next App Router 自动捕获:
 *   - 不匹配的路由(用户输错地址 / 旧链接失效)
 *   - 显式 notFound() 调用
 *
 * 走 Pecker 工作台一致的 charcoal/orange/cream 调子,配一只困惑的小啄木鸟
 * 让"页面找不到"不那么冷。biz-lost.png 缺失时 onError 静默隐藏,文案 + CTA
 * 仍能单独成立 — 鸟只是"加分项",不是页面骨架。
 */

export const metadata = {
  title: "找不到页面 · Pecker",
};

export default function NotFound() {
  return (
    <main
      style={{
        minHeight: "calc(100vh - 60px)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: "60px 24px",
        fontFamily: "var(--font-sans)",
        background: "var(--surface-canvas)",
      }}
    >
      <div style={{ textAlign: "center", maxWidth: 480 }}>
        <LostBird />

        {/* eyebrow */}
        <div
          style={{
            fontSize: 11,
            fontWeight: 600,
            color: "var(--accent-600)",
            letterSpacing: "0.04em",
            marginBottom: 8,
          }}
        >
          404 · 找不到这个页面
        </div>

        {/* headline */}
        <h1
          style={{
            fontSize: 22,
            fontWeight: 600,
            color: "var(--text-strong)",
            margin: 0,
            letterSpacing: "-0.015em",
            lineHeight: 1.3,
          }}
        >
          这只啄木鸟也不知道你要找什么
        </h1>

        {/* subtitle */}
        <p
          style={{
            fontSize: 14,
            color: "var(--text-muted)",
            marginTop: 10,
            lineHeight: 1.65,
          }}
        >
          可能是链接过期了,或者地址打错了。
          <br />
          要不回评审工作台再试一次?
        </p>

        {/* CTA */}
        <div
          style={{
            marginTop: 24,
            display: "flex",
            gap: 10,
            justifyContent: "center",
            flexWrap: "wrap",
          }}
        >
          <Link
            href="/review"
            style={{
              display: "inline-flex",
              alignItems: "center",
              padding: "9px 18px",
              borderRadius: "var(--r-3)",
              background: "var(--accent-500)",
              color: "var(--accent-fg)",
              fontSize: 13,
              fontWeight: 600,
              textDecoration: "none",
            }}
          >
            进入评审 →
          </Link>
          <Link
            href="/"
            style={{
              display: "inline-flex",
              alignItems: "center",
              padding: "9px 18px",
              borderRadius: "var(--r-3)",
              border: "1px solid var(--border-default)",
              background: "var(--surface-raised)",
              color: "var(--text-default)",
              fontSize: 13,
              fontWeight: 500,
              textDecoration: "none",
            }}
          >
            ← 回首页
          </Link>
        </div>
      </div>
    </main>
  );
}
