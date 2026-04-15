import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
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
        className="min-h-full flex flex-col bg-muted/30 text-foreground"
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
