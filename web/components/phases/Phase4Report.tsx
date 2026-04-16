"use client";

/**
 * Phase 4 — 报告出口
 *
 * 3 条出口(都吃同一份客户端生成的 markdown):
 * 1. 下载 .md 文件(浏览器 Blob,不走后端)
 * 2. 保存到 workspace/wiki/ (POST /api/reports/{ws}/save-to-wiki)
 * 3. 推送飞书群(POST /api/feishu/send)
 *
 * readonly 用户:后两个按钮 disabled(并带提示),下载不受限。
 *
 * 页面顶部有一个报告预览(折叠),用户可以一眼看到"啄伤度"和决策汇总。
 */

import { useMemo, useState } from "react";
import {
  Download,
  Save,
  Send,
  ArrowLeft,
  RotateCcw,
  CheckCircle2,
  Loader2,
  Eye,
  EyeOff,
} from "lucide-react";
import { toast } from "sonner";
import { useMutation, useQuery } from "@tanstack/react-query";

import {
  authApi,
  reportsApi,
  feishuApi,
  draftsApi,
  auditApi,
  ApiError,
} from "@/lib/api";
import { useReviewStore } from "@/lib/store";
import { generateReportMarkdown, computeStats } from "@/lib/generateReport";

import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Separator } from "@/components/ui/separator";
import { ScrollArea } from "@/components/ui/scroll-area";

export function Phase4Report() {
  const reviewResult = useReviewStore((s) => s.reviewResult);
  const decisions = useReviewStore((s) => s.decisions);
  const workspace = useReviewStore((s) => s.workspace);
  const prdName = useReviewStore((s) => s.prdName);
  const reviewer = useReviewStore((s) => s.reviewer);
  const setPhase = useReviewStore((s) => s.setPhase);
  const resetReview = useReviewStore((s) => s.resetReview);

  const [showPreview, setShowPreview] = useState(false);

  // 拉 /api/me 判断是否 readonly
  const { data: me } = useQuery({
    queryKey: ["me"],
    queryFn: () => authApi.me(),
    retry: false,
    staleTime: 60 * 1000,
  });
  const isReadonly = me?.readonly ?? false;

  // ========== 生成报告 markdown + 统计 ==========
  const { markdown, stats } = useMemo(() => {
    if (!reviewResult) return { markdown: "", stats: null };
    return {
      markdown: generateReportMarkdown(reviewResult, decisions),
      stats: computeStats(reviewResult, decisions),
    };
  }, [reviewResult, decisions]);

  // ========== 下载 ==========
  const handleDownload = () => {
    if (!markdown) return;
    const safeName = (prdName || "PRD").replace(/\.[^.]+$/, "");
    const dateTag = new Date().toISOString().slice(0, 10);
    const filename = `评审报告-${safeName}-${dateTag}.md`;
    const blob = new Blob([markdown], { type: "text/markdown;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
    toast.success(`已下载 ${filename}`);
    // P0-4: 审计 downloaded_report
    void auditApi
      .log({
        event: "downloaded_report",
        workspace,
        prd_name: prdName || "未命名",
        extra: { filename },
      })
      .catch(() => {});
  };

  // ========== 保存到 wiki ==========
  const saveWikiMutation = useMutation({
    mutationFn: () => {
      if (!reviewResult || !stats) throw new Error("缺少评审结果");
      return reportsApi.saveToWiki(workspace, {
        prd_name: prdName || "未命名",
        report_markdown: markdown,
        items_count: stats.total,
        accepted_count: stats.accepted,
        rejected_count: stats.rejected,
        edited_count: stats.edited,
        peck_score: stats.peckScore,
        peck_label: stats.peckLabel,
      });
    },
    onSuccess: (resp) => {
      toast.success(`已保存到 wiki${resp.filename ? `: ${resp.filename}` : ""}`);
      // P0-4: 审计 saved_to_wiki
      void auditApi
        .log({
          event: "saved_to_wiki",
          workspace,
          prd_name: prdName || "未命名",
          extra: { filename: resp.filename ?? "" },
        })
        .catch(() => {});
    },
    onError: (e: ApiError) => {
      if (e.status === 403) {
        toast.error("只读用户不能保存 wiki");
      } else {
        toast.error(`保存失败: ${e.detail ?? e.message}`);
      }
    },
  });

  // ========== 飞书推送 ==========
  const feishuMutation = useMutation({
    mutationFn: () =>
      feishuApi.send({
        prd_name: prdName || "未命名",
        report_markdown: markdown,
      }),
    onSuccess: (resp) => {
      toast.success(`已推送到飞书${resp.msg_id ? ` (msg_id=${resp.msg_id.slice(0, 12)}...)` : ""}`);
      // P0-4: 审计 pushed_feishu
      void auditApi
        .log({
          event: "pushed_feishu",
          workspace,
          prd_name: prdName || "未命名",
          extra: { msg_id: resp.msg_id ?? "" },
        })
        .catch(() => {});
    },
    onError: (e: ApiError) => {
      if (e.status === 503) {
        toast.error("飞书未配置(需要 FEISHU_APP_ID/APP_SECRET/CHAT_ID)");
      } else if (e.status === 403) {
        toast.error("只读用户不能推送飞书");
      } else {
        toast.error(`推送失败: ${e.detail ?? e.message}`);
      }
    },
  });

  // ========== 重新开始 ==========
  const handleRestart = async () => {
    if (reviewer) {
      try {
        await draftsApi.delete(reviewer);
      } catch {
        // ignore
      }
    }
    resetReview();
  };

  // ========== 无结果 guard ==========
  if (!reviewResult || !stats) {
    return (
      <Alert variant="destructive">
        <AlertTitle>缺少评审结果</AlertTitle>
        <AlertDescription>
          没有找到评审数据,请返回重新开始。
          <Button
            size="sm"
            variant="outline"
            className="ml-3"
            onClick={handleRestart}
          >
            重新开始
          </Button>
        </AlertDescription>
      </Alert>
    );
  }

  return (
    <div className="space-y-4">
      {/* ========== 完成横幅 + 啄伤度 ========== */}
      <Card className="border-emerald-500/40 bg-emerald-50/50 dark:bg-emerald-950/20">
        <CardContent className="flex flex-wrap items-center gap-6 p-6">
          <CheckCircle2 className="h-10 w-10 text-emerald-600" />
          <div className="flex-1">
            <div className="text-lg font-semibold">评审完成</div>
            <div className="text-sm text-muted-foreground">
              {prdName || "未命名"} · 共 {stats.total} 条改进项
            </div>
          </div>
          <div className="text-right">
            <div className="text-xs text-muted-foreground">啄伤度</div>
            <div className="flex items-baseline gap-1">
              <span className="text-3xl font-bold tabular-nums">
                {stats.peckScore}
              </span>
              <span className="text-xs text-muted-foreground">/ 100</span>
            </div>
            <Badge variant="secondary" className="mt-1">
              {stats.peckLabel}
            </Badge>
          </div>
        </CardContent>
      </Card>

      {/* ========== CC advanced: telemetry 汇总 ========== */}
      {reviewResult?.telemetry && (
        <Card>
          <CardContent className="p-4">
            <div className="flex items-center gap-2 text-xs text-muted-foreground">
              <span className="font-mono uppercase tracking-wider">
                运行指标
              </span>
              <span className="h-px flex-1 bg-border" />
              {reviewResult.telemetry.total_duration_ms && (
                <span className="font-mono tabular-nums">
                  {(reviewResult.telemetry.total_duration_ms / 1000).toFixed(1)}s
                </span>
              )}
            </div>
            {reviewResult.telemetry.workers && (
              <div className="mt-2 flex flex-wrap gap-3">
                {Object.entries(
                  reviewResult.telemetry.workers as Record<
                    string,
                    Record<string, number>
                  >,
                ).map(([dim, metrics]) => (
                  <div
                    key={dim}
                    className="rounded-sm border bg-muted/30 px-2 py-1 text-[11px]"
                  >
                    <div className="font-medium text-foreground/80">{dim}</div>
                    <div className="mt-0.5 space-x-2 text-muted-foreground">
                      {metrics.duration_ms && (
                        <span>{(metrics.duration_ms / 1000).toFixed(0)}s</span>
                      )}
                      {metrics.tokens_in && (
                        <span>{(metrics.tokens_in / 1000).toFixed(1)}K in</span>
                      )}
                      {metrics.tokens_out && (
                        <span>
                          {(metrics.tokens_out / 1000).toFixed(1)}K out
                        </span>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* ========== CC-pattern: 成本归因(如果后端返回了 cost_breakdown) ========== */}
      {reviewResult?.cost_breakdown && (
        <Card>
          <CardContent className="p-4">
            <div className="flex items-center gap-2 text-xs text-muted-foreground">
              <span className="font-mono uppercase tracking-wider">
                成本归因
              </span>
              <span className="h-px flex-1 bg-border" />
              <span className="font-mono tabular-nums">
                $
                {Object.values(
                  reviewResult.cost_breakdown as Record<string, number>,
                )
                  .reduce((a: number, b: number) => a + b, 0)
                  .toFixed(3)}
              </span>
            </div>
            <div className="mt-2 flex flex-wrap gap-3">
              {Object.entries(
                reviewResult.cost_breakdown as Record<string, number>,
              ).map(([dim, cost]) => (
                <div
                  key={dim}
                  className="rounded-sm border bg-muted/30 px-2 py-1 text-[11px]"
                >
                  <span className="text-muted-foreground">{dim}</span>{" "}
                  <span className="font-mono tabular-nums">
                    ${(cost as number).toFixed(3)}
                  </span>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* ========== 3 条出口 ========== */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">报告出口</CardTitle>
          <CardDescription>
            下载本地副本 / 归档到 workspace wiki / 推送飞书群。三者都使用同一份报告内容。
          </CardDescription>
        </CardHeader>
        <CardContent className="grid gap-3 sm:grid-cols-3">
          {/* 下载 */}
          <ActionCard
            icon={<Download className="h-5 w-5" />}
            title="下载 .md"
            hint="浏览器本地保存,不走后端"
            onClick={handleDownload}
            loading={false}
            disabled={false}
          />

          {/* 保存 wiki */}
          <ActionCard
            icon={<Save className="h-5 w-5" />}
            title="保存到 wiki"
            hint={
              isReadonly
                ? "只读用户无权保存"
                : `${workspace.replace(/^workspace-/, "")}/wiki/`
            }
            onClick={() => saveWikiMutation.mutate()}
            loading={saveWikiMutation.isPending}
            disabled={isReadonly || saveWikiMutation.isPending}
          />

          {/* 飞书 */}
          <ActionCard
            icon={<Send className="h-5 w-5" />}
            title="推送飞书群"
            hint={isReadonly ? "只读用户无权推送" : "前 3500 字 + 卡片形式"}
            onClick={() => feishuMutation.mutate()}
            loading={feishuMutation.isPending}
            disabled={isReadonly || feishuMutation.isPending}
          />
        </CardContent>
      </Card>

      {/* ========== 预览折叠 ========== */}
      <Card>
        <CardHeader className="pb-3">
          <div className="flex items-center justify-between">
            <CardTitle className="text-base">报告预览</CardTitle>
            <Button
              size="sm"
              variant="ghost"
              onClick={() => setShowPreview((v) => !v)}
            >
              {showPreview ? (
                <>
                  <EyeOff className="mr-1 h-4 w-4" />
                  折叠
                </>
              ) : (
                <>
                  <Eye className="mr-1 h-4 w-4" />
                  展开
                </>
              )}
            </Button>
          </div>
          {!showPreview && (
            <CardDescription className="text-xs">
              {markdown.length} 字 · 展开查看完整 markdown
            </CardDescription>
          )}
        </CardHeader>
        {showPreview && (
          <CardContent>
            <ScrollArea className="h-96 rounded-md border bg-muted/20 p-4">
              <pre className="whitespace-pre-wrap font-mono text-xs leading-relaxed">
                {markdown}
              </pre>
            </ScrollArea>
          </CardContent>
        )}
      </Card>

      {/* ========== 底部操作 ========== */}
      <Separator />
      <div className="flex items-center justify-between">
        <Button variant="ghost" onClick={() => setPhase(3)}>
          <ArrowLeft className="mr-1 h-4 w-4" />
          返回确认
        </Button>
        <Button variant="outline" onClick={handleRestart}>
          <RotateCcw className="mr-1 h-4 w-4" />
          评审下一个
        </Button>
      </div>
    </div>
  );
}

// ============================================================
// 单个出口 Action Card
// ============================================================

function ActionCard({
  icon,
  title,
  hint,
  onClick,
  loading,
  disabled,
}: {
  icon: React.ReactNode;
  title: string;
  hint: string;
  onClick: () => void;
  loading: boolean;
  disabled: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className="group flex flex-col items-start gap-2 rounded-lg border bg-card p-4 text-left transition-colors hover:border-primary/60 hover:bg-primary/5 disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:bg-card"
    >
      <div className="flex items-center gap-2 text-foreground">
        {loading ? <Loader2 className="h-5 w-5 animate-spin" /> : icon}
        <span className="font-medium">{title}</span>
      </div>
      <span className="text-xs text-muted-foreground">{hint}</span>
    </button>
  );
}
