import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";

import { Providers } from "@/components/providers";
import { TopBanner } from "@/components/TopBanner";

// v8 只引入 Geist 家族(sans + mono)。
// @deprecated-v7 · Fraunces serif 已移除 —— 新页面用 var(--font-sans) + var(--font-mono)
const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
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
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body
        className="min-h-full flex flex-col bg-background text-foreground"
        style={{
          fontFamily:
            "var(--font-geist-sans), 'PingFang SC', 'Microsoft YaHei', 'Hiragino Sans GB', sans-serif",
        }}
      >
        <Providers>
          <div className="flex flex-1 flex-col">
            <TopBanner />
            <main className="flex-1">{children}</main>
          </div>
        </Providers>
      </body>
    </html>
  );
}
