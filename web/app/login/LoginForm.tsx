"use client";

/**
 * LoginForm — /login 的 client 组件
 *
 * 后端 POST /api/auth/login 验证 PECKER_WEB_PASSWORD,成功后签 JWT cookie
 * (HS256,8h TTL,HttpOnly,SameSite=Lax)。
 *
 * reviewer 写进 JWT payload,用于:
 * - TopBanner 显示 + 今日次数统计
 * - 审计日志归因
 * - readonly 拦截(如果 reviewer 在 PECKER_READONLY_USERS 列表里)
 */

import { useEffect, useState, type FormEvent } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { KeyRound, User, Loader2 } from "lucide-react";
import { toast } from "sonner";

import { authApi, ApiError } from "@/lib/api";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { Alert, AlertDescription } from "@/components/ui/alert";

export function LoginForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const queryClient = useQueryClient();

  const [password, setPassword] = useState("");
  const [reviewer, setReviewer] = useState("");

  // 已经登录 → 直接跳 /review
  const { data: me } = useQuery({
    queryKey: ["me"],
    queryFn: () => authApi.me(),
    retry: false,
    staleTime: 60 * 1000,
  });

  useEffect(() => {
    if (me?.reviewer) {
      const next = searchParams.get("next") ?? "/review";
      router.replace(next);
    }
  }, [me, router, searchParams]);

  // 从 localStorage 读回上次用的 reviewer 名字(便利功能)
  useEffect(() => {
    try {
      const remembered = localStorage.getItem("pecker_last_reviewer");
      if (remembered) setReviewer(remembered);
    } catch {
      // localStorage disabled,忽略
    }
  }, []);

  const loginMutation = useMutation({
    mutationFn: () => authApi.login(password, reviewer.trim()),
    onSuccess: (resp) => {
      try {
        localStorage.setItem("pecker_last_reviewer", resp.reviewer);
      } catch {
        // ignore
      }
      toast.success(
        `欢迎,${resp.reviewer}${resp.readonly ? "(只读)" : ""}`,
      );
      queryClient.invalidateQueries({ queryKey: ["me"] });
      const next = searchParams.get("next") ?? "/review";
      router.replace(next);
    },
    onError: (e: ApiError) => {
      if (e.status === 401) {
        toast.error("密码错误");
      } else if (e.status === 503) {
        toast.error("服务端未配置密码(PECKER_WEB_PASSWORD)");
      } else {
        toast.error(`登录失败: ${e.detail ?? e.message}`);
      }
    },
  });

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (!password || !reviewer.trim()) {
      toast.warning("请填写完整");
      return;
    }
    loginMutation.mutate();
  };

  return (
    <div className="flex min-h-[calc(100vh-3.5rem)] items-center justify-center px-6 py-12">
      <Card className="w-full max-w-sm">
        <CardHeader className="space-y-1">
          <CardTitle className="flex items-center gap-2">
            <span className="text-xl">🪵</span>
            啄木鸟登录
          </CardTitle>
          <CardDescription>
            使用团队共享密码进入 PRD 评审系统。
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="space-y-1.5">
              <Label htmlFor="reviewer">评审人姓名</Label>
              <div className="relative">
                <User className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
                <Input
                  id="reviewer"
                  className="pl-8"
                  placeholder="张三"
                  value={reviewer}
                  onChange={(e) => setReviewer(e.target.value)}
                  maxLength={40}
                  required
                />
              </div>
              <p className="text-[11px] text-muted-foreground">
                用于报告署名 + 审计 + readonly 判定
              </p>
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="password">团队密码</Label>
              <div className="relative">
                <KeyRound className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
                <Input
                  id="password"
                  type="password"
                  className="pl-8"
                  placeholder="••••••••"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
                />
              </div>
            </div>

            <Button
              type="submit"
              className="w-full"
              disabled={loginMutation.isPending}
            >
              {loginMutation.isPending ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  登录中...
                </>
              ) : (
                "登录"
              )}
            </Button>

            <Alert className="bg-muted/40 text-[11px]">
              <AlertDescription>
                密码由管理员通过 env var <code>PECKER_WEB_PASSWORD</code> 配置。
                登录态为 HttpOnly JWT cookie,8 小时后自动失效。
              </AlertDescription>
            </Alert>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
