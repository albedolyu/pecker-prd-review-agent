"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";

import { authApi } from "@/lib/api";

export function AdminOnlyPage({ children }: { children: React.ReactNode }) {
  const { data: me, isLoading, isError } = useQuery({
    queryKey: ["me"],
    queryFn: () => authApi.me(),
    retry: false,
    staleTime: 60 * 1000,
  });

  if (isLoading) {
    return (
      <RestrictedShell
        title="正在确认权限"
        desc="稍等一下，马上就好。"
      />
    );
  }

  if (isError) {
    return (
      <RestrictedShell
        title="暂时无法确认权限"
        desc="请刷新页面后再试；如果仍然不行，请联系工具负责人检查登录服务。"
      />
    );
  }

  if (!me?.is_admin) {
    return (
      <RestrictedShell
        title="这个页面仅管理员可见"
        desc="这里包含团队质量或规则样例，普通评审同事请从评审工作台进入。"
      />
    );
  }

  return <>{children}</>;
}

function RestrictedShell({ title, desc }: { title: string; desc: string }) {
  return (
    <div
      style={{
        maxWidth: 680,
        margin: "0 auto",
        padding: "64px 24px 80px",
        minHeight: "100vh",
        fontFamily: "var(--font-sans)",
      }}
    >
      <div
        style={{
          border: "1px solid var(--border-default)",
          borderRadius: "var(--r-4)",
          background: "var(--surface-raised)",
          padding: "30px 32px",
          color: "var(--text-default)",
        }}
      >
        <div
          style={{
            color: "var(--accent-600)",
            fontSize: 12,
            fontWeight: 700,
            marginBottom: 8,
          }}
        >
          管理员页面
        </div>
        <h1
          style={{
            margin: 0,
            color: "var(--text-strong)",
            fontSize: 24,
            fontWeight: 650,
            letterSpacing: 0,
          }}
        >
          {title}
        </h1>
        <p
          style={{
            margin: "10px 0 0",
            color: "var(--text-muted)",
            fontSize: 14,
            lineHeight: 1.7,
          }}
        >
          {desc}
        </p>
        <Link
          href="/review"
          style={{
            marginTop: 22,
            height: 36,
            display: "inline-flex",
            alignItems: "center",
            padding: "0 14px",
            borderRadius: "var(--r-3)",
            background: "var(--accent-600)",
            color: "white",
            textDecoration: "none",
            fontWeight: 650,
            fontSize: 13,
          }}
        >
          返回评审
        </Link>
      </div>
    </div>
  );
}
