import type { Metadata } from "next";
import "./globals.css";

import { Providers } from "@/components/providers";
import { TopBanner } from "@/components/TopBanner";

export const metadata: Metadata = {
  title: "Pecker — PRD Review",
  description:
    "PM 用的 PRD 提交前检查工具:检查目标范围、字段口径、体验细节和实现风险,并导出可同步的评审报告。",
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
