"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import {
  adminUsageApi,
  ApiError,
  type ActiveReviewDraft,
  type ActiveReviewJob,
  type AdminReviewJobEvent,
  type FeedbackBucket,
  type FeedbackRecord,
  type MissingFeedbackRecord,
  type UsageRun,
} from "@/lib/api";
import { AdminOnlyPage } from "@/components/auth/AdminOnlyPage";

const DAY_OPTIONS = [7, 30, 90] as const;
const FEEDBACK_ACTION_OPTIONS = [
  { value: "all", label: "全部反馈" },
  { value: "reject", label: "只看驳回" },
  { value: "edit", label: "只看改写" },
  { value: "accept", label: "只看认可" },
] as const;

type FeedbackActionFilter = (typeof FEEDBACK_ACTION_OPTIONS)[number]["value"];

export default function AdminUsagePage() {
  return (
    <AdminOnlyPage>
      <AdminUsageContent />
    </AdminOnlyPage>
  );
}

function AdminUsageContent() {
  const [days, setDays] = useState<number>(7);
  const [feedbackAction, setFeedbackAction] = useState<FeedbackActionFilter>("all");
  const { data, error, isLoading, isFetching } = useQuery({
    queryKey: ["admin-usage", days],
    queryFn: () => adminUsageApi.get(days),
    retry: false,
    staleTime: 30 * 1000,
  });
  const {
    data: feedbackData,
    error: feedbackError,
    isFetching: feedbackFetching,
  } = useQuery({
    queryKey: ["admin-feedback", days, feedbackAction],
    queryFn: () => adminUsageApi.feedback(days, { action: feedbackAction }),
    retry: false,
    staleTime: 30 * 1000,
  });

  const apiError = error instanceof ApiError ? error : null;
  const feedbackApiError = feedbackError instanceof ApiError ? feedbackError : null;
  const summary = data?.summary;
  const feedbackSummary = feedbackData?.summary;
  const budgetSpent = Number(data?.budget?.spent ?? 0);
  const budgetLimit = Number(data?.budget?.limit ?? 0);
  const budgetEnabled = Boolean(data?.budget?.enabled);
  const budgetText = budgetEnabled
    ? `$${budgetSpent.toFixed(2)} / $${budgetLimit.toFixed(2)}`
    : "未设置";

  const activeJobs = data?.active_jobs ?? [];
  const activeDrafts = data?.active_drafts ?? [];
  const recentJobEvents = data?.recent_job_events ?? [];

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

          {(isFetching || feedbackFetching) && (
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

          {activeJobs.length > 0 && (
            <section style={{ ...cardStyle, marginBottom: 16 }}>
              <SectionHead
                title="正在处理的评审"
                hint="只显示任务状态和材料名，不显示 PRD 正文；同事反馈卡住时优先看这里"
              />
              <div style={{ display: "flex", flexDirection: "column" }}>
                {activeJobs.slice(0, 8).map((job) => (
                  <ReviewJobRow key={job.job_id} job={job} />
                ))}
              </div>
            </section>
          )}

          {recentJobEvents.length > 0 && (
            <section style={{ ...cardStyle, marginBottom: 16 }}>
              <SectionHead
                title="最近处理轨迹"
                hint="服务重启后也能保留的脱敏阶段记录；同事反馈超时或卡住时，优先看这里定位到哪个方向"
              />
              <div style={{ overflowX: "auto" }}>
                <table style={{ ...tableStyle, minWidth: 900 }}>
                  <thead>
                    <tr>
                      {["时间", "同事", "材料", "阶段", "方向", "结果"].map((label) => (
                        <th key={label} style={thStyle}>{label}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {recentJobEvents.slice(0, 12).map((event) => (
                      <ReviewJobEventRow
                        key={`${event.job_id}-${event.index}-${event.event}`}
                        event={event}
                      />
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}

          {activeDrafts.length > 0 && (
            <section style={{ ...cardStyle, marginBottom: 16 }}>
              <SectionHead
                title="进行中的草稿"
                hint="用于定位同事是否停在逐条确认或报告阶段；只展示阶段、条数和处理进度，不展示 PRD 正文"
              />
              <div style={{ display: "flex", flexDirection: "column" }}>
                {activeDrafts.slice(0, 8).map((draft, index) => (
                  <ReviewDraftRow
                    key={`${draft.reviewer}-${draft.ts}-${index}`}
                    draft={draft}
                  />
                ))}
              </div>
            </section>
          )}

          <section style={{ ...cardStyle, marginBottom: 16 }}>
            <SectionHead
              title="逐条确认反馈"
              hint="看同事接受、驳回或改写了哪些评审意见；这里只展示意见摘要，不展示 PRD 正文"
            />
            <div
              style={{
                display: "flex",
                flexWrap: "wrap",
                gap: 8,
                padding: "12px 16px",
                borderBottom: "1px solid var(--border-subtle)",
              }}
            >
              {FEEDBACK_ACTION_OPTIONS.map((option) => {
                const active = option.value === feedbackAction;
                return (
                  <button
                    key={option.value}
                    type="button"
                    onClick={() => setFeedbackAction(option.value)}
                    style={{
                      border: active
                        ? "1px solid var(--accent-600)"
                        : "1px solid var(--border-default)",
                      borderRadius: "var(--r-pill)",
                      background: active ? "var(--accent-50)" : "var(--surface-raised)",
                      color: active ? "var(--accent-700)" : "var(--text-muted)",
                      padding: "6px 11px",
                      fontSize: 12,
                      fontWeight: active ? 650 : 500,
                      cursor: "pointer",
                      fontFamily: "var(--font-sans)",
                    }}
                  >
                    {option.label}
                  </button>
                );
              })}
            </div>
            {feedbackSummary && (
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))",
                  gap: 10,
                  padding: 16,
                  borderBottom: "1px solid var(--border-subtle)",
                }}
              >
                <SmallStat label="已处理意见" value={feedbackSummary.total_items} />
                <SmallStat label="同事认可" value={feedbackSummary.accepted + feedbackSummary.edited} />
                <SmallStat label="同事驳回" value={feedbackSummary.rejected} />
                <SmallStat label="草稿中的反馈" value={feedbackData.draft_items ?? 0} />
                <SmallStat label="PM 补充线索" value={feedbackData.missing_reports ?? 0} />
                <SmallStat
                  label="认可率"
                  value={`${Math.round(feedbackSummary.accept_rate * 100)}%`}
                />
              </div>
            )}
            {feedbackData &&
              (feedbackData.by_reviewer.length > 0 ||
                feedbackData.by_workspace.length > 0) && (
                <div
                  style={{
                    display: "grid",
                    gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))",
                    gap: 12,
                    padding: "0 16px 16px",
                    borderBottom: "1px solid var(--border-subtle)",
                  }}
                >
                  <FeedbackBreakdown
                    title="按同事看"
                    rows={feedbackData.by_reviewer.slice(0, 5)}
                    labelOf={(row) => row.reviewer || "未署名"}
                  />
                  <FeedbackBreakdown
                    title="按资料库看"
                    rows={feedbackData.by_workspace.slice(0, 5)}
                    labelOf={(row) =>
                      row.workspace?.replace(/^workspace-/, "") || "未选资料库"
                    }
                  />
                </div>
              )}
            {feedbackApiError ? (
              <InlineEmpty text={feedbackApiError.detail ?? "逐条反馈读取失败。"} />
            ) : feedbackData?.records.length ? (
              <div style={{ overflowX: "auto" }}>
                <table style={{ ...tableStyle, minWidth: 940 }}>
                  <thead>
                    <tr>
                      {["时间", "同事", "处理", "原因", "意见摘要", "材料"].map((label) => (
                        <th key={label} style={thStyle}>{label}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {feedbackData.records.slice(0, 12).map((record) => (
                      <FeedbackRow
                        key={`${record.timestamp}-${record.reviewer}-${record.item_id}`}
                        record={record}
                      />
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <InlineEmpty text="还没有同事完成逐条确认；确认后这里会显示反馈分布。" />
            )}
          </section>

          {(feedbackData?.missing_records?.length ?? 0) > 0 && (
            <section style={{ ...cardStyle, marginBottom: 16 }}>
              <SectionHead
                title="PM 补充线索"
                hint="同事认为评审漏掉的问题；只展示线索摘要和位置，不展示 PRD 正文"
              />
              <div style={{ overflowX: "auto" }}>
                <table style={{ ...tableStyle, minWidth: 860 }}>
                  <thead>
                    <tr>
                      {["时间", "同事", "线索", "位置", "归类", "材料"].map((label) => (
                        <th key={label} style={thStyle}>{label}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {feedbackData?.missing_records?.slice(0, 10).map((record) => (
                      <MissingFeedbackRow
                        key={record.feedback_id || `${record.timestamp}-${record.reviewer}`}
                        record={record}
                      />
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
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
                        {action.reviewer || "未署名"} ·{" "}
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

function SmallStat({ label, value }: { label: string; value: string | number }) {
  return (
    <div
      style={{
        border: "1px solid var(--border-subtle)",
        borderRadius: "var(--r-3)",
        padding: "10px 12px",
        background: "var(--surface-raised)",
      }}
    >
      <div style={{ color: "var(--text-faint)", fontSize: 11, fontWeight: 600 }}>
        {label}
      </div>
      <div
        style={{
          marginTop: 4,
          color: "var(--text-strong)",
          fontSize: 18,
          fontWeight: 650,
          fontVariantNumeric: "tabular-nums",
        }}
      >
        {value}
      </div>
    </div>
  );
}

function FeedbackBreakdown({
  title,
  rows,
  labelOf,
}: {
  title: string;
  rows: FeedbackBucket[];
  labelOf: (row: FeedbackBucket) => string;
}) {
  return (
    <div
      style={{
        border: "1px solid var(--border-subtle)",
        borderRadius: "var(--r-3)",
        background: "var(--surface-raised)",
        overflow: "hidden",
      }}
    >
      <div
        style={{
          padding: "9px 11px",
          borderBottom: "1px solid var(--border-subtle)",
          color: "var(--text-strong)",
          fontSize: 12,
          fontWeight: 650,
        }}
      >
        {title}
      </div>
      {rows.length ? (
        rows.map((row) => (
          <div
            key={`${title}-${labelOf(row)}`}
            style={{
              display: "grid",
              gridTemplateColumns: "1fr auto",
              gap: 10,
              padding: "9px 11px",
              borderTop: "1px solid var(--border-subtle)",
              fontSize: 12,
            }}
          >
            <div style={{ minWidth: 0 }}>
              <div
                style={{
                  color: "var(--text-default)",
                  fontWeight: 600,
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                  whiteSpace: "nowrap",
                }}
              >
                {labelOf(row)}
              </div>
              <div style={{ color: "var(--text-faint)", marginTop: 2 }}>
                认可 {row.accepted + row.edited} · 驳回 {row.rejected}
              </div>
            </div>
            <div
              style={{
                color: "var(--text-strong)",
                fontWeight: 650,
                fontVariantNumeric: "tabular-nums",
              }}
            >
              {row.total_items}
            </div>
          </div>
        ))
      ) : (
        <InlineEmpty text="暂无数据。" />
      )}
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

function FeedbackRow({ record }: { record: FeedbackRecord }) {
  const tone = decisionTone(record.action);
  return (
    <tr>
      <td style={tdStyle}>{formatTime(record.ts)}</td>
      <td style={tdStyle}>{record.reviewer || "未署名"}</td>
      <td style={tdStyle}>
        <span
          style={{
            borderRadius: "var(--r-pill)",
            padding: "2px 8px",
            background: tone.bg,
            color: tone.fg,
            fontWeight: 650,
            fontSize: 11,
            whiteSpace: "nowrap",
          }}
        >
          {decisionLabel(record.action)}
        </span>
      </td>
      <td style={tdStyle}>
        <div>{rejectReasonLabel(record.reason_category)}</div>
        {record.reason_note && (
          <div style={{ color: "var(--text-faint)", marginTop: 3 }}>
            {record.reason_note}
          </div>
        )}
      </td>
      <td style={{ ...tdStyle, maxWidth: 360 }}>
        <div style={{ color: "var(--text-default)", fontWeight: 600 }}>
          {record.problem || "暂无摘要"}
        </div>
        <div style={{ color: "var(--text-muted)", marginTop: 4 }}>
          {dimensionLabel(record.dimension)}
          {record.location ? ` · ${record.location}` : ""}
        </div>
      </td>
      <td style={tdStyle}>
        <div>{record.prd_name || "未记录材料名"}</div>
        <div style={{ color: "var(--text-faint)", marginTop: 3 }}>
          {record.workspace?.replace(/^workspace-/, "") || "未选资料库"}
        </div>
      </td>
    </tr>
  );
}

function MissingFeedbackRow({ record }: { record: MissingFeedbackRecord }) {
  return (
    <tr>
      <td style={tdStyle}>{formatTime(record.ts)}</td>
      <td style={tdStyle}>{record.reviewer || "未署名"}</td>
      <td style={{ ...tdStyle, maxWidth: 360 }}>
        <div style={{ color: "var(--text-default)", fontWeight: 600 }}>
          {record.problem || "暂无摘要"}
        </div>
      </td>
      <td style={tdStyle}>{record.location || "未填写"}</td>
      <td style={tdStyle}>{birdRoleLabel(record.responsible_bird_id)}</td>
      <td style={tdStyle}>
        <div>{record.prd_name || "未记录材料名"}</div>
        <div style={{ color: "var(--text-faint)", marginTop: 3 }}>
          {record.workspace?.replace(/^workspace-/, "") || "未选资料库"}
        </div>
      </td>
    </tr>
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
          {run.reviewer || "未署名"} · {run.workspace?.replace(/^workspace-/, "") || "未选资料库"}
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

function ReviewJobRow({ job }: { job: ActiveReviewJob }) {
  const tone = statusTone(job.status === "done" ? "completed" : job.status);
  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "1fr 92px 120px",
        gap: 12,
        alignItems: "center",
        padding: "11px 16px",
        borderTop: "1px solid var(--border-subtle)",
        fontSize: 12,
      }}
    >
      <div>
        <div style={{ color: "var(--text-default)", fontWeight: 650 }}>
          {job.prd_name || "未命名材料"}
        </div>
        <div style={{ color: "var(--text-muted)", marginTop: 3 }}>
          {job.owner || "未署名"} · {job.workspace?.replace(/^workspace-/, "") || "未选资料库"}
        </div>
      </div>
      <span
        style={{
          justifySelf: "start",
          borderRadius: "var(--r-pill)",
          padding: "2px 8px",
          background: tone.bg,
          color: tone.fg,
          fontWeight: 650,
          fontSize: 11,
          whiteSpace: "nowrap",
        }}
      >
        {jobStatusLabel(job.status)}
      </span>
      <div style={{ color: "var(--text-muted)", textAlign: "right" }}>
        <div>{jobEventLabel(job.last_event)}</div>
        <div style={{ color: "var(--text-faint)", marginTop: 2 }}>
          {formatEpochTime(job.updated_at)}
        </div>
      </div>
    </div>
  );
}

function ReviewDraftRow({ draft }: { draft: ActiveReviewDraft }) {
  const processed =
    Number(draft.accepted ?? 0) +
    Number(draft.rejected ?? 0) +
    Number(draft.edited ?? 0);
  const runMeta = formatDraftRunMeta(draft);
  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "1fr 108px 128px",
        gap: 12,
        alignItems: "center",
        padding: "11px 16px",
        borderTop: "1px solid var(--border-subtle)",
        fontSize: 12,
      }}
    >
      <div>
        <div style={{ color: "var(--text-default)", fontWeight: 650 }}>
          {draft.prd_name || "未命名材料"}
        </div>
        <div style={{ color: "var(--text-muted)", marginTop: 3 }}>
          {draft.reviewer || "未署名"} · {draft.workspace?.replace(/^workspace-/, "") || "未选资料库"}
        </div>
      </div>
      <span
        style={{
          justifySelf: "start",
          borderRadius: "var(--r-pill)",
          padding: "2px 8px",
          background:
            draft.phase >= 3
              ? "var(--status-warn-bg)"
              : "var(--surface-muted)",
          color:
            draft.phase >= 3
              ? "var(--status-warn-fg)"
              : "var(--text-muted)",
          fontWeight: 650,
          fontSize: 11,
          whiteSpace: "nowrap",
        }}
      >
        {draft.phase_label || `第 ${draft.phase} 步`}
      </span>
      <div style={{ color: "var(--text-muted)", textAlign: "right" }}>
        <div>
          {processed}/{draft.items_count ?? 0} 条已处理
        </div>
        <div style={{ color: "var(--text-faint)", marginTop: 2 }}>
          {formatTime(draft.ts)}
        </div>
        {runMeta && (
          <div style={{ color: "var(--text-faint)", marginTop: 2 }}>
            {runMeta}
          </div>
        )}
      </div>
    </div>
  );
}

function formatDraftRunMeta(draft: ActiveReviewDraft): string {
  const parts: string[] = [];
  if (draft.duration_ms) {
    parts.push(`耗时 ${formatDuration(draft.duration_ms)}`);
  }
  if (draft.recovered_workers) {
    parts.push(`已恢复 ${draft.recovered_workers} 个方向`);
  }
  if (draft.failed_workers) {
    parts.push(`${draft.failed_workers} 个方向未完成`);
  }
  if (draft.context_packet_workers) {
    parts.push(`${draft.context_packet_workers} 个方向使用压缩视图`);
  }
  if (draft.orchestrator) {
    parts.push(draft.orchestrator === "langgraph" ? "可恢复编排" : draft.orchestrator);
  }
  return parts.join(" · ");
}

function ReviewJobEventRow({ event }: { event: AdminReviewJobEvent }) {
  const failed = event.success === false || ["error", "review_failed"].includes(event.event ?? "");
  const tone = failed
    ? { bg: "var(--status-failed-bg)", fg: "var(--status-failed-fg)" }
    : event.event === "result"
      ? { bg: "var(--status-done-bg)", fg: "var(--status-done-fg)" }
      : { bg: "var(--surface-muted)", fg: "var(--text-muted)" };
  const resultText = failed
    ? event.error || event.message || "需要排查"
    : typeof event.items_count === "number"
      ? `${event.items_count} 条意见`
      : typeof event.result_items_count === "number"
        ? `${event.result_items_count} 条意见`
        : jobEventLabel(event.event);
  const runtimeHint =
    typeof event.duration_ms === "number"
      ? `耗时 ${(event.duration_ms / 1000).toFixed(1)} 秒`
      : typeof event.prd_context_packet_chars === "number" &&
          event.prd_context_packet_chars > 0
        ? `已使用压缩视图 ${Math.round(event.prd_context_packet_chars / 1000)}k 字`
        : "";
  return (
    <tr>
      <td style={tdStyle}>{formatEpochTime(event.ts)}</td>
      <td style={tdStyle}>{event.owner || "未署名"}</td>
      <td style={tdStyle}>
        <div>{event.prd_name || "未命名材料"}</div>
        <div style={{ color: "var(--text-faint)", fontSize: 11, marginTop: 2 }}>
          {event.workspace?.replace(/^workspace-/, "") || "未选资料库"}
        </div>
      </td>
      <td style={tdStyle}>{jobEventLabel(event.event)}</td>
      <td style={tdStyle}>{dimensionLabel(event.dim_key)}</td>
      <td style={tdStyle}>
        <span
          style={{
            display: "inline-flex",
            maxWidth: 260,
            borderRadius: "var(--r-pill)",
            padding: "2px 8px",
            background: tone.bg,
            color: tone.fg,
            fontWeight: 650,
            fontSize: 11,
            whiteSpace: "normal",
          }}
        >
          {resultText}
        </span>
        {runtimeHint && (
          <div style={{ color: "var(--text-faint)", fontSize: 11, marginTop: 4 }}>
            {runtimeHint}
          </div>
        )}
      </td>
    </tr>
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

function formatEpochTime(ts?: number) {
  if (!ts) return "暂无";
  const date = new Date(ts * 1000);
  const month = `${date.getMonth() + 1}`.padStart(2, "0");
  const day = `${date.getDate()}`.padStart(2, "0");
  const hour = `${date.getHours()}`.padStart(2, "0");
  const minute = `${date.getMinutes()}`.padStart(2, "0");
  return `${month}-${day} ${hour}:${minute}`;
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

function jobStatusLabel(status?: string) {
  return {
    queued: "排队中",
    running: "评审中",
    done: "已完成",
    error: "异常",
    cancelled: "已取消",
  }[status ?? ""] ?? "未知";
}

function jobEventLabel(event?: string) {
  return {
    uploaded: "已接入材料",
    wiki_scanned: "资料库已读取",
    review_queued: "等待空闲评审位",
    workers_started: "评审已开始",
    worker_done: "有方向完成",
    final_reviewer_started: "正在收口",
    final_reviewer_done: "收口完成",
    result: "结果已生成",
    error: "遇到异常",
    review_failed: "评审失败",
  }[event ?? ""] ?? "等待更新";
}

function actionLabel(event?: string) {
  return {
    review_started: "开始评审",
    report_downloaded: "下载报告",
    wiki_saved: "存入资料库",
    feishu_pushed: "推送飞书",
    item_feedback: "标记意见",
  }[event ?? ""] ?? (event || "记录动作");
}

function decisionLabel(action?: string) {
  return {
    accept: "认可",
    reject: "驳回",
    edit: "改写后认可",
    unknown: "未确认",
  }[action ?? "unknown"] ?? "未确认";
}

function decisionTone(action?: string) {
  if (action === "reject") {
    return { bg: "var(--status-failed-bg)", fg: "var(--status-failed-fg)" };
  }
  if (action === "edit") {
    return { bg: "var(--status-warn-bg)", fg: "var(--status-warn-fg)" };
  }
  if (action === "accept") {
    return { bg: "var(--status-done-bg)", fg: "var(--status-done-fg)" };
  }
  return { bg: "var(--surface-raised)", fg: "var(--text-muted)" };
}

function rejectReasonLabel(reason?: string) {
  return {
    good_issue: "好问题",
    false_positive: "误报",
    known_tradeoff: "已知取舍",
    wiki_missing: "上下文不足",
    rule_too_strict: "规则过严",
    impl_detail: "实现细节",
    model_noise: "判断不准",
  }[reason ?? ""] ?? (reason ? reason : "未填写");
}

function dimensionLabel(dimension?: string) {
  return {
    structure: "业务完整性",
    quality: "使用体验",
    data_quality: "字段口径",
    risk: "实现风险",
    data: "字段口径",
  }[dimension ?? ""] ?? (dimension || "未标注方向");
}

function birdRoleLabel(id?: number | null) {
  return {
    1: "业务完整性",
    2: "字段口径",
    3: "使用体验",
    4: "实现风险",
    5: "复核",
  }[Number(id)] ?? "未归类";
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
