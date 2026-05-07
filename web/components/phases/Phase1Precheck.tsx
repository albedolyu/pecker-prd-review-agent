"use client";

/**
 * Phase 1 — 知识盲区预检
 *
 * 触发后端 /api/review/precheck(~15s 盲区分析),展示:
 * - 强相关 wiki 页(命中 ≥3 关键词)
 * - 弱相关 wiki 页(命中 ≥1)
 * - 知识盲区(系统识别 PRD 需要但 wiki 缺的主题)
 *
 * 关键职责: 把后端返回的 `wiki_pages` 完整内容映射存进 store,
 * Phase 2 的 /api/review/run 必须原样带回去(是后端契约的一部分)。
 *
 * UI 状态:
 * - loading (盲区分析中,转圈 15s)
 * - 成功展示 3 列结果
 * - 失败显示 retry
 */

import { useEffect, useRef } from "react";
import { useMutation } from "@tanstack/react-query";
import {
  Sparkles,
  BookOpen,
  BookMarked,
  HelpCircle,
  ArrowLeft,
  ArrowRight,
  RefreshCw,
  Loader2,
  AlertTriangle,
} from "lucide-react";
import { toast } from "sonner";

import { reviewApi, draftsApi, ApiError, type PrecheckResponse } from "@/lib/api";
import { useReviewStore } from "@/lib/store";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";

export function Phase1Precheck() {
  const reviewer = useReviewStore((s) => s.reviewer);
  const workspace = useReviewStore((s) => s.workspace);
  const prdContent = useReviewStore((s) => s.prdContent);
  const rawMaterials = useReviewStore((s) => s.rawMaterials);
  const userNotes = useReviewStore((s) => s.userNotes);
  const precheckResult = useReviewStore((s) => s.precheckResult);
  const wikiPages = useReviewStore((s) => s.wikiPages);
  const setPrecheckResult = useReviewStore((s) => s.setPrecheckResult);
  const setWikiPages = useReviewStore((s) => s.setWikiPages);
  const setUserInput = useReviewStore((s) => s.setUserInput);
  const setPhase = useReviewStore((s) => s.setPhase);
  const toDraftPayload = useReviewStore((s) => s.toDraftPayload);

  const mutation = useMutation({
    mutationFn: () =>
      reviewApi.precheck({
        workspace,
        prd_content: prdContent,
        raw_materials: rawMaterials,
      }),
    onSuccess: (data: PrecheckResponse) => {
      setPrecheckResult(data);
      setWikiPages({ ...data.wiki_pages });
      toast.success(
        `预检完成:强相关 ${data.strong.length} · 弱相关 ${data.weak.length} · 盲区 ${data.gaps.length}`,
      );
      // 预检是非交互步骤,完成后自动推进到 Phase 2,和 Phase 2 → Phase 3
      // 的自动推进保持一致。给 800ms 让用户看一眼 toast + 弱相关/盲区结果。
      setTimeout(() => setPhase(2), 800);
    },
    onError: (e: ApiError) => {
      toast.error(`预检失败: ${e.detail ?? e.message}`);
    },
  });

  // 自动跑一次预检(除非 store 里已经有结果 — 比如从 Phase 2 返回)
  const triggered = useRef(false);
  useEffect(() => {
    if (!precheckResult && !triggered.current && prdContent && workspace) {
      triggered.current = true;
      mutation.mutate();
    }
  }, [precheckResult, prdContent, workspace, mutation]);

  const handleBack = () => {
    setPhase(0);
  };

  const handleRetry = () => {
    triggered.current = true;
    mutation.mutate();
  };

  const handleNext = async () => {
    if (!precheckResult) {
      toast.warning("预检还没完成");
      return;
    }
    if (Object.keys(wikiPages).length === 0) {
      toast.warning("wiki 内容缺失,Phase 2 会收不到上下文");
    }
    // 先保存 draft(phase=2)
    try {
      if (reviewer) {
        await draftsApi.save(reviewer, { ...toDraftPayload(), phase: 2 });
      }
    } catch {
      // 非阻塞
    }
    setPhase(2);
  };

  const isLoading = mutation.isPending;
  const hasResult = !!precheckResult;

  return (
    <div className="space-y-4">
      {/* ========== 标题 + 上下文 ========== */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Sparkles className="h-5 w-5 text-muted-foreground" />
            知识盲区预检
          </CardTitle>
          <CardDescription>
            扫描 workspace 里的 wiki 页面,识别与本次 PRD 强 / 弱相关的页面,
            并标出知识盲区。下一步评审员会看到这些页面作为上下文。
          </CardDescription>
        </CardHeader>
      </Card>

      {/* ========== 加载态 ========== */}
      {isLoading && !hasResult && (
        <Alert>
          <Loader2 className="h-4 w-4 animate-spin" />
          <AlertTitle>正在预检...</AlertTitle>
          <AlertDescription>
            本地 wiki 扫描 + 盲区分析,大约 10-15 秒。期间请不要关闭页面。
          </AlertDescription>
        </Alert>
      )}

      {/* ========== 错误态 ========== */}
      {mutation.isError && !hasResult && (
        <Alert variant="destructive">
          <AlertTriangle className="h-4 w-4" />
          <AlertTitle>预检失败</AlertTitle>
          <AlertDescription className="space-y-2">
            <div className="text-xs">
              {(mutation.error as ApiError)?.detail ?? mutation.error?.message}
            </div>
            <Button size="sm" variant="outline" onClick={handleRetry}>
              <RefreshCw className="mr-1 h-3.5 w-3.5" />
              重试
            </Button>
          </AlertDescription>
        </Alert>
      )}

      {/* ========== 成功态 ========== */}
      {hasResult && precheckResult && (
        <div className="grid gap-4 md:grid-cols-3">
          {/* 强相关 */}
          <ResultColumn
            icon={<BookMarked className="h-4 w-4" />}
            title="强相关"
            hint="命中 ≥3 关键词"
            items={precheckResult.strong}
            emptyText="没有强相关 wiki 页"
            accent="primary"
          />
          {/* 弱相关 */}
          <ResultColumn
            icon={<BookOpen className="h-4 w-4" />}
            title="弱相关"
            hint="命中 ≥1 关键词"
            items={precheckResult.weak}
            emptyText="没有弱相关 wiki 页"
            accent="secondary"
          />
          {/* 知识盲区 */}
          <ResultColumn
            icon={<HelpCircle className="h-4 w-4" />}
            title="知识盲区"
            hint="系统识别的缺失主题"
            items={precheckResult.gaps}
            emptyText="无明显盲区"
            accent="warning"
          />
        </div>
      )}

      {/* ========== 用户补充说明 ========== */}
      {hasResult && (
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base">补充说明(可选)</CardTitle>
            <CardDescription className="text-xs">
              看完预检结果后,如果想提醒下一步的编辑关注某些点,写在这里。
              会和 PRD 一起送到 4 位编辑。
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Label htmlFor="notes-phase1" className="sr-only">
              补充说明
            </Label>
            <Textarea
              id="notes-phase1"
              placeholder="例:本次重点检查字段映射;忽略 UI 交互部分..."
              rows={3}
              value={userNotes}
              onChange={(e) => setUserInput({ userNotes: e.target.value })}
            />
          </CardContent>
        </Card>
      )}

      {/* ========== 底部按钮 ========== */}
      <Separator />
      <div className="flex items-center justify-between">
        <Button variant="ghost" onClick={handleBack}>
          <ArrowLeft className="mr-1 h-4 w-4" />
          返回
        </Button>
        {hasResult && (
          <Button variant="outline" size="sm" onClick={handleRetry}>
            <RefreshCw className="mr-1 h-3.5 w-3.5" />
            重新预检
          </Button>
        )}
        <Button onClick={handleNext} disabled={!hasResult || isLoading}>
          下一步:开始评审
          <ArrowRight className="ml-1 h-4 w-4" />
        </Button>
      </div>
    </div>
  );
}

// ============================================================
// 辅助:单列结果展示
// ============================================================

interface ResultColumnProps {
  icon: React.ReactNode;
  title: string;
  hint: string;
  items: ReadonlyArray<string>;
  emptyText: string;
  accent: "primary" | "secondary" | "warning";
}

function ResultColumn({
  icon,
  title,
  hint,
  items,
  emptyText,
  accent,
}: ResultColumnProps) {
  const accentCls =
    accent === "primary"
      ? "text-primary"
      : accent === "warning"
        ? "text-amber-600 dark:text-amber-400"
        : "text-muted-foreground";

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle
          className={`flex items-center justify-between text-sm ${accentCls}`}
        >
          <span className="flex items-center gap-1.5">
            {icon}
            {title}
          </span>
          <Badge variant="outline" className="font-mono">
            {items.length}
          </Badge>
        </CardTitle>
        <CardDescription className="text-xs">{hint}</CardDescription>
      </CardHeader>
      <CardContent>
        {items.length === 0 ? (
          <p className="text-xs text-muted-foreground">{emptyText}</p>
        ) : (
          <ul className="space-y-1.5 text-xs">
            {items.slice(0, 20).map((item, idx) => (
              <li
                key={idx}
                className="rounded-md bg-muted/50 px-2 py-1.5 leading-relaxed"
              >
                {item}
              </li>
            ))}
            {items.length > 20 && (
              <li className="text-muted-foreground">
                还有 {items.length - 20} 条省略
              </li>
            )}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
