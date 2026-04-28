import type { Metadata } from "next";
import "./globals.css";

import { Providers } from "@/components/providers";
import { TopBanner } from "@/components/TopBanner";

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
    <html lang="zh-CN" className="h-full antialiased">
      <body
        className="min-h-full flex flex-col bg-background text-foreground"
        style={{
          fontFamily:
            "var(--font-sans), 'PingFang SC', 'Microsoft YaHei', 'Hiragino Sans GB', sans-serif",
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
