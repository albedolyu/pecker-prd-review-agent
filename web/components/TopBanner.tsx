"use client";

/**
 * TopBanner — 所有页面顶部的横条
 *
 * 内容:
 * - 左: 品牌名 "啄木鸟 Pecker"(仅文字,Phase D 加 logo)
 * - 中: 当前 reviewer / workspace / 今日评审次数
 * - 右: readonly 徽章(如果是只读用户)+ About / 登出
 *
 * 数据源:
 * - /api/me → reviewer + readonly
 * - /api/audit/today/{reviewer} → 今日次数
 *
 * 未登录(/api/me 401)时只显示品牌名 + 登录链接。
 */

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { LogOut, Eye, Sparkles } from "lucide-react";
import { toast } from "sonner";

import { authApi, auditApi, ApiError } from "@/lib/api";
import { Button, buttonVariants } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { cn } from "@/lib/utils";

export function TopBanner() {
  const router = useRouter();
  const queryClient = useQueryClient();

  // 当前登录态
  const { data: me, isLoading: meLoading } = useQuery({
    queryKey: ["me"],
    queryFn: () => authApi.me(),
    retry: false,
    staleTime: 60 * 1000,
  });

  // 今日次数(依赖登录态)
  const { data: todayCount } = useQuery({
    queryKey: ["audit", "today", me?.reviewer],
    queryFn: () => auditApi.todayCount(me!.reviewer),
    enabled: !!me?.reviewer,
    staleTime: 30 * 1000,
  });

  const handleLogout = async () => {
    try {
      await authApi.logout();
      queryClient.clear();
      toast.success("已登出");
      router.push("/login");
    } catch (e) {
      const err = e as ApiError;
      toast.error(`登出失败: ${err.detail ?? err.message}`);
    }
  };

  return (
    <header className="sticky top-0 z-40 w-full border-b bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/80">
      <div className="mx-auto flex h-14 max-w-6xl items-center gap-4 px-6">
        {/* ========== 左: 品牌 ========== */}
        <Link
          href="/review"
          className="flex items-center gap-2 font-semibold tracking-tight"
        >
          <span className="text-lg">🪵</span>
          <span className="text-base">啄木鸟</span>
          <span className="hidden text-xs uppercase text-muted-foreground sm:inline">
            Pecker
          </span>
        </Link>

        {/* ========== 中: reviewer 信息(登录后显示) ========== */}
        {me && (
          <>
            <Separator orientation="vertical" className="h-5" />
            <div className="flex items-center gap-3 text-sm">
              <span className="text-muted-foreground">评审人</span>
              <span className="font-medium">{me.reviewer}</span>
              {me.readonly && (
                <Badge variant="secondary" className="gap-1 px-2 py-0">
                  <Eye className="h-3 w-3" />
                  只读
                </Badge>
              )}
              {todayCount !== undefined && (
                <span className="hidden text-muted-foreground md:inline">
                  今日 <span className="font-medium text-foreground">
                    {todayCount.count}
                  </span> 次
                </span>
              )}
            </div>
          </>
        )}

        {/* ========== 右: 辅助操作 ========== */}
        <div className="ml-auto flex items-center gap-2">
          <Link
            href="/about"
            className={cn(buttonVariants({ variant: "ghost", size: "sm" }))}
          >
            <Sparkles className="mr-1 h-3.5 w-3.5" />
            关于
          </Link>

          {!meLoading && !me && (
            <Link
              href="/login"
              className={cn(buttonVariants({ variant: "outline", size: "sm" }))}
            >
              登录
            </Link>
          )}

          {me && (
            <Button variant="ghost" size="sm" onClick={handleLogout}>
              <LogOut className="mr-1 h-3.5 w-3.5" />
              登出
            </Button>
          )}
        </div>
      </div>
    </header>
  );
}
