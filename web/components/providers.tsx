"use client";

/**
 * 全局 Provider 壳 — 所有 client 依赖在这里集中:
 * - TanStack Query: /api/me / /api/workspaces / /api/drafts 的缓存
 * - shadcn TooltipProvider: RoleCard hover 彩蛋
 * - sonner Toaster: 全局通知(飞书发送/保存 wiki/报错)
 *
 * 被 app/layout.tsx 的 server component 包住 children。
 */

import { useState, type ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { TooltipProvider } from "@/components/ui/tooltip";
import { Toaster } from "@/components/ui/sonner";

export function Providers({ children }: { children: ReactNode }) {
  // QueryClient 在组件内创建,保证每个 render 实例有自己的 cache,
  // 避免 Next.js dev HMR 时跨 hot reload 串 cache
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 30 * 1000, // 30 秒内不 refetch
            gcTime: 5 * 60 * 1000, // 5 分钟 GC
            retry: (failureCount, error) => {
              // 认证失败不重试,其他错误最多重试 1 次
              const status = (error as { status?: number })?.status;
              if (status === 401 || status === 403) return false;
              return failureCount < 1;
            },
            refetchOnWindowFocus: false,
          },
        },
      }),
  );

  return (
    <QueryClientProvider client={queryClient}>
      <TooltipProvider delay={200}>{children}</TooltipProvider>
      <Toaster position="top-right" richColors closeButton />
    </QueryClientProvider>
  );
}
