import type { Metadata } from "next";
import { Geist, Geist_Mono, Fraunces } from "next/font/google";
import "./globals.css";

import { Providers } from "@/components/providers";
import { TopBanner } from "@/components/TopBanner";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

// Fraunces — 现代 transitional serif,带 optical size 变化,
// 给标题一种"刻金属印刷"的严肃感。中文字符会自动 fallback 到
// 系统 PingFang SC / 微软雅黑,形成 latin serif + 中文黑体的
// 编辑部混排气质。
const fraunces = Fraunces({
  variable: "--font-fraunces",
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  style: ["normal", "italic"],
});

export const metadata: Metadata = {
  title: "啄木鸟 Pecker — PRD 评审",
  description:
    "PM 用的 PRD 评审工具:4 位编辑并行审查 + 终审交叉校验 + 飞书推送。",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="zh-CN"
      className={`${geistSans.variable} ${geistMono.variable} ${fraunces.variable} h-full antialiased`}
    >
      <body
        className="min-h-full flex flex-col bg-background text-foreground"
        style={{
          fontFamily:
            "var(--font-geist-sans), 'PingFang SC', 'Microsoft YaHei', 'Hiragino Sans GB', sans-serif",
        }}
      >
        <Providers>
          <TopBanner />
          <main className="flex-1">{children}</main>
        </Providers>
      </body>
    </html>
  );
}
