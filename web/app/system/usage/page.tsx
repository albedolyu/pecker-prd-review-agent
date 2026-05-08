"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { adminUsageApi, ApiError, type UsageRun } from "@/lib/api";

const DAY_OPTIONS = [7, 30, 90] as const;

export default function AdminUsagePage() {
  const [days, setDays] = useState<number>(7);
  const { data, error, isLoading, isFetching } = useQuery({
    queryKey: ["admin-usage", days],
    queryFn: () => adminUsageApi.get(days),
    retry: false,
    staleTime: 30 * 1000,
  });

  const apiError = error instanceof ApiError ? error : null;
  const summary = data?.summary;
  const budgetSpent = Number(data?.budget?.spent ?? 0);
  const budgetLimit = Number(data?.budget?.limit ?? 0);
  const budgetEnabled = Boolean(data?.budget?.enabled);
  const budgetText = budgetEnabled
    ? `$${budgetSpent.toFixed(2)} / $${budgetLimit.toFixed(2)}`
    : "未设置";

  const completionRate = useMemo(() => {
    if (!summary?.total_reviews) return "0%";
    return `${Math.round((summary.completed / summary.total_reviews) * 100)}%`;
  }, [summary]);

  if (apiError?.status === 403) {
    return (
      <PageShell>
        <EmptyState
          title="这个看板仅管理员可见"
          desc={apiError.detail ?? "请用管理员账号登录后查看团队使用情况。"}
        />
      </PageShell>
    );
  }

  return (
    <PageShell>
      <header
        style={{
          display: "flex",
          alignItems: "flex-start",
          justifyContent: "space-between",
          gap: 16,
          marginBottom: 20,
        }}
      >
        <div>
          <div style={eyebrowStyle}>团队看板</div>
          <h1
            style={{
              margin: 0,
              color: "var(--text-strong)",
              fontSize: 24,
              fontWeight: 650,
              letterSpacing: 0,
            }}
          >
            团队使用情况
          </h1>
          <p
            style={{
              margin: "6px 0 0",
              color: "var(--text-muted)",
              fontSize: 13,
              lineHeight: 1.6,
            }}
          >
            看谁在用、最近跑了多少次、有没有失败和预算消耗。不展示 PRD 正文。
          </p>
        </div>
        <label
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 8,
            color: "var(--text-muted)",
            fontSize: 12,
          }}
        >
          时间范围
          <select
            value={days}
            onChange={(e) => setDays(Number(e.target.value))}
            style={{
              height: 34,
              border: "1px solid var(--border-default)",
              borderRadius: "var(--r-3)",
              background: "var(--surface-raised)",
              color: "var(--text-default)",
              padding: "0 10px",
              fontFamily: "var(--font-sans)",
            }}
          >
            {DAY_OPTIONS.map((value) => (
              <option key={value} value={value}>
                最近 {value} 天
              </option>
            ))}
          </select>
        </label>
      </header>

      {isLoading && <EmptyState title="正在读取使用情况" desc="稍等一下，马上就好。" />}
      {apiError && apiError.status !== 403 && (
        <EmptyState title="读取失败" desc={apiError.detail ?? apiError.message} />
      )}

      {data && summary && (
        <>
          <section
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(5, minmax(0, 1fr))",
              gap: 12,
              marginBottom: 18,
            }}
          >
            <MetricCard label="评审次数" value={summary.total_reviews} />
            <MetricCard label="活跃同事" value={summary.active_reviewers} />
            <MetricCard label="完成率" value={completionRate} />
            <MetricCard label="平均耗时" value={formatDuration(summary.avg_duration_ms)} />
            <MetricCard label="今日预算" value={budgetText} compact />
          </section>

          {isFetching && (
            <div
              style={{
                marginBottom: 12,
                color: "var(--text-faint)",
                fontSize: 12,
              }}
            >
              正在刷新...
            </div>
          )}

          <section style={cardStyle}>
            <SectionHead title="同事使用概览" hint="按最近使用和评审次数排序" />
            {data.reviewers.length ? (
              <div style={{ overflowX: "auto" }}>
                <table style={tableStyle}>
                  <thead>
                    <tr>
                      {["同事", "评审次数", "完成", "异常", "常用资料库", "最近一次"].map((label) => (
                        <th key={label} style={thStyle}>{label}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {data.reviewers.map((reviewer) => {
                      const topWorkspace = Object.entries(reviewer.workspaces)[0];
                      return (
                        <tr key={reviewer.reviewer}>
                          <td style={tdStyle}>{reviewer.reviewer}</td>
                          <td style={tdMonoStyle}>{reviewer.reviews}</td>
                          <td style={tdMonoStyle}>{reviewer.completed}</td>
                          <td style={tdMonoStyle}>{reviewer.failed + reviewer.degraded}</td>
                          <td style={tdStyle}>
                            {topWorkspace
                              ? `${topWorkspace[0].replace(/^workspace-/, "")} (${topWorkspace[1]})`
                              : "暂无"}
                          </td>
                          <td style={tdStyle}>
                            <div>{formatTime(reviewer.last_seen)}</div>
                            <div style={{ color: "var(--text-faint)", fontSize: 11 }}>
                              {reviewer.last_prd_name || "暂无材料名"}
                            </div>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            ) : (
              <InlineEmpty text="还没有同事开始评审。" />
            )}
          </section>

          <div
            style={{
              display: "grid",
              gridTemplateColumns: "1.35fr 1fr",
              gap: 16,
              marginTop: 16,
            }}
          >
            <section style={cardStyle}>
              <SectionHead title="最近评审" hint="只展示材料名和运行结果" />
              {data.recent_runs.length ? (
                <div style={{ display: "flex", flexDirection: "column" }}>
                  {data.recent_runs.slice(0, 10).map((run, index) => (
                    <RecentRunRow key={`${run.ts_start}-${index}`} run={run} />
                  ))}
                </div>
              ) : (
                <InlineEmpty text="暂无评审记录。" />
              )}
            </section>

            <section style={cardStyle}>
              <SectionHead title="最近动作" hint="上传、开始评审、下载报告等关键动作" />
              {data.recent_actions.length ? (
                <div style={{ display: "flex", flexDirection: "column" }}>
                  {data.recent_actions.slice(0, 12).map((action, index) => (
                    <div
                      key={`${action.ts}-${action.event}-${index}`}
                      style={{
                        padding: "10px 16px",
                        borderTop: "1px solid var(--border-subtle)",
                        fontSize: 12,
                      }}
                    >
                      <div
                        style={{
                          display: "flex",
                          justifyContent: "space-between",
                          gap: 10,
                          color: "var(--text-default)",
                        }}
                      >
                        <span>{actionLabel(action.event)}</span>
                        <span style={{ color: "var(--text-faint)" }}>
                          {formatTime(action.ts)}
                        </span>
                      </div>
                      <div style={{ marginTop: 3, color: "var(--text-muted)" }}>
                        {action.reviewer || "unknown"} ·{" "}
                        {action.workspace?.replace(/^workspace-/, "") || "未选资料库"}
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <InlineEmpty text="暂无动作记录。" />
              )}
            </section>
          </div>
        </>
      )}
    </PageShell>
  );
}

function PageShell({ children }: { children: React.ReactNode }) {
  return (
    <div
      style={{
        maxWidth: 1180,
        margin: "0 auto",
        padding: "30px 24px 80px",
        minHeight: "100vh",
        fontFamily: "var(--font-sans)",
      }}
    >
      {children}
    </div>
  );
}

function MetricCard({
  label,
  value,
  compact,
}: {
  label: string;
  value: string | number;
  compact?: boolean;
}) {
  return (
    <div style={{ ...cardStyle, padding: "14px 16px" }}>
      <div
        style={{
          color: "var(--text-faint)",
          fontSize: 11,
          fontWeight: 600,
        }}
      >
        {label}
      </div>
      <div
        style={{
          marginTop: 6,
          color: "var(--text-strong)",
          fontSize: compact ? 18 : 24,
          fontWeight: 650,
          fontVariantNumeric: "tabular-nums",
          whiteSpace: "nowrap",
        }}
      >
        {value}
      </div>
    </div>
  );
}

function SectionHead({ title, hint }: { title: string; hint: string }) {
  return (
    <header
      style={{
        padding: "13px 16px",
        borderBottom: "1px solid var(--border-subtle)",
      }}
    >
      <div style={{ color: "var(--text-strong)", fontSize: 14, fontWeight: 650 }}>
        {title}
      </div>
      <div style={{ color: "var(--text-muted)", fontSize: 11, marginTop: 2 }}>
        {hint}
      </div>
    </header>
  );
}

function RecentRunRow({ run }: { run: UsageRun }) {
  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "1fr 92px 86px",
        gap: 12,
        alignItems: "center",
        padding: "11px 16px",
        borderTop: "1px solid var(--border-subtle)",
        fontSize: 12,
      }}
    >
      <div>
        <div style={{ color: "var(--text-default)", fontWeight: 600 }}>
          {run.prd_name || "未命名材料"}
        </div>
        <div style={{ color: "var(--text-muted)", marginTop: 3 }}>
          {run.reviewer || "unknown"} · {run.workspace?.replace(/^workspace-/, "") || "未选资料库"}
        </div>
      </div>
      <span
        style={{
          justifySelf: "start",
          borderRadius: "var(--r-pill)",
          padding: "2px 8px",
          background: statusTone(run.status).bg,
          color: statusTone(run.status).fg,
          fontWeight: 600,
          fontSize: 11,
        }}
      >
        {statusLabel(run.status)}
      </span>
      <div style={{ color: "var(--text-muted)", textAlign: "right" }}>
        <div>{formatDuration(run.duration_ms)}</div>
        <div style={{ color: "var(--text-faint)", marginTop: 2 }}>
          {formatTime(run.ts_start)}
        </div>
      </div>
    </div>
  );
}

function EmptyState({ title, desc }: { title: string; desc: string }) {
  return (
    <div
      style={{
        ...cardStyle,
        padding: "36px 24px",
        color: "var(--text-muted)",
        textAlign: "center",
      }}
    >
      <h2 style={{ margin: 0, color: "var(--text-strong)", fontSize: 18 }}>
        {title}
      </h2>
      <p style={{ margin: "8px 0 0", fontSize: 13 }}>{desc}</p>
    </div>
  );
}

function InlineEmpty({ text }: { text: string }) {
  return (
    <div style={{ padding: 16, color: "var(--text-muted)", fontSize: 12 }}>
      {text}
    </div>
  );
}

function formatDuration(ms?: number) {
  const value = Number(ms ?? 0);
  if (!value) return "0 分钟";
  const minutes = Math.max(1, Math.round(value / 60000));
  return `${minutes} 分钟`;
}

function formatTime(ts?: string) {
  if (!ts) return "暂无";
  const match = ts.match(/^\d{4}-(\d{2})-(\d{2})T(\d{2}):(\d{2})/);
  return match ? `${match[1]}-${match[2]} ${match[3]}:${match[4]}` : ts;
}

function statusLabel(status?: string) {
  return {
    completed: "已完成",
    failed: "失败",
    degraded: "部分完成",
    unknown: "未确认",
  }[status ?? "unknown"] ?? "未确认";
}

function statusTone(status?: string) {
  if (status === "completed") {
    return { bg: "var(--status-done-bg)", fg: "var(--status-done-fg)" };
  }
  if (status === "failed") {
    return { bg: "var(--status-failed-bg)", fg: "var(--status-failed-fg)" };
  }
  return { bg: "var(--status-warn-bg)", fg: "var(--status-warn-fg)" };
}

function actionLabel(event?: string) {
  return {
    review_started: "开始评审",
    report_downloaded: "下载报告",
    wiki_saved: "保存到知识库",
    feishu_pushed: "推送飞书",
    item_feedback: "标记意见",
  }[event ?? ""] ?? (event || "记录动作");
}

const cardStyle: React.CSSProperties = {
  background: "var(--surface-raised)",
  border: "1px solid var(--border-default)",
  borderRadius: "var(--r-4)",
  overflow: "hidden",
};

const eyebrowStyle: React.CSSProperties = {
  color: "var(--accent-600)",
  fontSize: 11,
  fontWeight: 700,
  marginBottom: 5,
};

const tableStyle: React.CSSProperties = {
  width: "100%",
  minWidth: 760,
  borderCollapse: "collapse",
  fontSize: 12,
};

const thStyle: React.CSSProperties = {
  padding: "10px 16px",
  textAlign: "left",
  color: "var(--text-faint)",
  borderBottom: "1px solid var(--border-subtle)",
  fontWeight: 650,
};

const tdStyle: React.CSSProperties = {
  padding: "11px 16px",
  borderBottom: "1px solid var(--border-subtle)",
  color: "var(--text-default)",
  verticalAlign: "top",
};

const tdMonoStyle: React.CSSProperties = {
  ...tdStyle,
  fontVariantNumeric: "tabular-nums",
};

