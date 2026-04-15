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
 *
 * Phase F 视觉:
 * - 非对称 split(左 kraft + 巨型引语 + 爪印,右 form 去 Card 壳)
 * - 下划线 input 取代 shadcn Input
 * - 按钮 hover 右上角冒红笔勾
 */

import { useEffect, useState, type FormEvent } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { authApi, ApiError } from "@/lib/api";
import { PeckerClaw } from "@/components/PeckerClaw";

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
    <main className="relative grid min-h-[calc(100vh-3.5rem)] grid-cols-1 md:grid-cols-[1.45fr_1fr]">
      {/* ========== 左:空白 + 引语 + 脚印 ========== */}
      <aside
        className="relative hidden flex-col justify-between overflow-hidden bg-pecker-kraft px-[var(--spacing-gutter)] py-12 md:flex
          before:pointer-events-none before:absolute before:inset-0 before:mix-blend-multiply before:opacity-60 before:content-[''] before:pecker-grain-bg"
      >
        {/* 顶部刊眉 */}
        <div className="relative flex items-baseline gap-3 font-mono text-[10px] uppercase tracking-[0.18em] text-foreground/60">
          <span>啄木鸟内刊</span>
          <span className="h-px flex-1 bg-foreground/60" />
          <span>卷一</span>
        </div>

        {/* 中部:巨大衬线引语,故意断行 */}
        <blockquote className="relative max-w-[22ch]">
          <span
            aria-hidden
            className="absolute -left-6 -top-10 font-serif text-[9rem] leading-[0.6] text-pecker-red/20"
          >
            &ldquo;
          </span>
          <p className="font-serif text-[2.35rem] leading-[1.18] tracking-tight text-foreground/90">
            评审不是
            <br />
            <span className="ink-mark">挑刺</span>,
            <br />
            是把没说清楚的事
            <br />
            <span className="font-light italic">逼出来</span>。
          </p>
          <footer className="mt-5 font-mono text-[10px] uppercase tracking-[0.2em] text-foreground/50">
            —— 苍鹰 · 终审纪要 001
          </footer>
        </blockquote>

        {/* 底部:3 个爪印 + 版次 */}
        <div className="relative flex items-end justify-between font-mono text-[10px] uppercase tracking-[0.16em] text-foreground/50">
          <div className="tilt-c flex items-center gap-[6px] text-foreground/65">
            <PeckerClaw className="opacity-55" />
            <PeckerClaw className="-translate-y-[3px] opacity-70" />
            <PeckerClaw className="opacity-85" />
          </div>
          <span>第 壹 期 · 春</span>
        </div>
      </aside>

      {/* ========== 右:form(去 Card 壳) ========== */}
      <section className="relative flex items-center px-[var(--spacing-gutter)] py-12">
        <div className="relative w-full max-w-[22rem]">
          {/* 小刊眉 */}
          <div className="mb-2 font-mono text-[10px] uppercase tracking-[0.2em] text-foreground/55">
            登 · 录 · 口
          </div>

          {/* 标题,非卡片 */}
          <h1 className="font-serif text-[2.1rem] leading-[1.05] tracking-tight">
            今日
            <br />
            <span className="ink-mark">签 到</span>
          </h1>
          <p className="mt-3 max-w-[18rem] text-[13px] leading-[1.7] text-foreground/65">
            输入你的名字和团队密码,进入今天的评审桌。
            名字会记在报告署名和审计日志里。
          </p>

          {/* form:不用 card,直接贴着 */}
          <form onSubmit={handleSubmit} className="mt-8 space-y-5">
            <label className="block">
              <span className="font-mono text-[10px] uppercase tracking-[0.14em] text-foreground/55">
                01 · 评审人
              </span>
              <input
                type="text"
                value={reviewer}
                onChange={(e) => setReviewer(e.target.value)}
                maxLength={40}
                required
                placeholder="你的名字"
                className="mt-1 w-full border-0 border-b border-foreground/35 bg-transparent px-0 py-2 font-serif text-[1.1rem] text-foreground placeholder:italic placeholder:text-foreground/30 focus:border-b-2 focus:border-pecker-red focus:outline-none"
              />
            </label>
            <label className="block">
              <span className="font-mono text-[10px] uppercase tracking-[0.14em] text-foreground/55">
                02 · 团队密码
              </span>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                placeholder="••••••••"
                className="mt-1 w-full border-0 border-b border-foreground/35 bg-transparent px-0 py-2 font-serif text-[1.1rem] text-foreground placeholder:italic placeholder:text-foreground/30 focus:border-b-2 focus:border-pecker-red focus:outline-none"
              />
            </label>

            <button
              type="submit"
              disabled={loginMutation.isPending}
              className="group relative mt-4 inline-flex items-center gap-3 bg-foreground px-5 py-2 font-serif text-[1.05rem] text-background shadow-print transition-all duration-300 hover:shadow-print-lift disabled:opacity-60 hover:[transform:rotate(0.6deg)]"
            >
              {loginMutation.isPending ? "登录中..." : "进入编辑部"}
              <span className="font-mono text-[11px] opacity-70 transition-transform group-hover:translate-x-1">
                →
              </span>
              {/* hover 时右上角冒出红笔勾 */}
              <span
                aria-hidden
                className="absolute -right-2 -top-3 rotate-[8deg] font-serif text-[1.3rem] text-pecker-red opacity-0 transition-opacity duration-300 group-hover:opacity-100"
              >
                ✓
              </span>
            </button>
          </form>

          {/* 底部说明,手写批注气息 */}
          <div className="mt-10 flex items-start gap-2 border-t border-dashed border-foreground/20 pt-4 font-mono text-[10px] uppercase tracking-[0.12em] text-foreground/50">
            <span className="text-pecker-red">✱</span>
            <span className="normal-case leading-[1.7] tracking-normal">
              密码由管理员通过 env var <code>PECKER_WEB_PASSWORD</code> 配置。
              登录态为 HttpOnly JWT cookie,8 小时后自动失效。
            </span>
          </div>
        </div>
      </section>
    </main>
  );
}
