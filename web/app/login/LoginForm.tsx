"use client";

/**
 * LoginForm · v8 · 工作台气质登录
 *
 * 数据契约零改动:
 * - authApi.login(password, reviewer) → JWT cookie(HS256, 8h TTL)
 * - authApi.me() · 已登录跳 next 或 /review
 * - localStorage.pecker_last_reviewer 记住上次用户名
 *
 * v8 UI:
 * - 生成式 10 鸟协作插画 + 400px 登录表单
 * - 无衬线表单 · accent 主按钮 · 极简
 */

import { useEffect, useState, type FormEvent } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { BirdAvatar } from "@/components/birds/BirdAvatar";
import { authApi, ApiError } from "@/lib/api";

export function LoginForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const queryClient = useQueryClient();

  const [password, setPassword] = useState("");
  const [reviewer, setReviewer] = useState("");
  const [remember, setRemember] = useState(true);

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

  useEffect(() => {
    try {
      const remembered = localStorage.getItem("pecker_last_reviewer");
      // eslint-disable-next-line react-hooks/set-state-in-effect -- 仅启动时从 localStorage 恢复一次,不会级联
      if (remembered) setReviewer(remembered);
    } catch {
      /* ignore */
    }
  }, []);

  const loginMutation = useMutation({
    mutationFn: () => authApi.login(password, reviewer.trim()),
    onSuccess: (resp) => {
      try {
        if (remember)
          localStorage.setItem("pecker_last_reviewer", resp.reviewer);
      } catch {
        /* ignore */
      }
      toast.success(
        `欢迎,${resp.reviewer}${resp.readonly ? "(只读权限)" : ""}`,
      );
      queryClient.invalidateQueries({ queryKey: ["me"] });
      const next = searchParams.get("next") ?? "/review";
      router.replace(next);
    },
    onError: (e: ApiError) => {
      if (e.status === 401) toast.error("密码错误");
      else if (e.status === 503)
        toast.error("还未配置登录密码,请联系工具负责人");
      else if (e.status === 0) toast.error(e.message);
      else toast.error(`登录失败: ${e.detail ?? e.message}`);
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
    <main
      style={{
        minHeight: "calc(100vh - 60px)",
        display: "grid",
        placeItems: "center",
        padding: "40px 24px",
        fontFamily: "var(--font-sans)",
        background: "var(--surface-canvas)",
      }}
    >
      <div
        style={{
          width: "100%",
          maxWidth: 980,
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 360px), 1fr))",
          alignItems: "center",
          gap: 36,
        }}
      >
        <LoginBirdTeamIllustration />

        <div style={{ width: "100%", maxWidth: 400, justifySelf: "center" }}>
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 10,
              marginBottom: 24,
            }}
          >
            <BrandMark />
            <span
              style={{
                fontSize: 15,
                fontWeight: 600,
                color: "var(--text-strong)",
              }}
            >
              Pecker
            </span>
          </div>

          <form
            onSubmit={handleSubmit}
            style={{
              background: "var(--surface-raised)",
              border: "1px solid var(--border-default)",
              borderRadius: "var(--r-4)",
              padding: "28px 28px 24px",
              boxShadow: "var(--shadow-sm)",
            }}
          >
            <header style={{ marginBottom: 20 }}>
              <h1
                style={{
                  fontSize: 20,
                  fontWeight: 600,
                  color: "var(--text-strong)",
                  margin: 0,
                }}
              >
                登录
              </h1>
              <p
                style={{
                  fontSize: 12,
                  color: "var(--text-muted)",
                  marginTop: 4,
                }}
              >
                PRD 评审工作台 · 使用团队密码登录
              </p>
            </header>

            <div
              style={{
                display: "flex",
                flexDirection: "column",
                gap: 14,
              }}
            >
              <Field label="评审人" hint="会出现在评审报告署名">
                <input
                  type="text"
                  value={reviewer}
                  onChange={(e) => setReviewer(e.target.value)}
                  maxLength={40}
                  required
                  placeholder="晨舒"
                  autoFocus
                  style={inputStyle}
                />
              </Field>

              <Field label="密码">
                <input
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
                  placeholder="············"
                  style={inputStyle}
                />
              </Field>

              <label
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 8,
                  cursor: "pointer",
                  fontSize: 12,
                  color: "var(--text-muted)",
                  paddingTop: 2,
                }}
              >
                <input
                  type="checkbox"
                  checked={remember}
                  onChange={(e) => setRemember(e.target.checked)}
                  style={{
                    width: 14,
                    height: 14,
                    cursor: "pointer",
                    accentColor: "var(--accent-500)",
                  }}
                />
                记住我 · 8 小时内免登录
              </label>

              <button
                type="submit"
                disabled={loginMutation.isPending}
                style={{
                  height: 38,
                  marginTop: 6,
                  border: 0,
                  borderRadius: "var(--r-3)",
                  background: loginMutation.isPending
                    ? "var(--neutral-200)"
                    : "var(--accent-500)",
                  color: loginMutation.isPending
                    ? "var(--text-muted)"
                    : "var(--accent-fg)",
                  fontSize: 13,
                  fontWeight: 600,
                  cursor: loginMutation.isPending ? "not-allowed" : "pointer",
                  fontFamily: "var(--font-sans)",
                  transition: "background var(--dur-fast) var(--ease-out)",
                }}
              >
                {loginMutation.isPending ? "登录中…" : "登录 →"}
              </button>
            </div>

            <div
              style={{
                marginTop: 20,
                paddingTop: 14,
                borderTop: "1px solid var(--border-subtle)",
                fontSize: 11,
                color: "var(--text-faint)",
                textAlign: "center",
                lineHeight: 1.65,
              }}
            >
              第一次来？找工具负责人要密码,登录后即可使用评审工作台。
            </div>
          </form>

          <div
            style={{
              marginTop: 16,
              textAlign: "center",
            }}
          >
            <Link
              href="/"
              style={{
                fontSize: 12,
                color: "var(--text-muted)",
                textDecoration: "none",
              }}
            >
              ← 回首页
            </Link>
          </div>
        </div>
      </div>
    </main>
  );
}

// ============================================================

function LoginBirdTeamIllustration() {
  return (
    <section
      aria-label="十只鸟协作评审插画"
      style={{
        width: "100%",
        minWidth: 0,
        justifySelf: "center",
      }}
    >
      <img
        src="/illustrations/login-bird-team.jpg"
        alt="十只鸟围绕 PRD 评审桌协作"
        style={{
          display: "block",
          width: "100%",
          aspectRatio: "16 / 10",
          objectFit: "cover",
          borderRadius: "var(--r-4)",
          border: "1px solid var(--border-default)",
          boxShadow: "var(--shadow-sm)",
        }}
      />
      <p
        style={{
          margin: "14px 0 0",
          maxWidth: 560,
          fontSize: 13,
          lineHeight: 1.7,
          color: "var(--text-muted)",
        }}
      >
        十个检查角色围绕同一份 PRD 协作:先分方向检查,再合并复核,最后交给 PM 确认。
      </p>
    </section>
  );
}

function BrandMark() {
  return (
    <span
      aria-hidden
      style={{
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        width: 30,
        height: 30,
        borderRadius: "50%",
        background: "var(--surface-raised)",
        border:
          "1px solid color-mix(in oklch, var(--accent-500) 35%, var(--border-default))",
        boxShadow: "0 0 0 2px var(--accent-50)",
        overflow: "hidden",
        flexShrink: 0,
      }}
    >
      <BirdAvatar id={6} size="lg" style={{ width: 28, height: 28 }} />
    </span>
  );
}

function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      <div
        style={{
          display: "flex",
          alignItems: "baseline",
          gap: 8,
        }}
      >
        <label
          style={{
            fontSize: 12,
            fontWeight: 600,
            color: "var(--text-strong)",
          }}
        >
          {label}
        </label>
        {hint && (
          <span style={{ fontSize: 11, color: "var(--text-muted)" }}>
            {hint}
          </span>
        )}
      </div>
      {children}
    </div>
  );
}

const inputStyle: React.CSSProperties = {
  width: "100%",
  height: 36,
  border: "1px solid var(--border-default)",
  borderRadius: "var(--r-3)",
  background: "var(--surface-raised)",
  padding: "0 12px",
  fontFamily: "var(--font-sans)",
  fontSize: 13,
  color: "var(--text-default)",
  outline: "none",
};
