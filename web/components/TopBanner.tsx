"use client";

/**
 * TopBanner · v8 · 全局顶栏(工作台气质)
 *
 * 功能零回归:
 * - /api/me → reviewer + readonly
 * - /api/audit/today/{reviewer} → 今日次数
 * - About 链接 / 登出 按钮
 *
 * v8 视觉:
 * - 无衬线字体 · 紧凑 · monospace 元数据
 * - brand:主编鸟头像 + "Pecker" 字样,去 "2026 春" 季节标签
 * - 中间:reviewer + 今日次数(mono)· 去散文式"你好"
 * - 右:About / 登出 极简文字链
 */

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { BirdAvatar } from "@/components/birds/BirdAvatar";
import { authApi, auditApi, ApiError } from "@/lib/api";

export function TopBanner() {
  const router = useRouter();
  const queryClient = useQueryClient();

  const { data: me, isLoading: meLoading } = useQuery({
    queryKey: ["me"],
    queryFn: () => authApi.me(),
    retry: false,
    staleTime: 60 * 1000,
  });

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
    <header
      style={{
        position: "relative",
        zIndex: 30,
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        padding: "10px 20px",
        borderBottom: "1px solid var(--border-subtle)",
        background: "var(--surface-raised)",
        fontFamily: "var(--font-sans)",
      }}
    >
      {/* ── 左 · brand ── */}
      <Link
        href="/review"
        style={{
          display: "inline-flex",
          alignItems: "center",
          gap: 8,
          color: "var(--text-strong)",
          textDecoration: "none",
        }}
      >
        <BrandMark />
        <span
          style={{
            fontSize: 14,
            fontWeight: 600,
            letterSpacing: 0,
          }}
        >
          Pecker
        </span>
        <span
          style={{
            fontSize: 11,
            color: "var(--text-faint)",
            fontWeight: 500,
            letterSpacing: 0,
          }}
        >
          评审工作台
        </span>
      </Link>

      {/* ── 右 · reviewer + 辅助 ── */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 14,
          fontSize: 12,
          color: "var(--text-muted)",
        }}
      >
        {me && (
          <>
            <span
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: 6,
              }}
            >
              <span
                style={{
                  fontSize: 11,
                  color: "var(--text-faint)",
                }}
              >
                当前用户
              </span>
              <span
                style={{
                  fontWeight: 500,
                  color: "var(--text-default)",
                }}
              >
                {me.reviewer}
              </span>
              {me.readonly && (
                <span
                  style={{
                    fontSize: 10,
                    padding: "1px 5px",
                    borderRadius: "var(--r-2)",
                    background: "var(--status-queued-bg)",
                    color: "var(--status-queued-fg)",
                    fontWeight: 600,
                  }}
                >
                  只读
                </span>
              )}
            </span>
            {todayCount && (
              <>
                <Divider />
                <span
                  style={{
                    display: "none",
                    alignItems: "center",
                    gap: 6,
                  }}
                  className="sm:inline-flex"
                >
                  <span
                    style={{
                      fontSize: 11,
                      color: "var(--text-faint)",
                    }}
                  >
                    今日已评
                  </span>
                  <span
                    style={{
                      fontWeight: 600,
                      color: "var(--text-default)",
                      fontVariantNumeric: "tabular-nums",
                    }}
                  >
                    {todayCount.count}
                  </span>
                </span>
              </>
            )}
            <Divider />
          </>
        )}

        <Link
          href="/runs/diff"
          style={{
            color: "var(--text-muted)",
            textDecoration: "none",
            transition: "color var(--dur-fast) var(--ease-out)",
          }}
          onMouseEnter={(e) =>
            ((e.currentTarget as HTMLAnchorElement).style.color =
              "var(--accent-600)")
          }
          onMouseLeave={(e) =>
            ((e.currentTarget as HTMLAnchorElement).style.color =
              "var(--text-muted)")
          }
        >
          评审记录
        </Link>
        <Link
          href="/system/health"
          style={{
            color: "var(--text-muted)",
            textDecoration: "none",
            transition: "color var(--dur-fast) var(--ease-out)",
          }}
          onMouseEnter={(e) =>
            ((e.currentTarget as HTMLAnchorElement).style.color =
              "var(--accent-600)")
          }
          onMouseLeave={(e) =>
            ((e.currentTarget as HTMLAnchorElement).style.color =
              "var(--text-muted)")
          }
        >
          质量看板
        </Link>
        <Link
          href="/about"
          style={{
            color: "var(--text-muted)",
            textDecoration: "none",
            transition: "color var(--dur-fast) var(--ease-out)",
          }}
          onMouseEnter={(e) =>
            ((e.currentTarget as HTMLAnchorElement).style.color =
              "var(--accent-600)")
          }
          onMouseLeave={(e) =>
            ((e.currentTarget as HTMLAnchorElement).style.color =
              "var(--text-muted)")
          }
        >
          使用说明
        </Link>

        {!meLoading && !me && (
          <Link
            href="/login"
            style={{
              color: "var(--accent-600)",
              textDecoration: "none",
              fontWeight: 500,
            }}
          >
            登录
          </Link>
        )}

        {me && (
          <button
            type="button"
            onClick={handleLogout}
            style={{
              background: "transparent",
              border: 0,
              cursor: "pointer",
              color: "var(--text-muted)",
              fontSize: 12,
              fontFamily: "var(--font-sans)",
              padding: 0,
              transition: "color var(--dur-fast) var(--ease-out)",
            }}
            onMouseEnter={(e) =>
              ((e.currentTarget as HTMLButtonElement).style.color =
                "var(--status-failed-fg)")
            }
            onMouseLeave={(e) =>
              ((e.currentTarget as HTMLButtonElement).style.color =
                "var(--text-muted)")
            }
          >
            退出
          </button>
        )}
      </div>
    </header>
  );
}

// ============================================================
// v8 · brand mark · 主编鸟头像
// ============================================================
function BrandMark() {
  return (
    <span
      aria-hidden
      style={{
        position: "relative",
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        width: 30,
        height: 30,
        borderRadius: "50%",
        background: "var(--surface-raised)",
        border: "1px solid color-mix(in oklch, var(--accent-500) 35%, var(--border-default))",
        boxShadow: "0 0 0 2px var(--accent-50)",
        overflow: "hidden",
        flexShrink: 0,
      }}
    >
      <BirdAvatar
        id={6}
        size="lg"
        style={{
          width: 28,
          height: 28,
        }}
      />
    </span>
  );
}

function Divider() {
  return (
    <span
      aria-hidden
      style={{
        width: 1,
        height: 14,
        background: "var(--border-default)",
      }}
    />
  );
}
