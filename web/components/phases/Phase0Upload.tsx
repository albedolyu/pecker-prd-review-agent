"use client";

/**
 * Phase 0 — PRD 上传 + 基础参数
 *
 * 元素:
 * - 草稿恢复 Banner(如果后端 GET /api/drafts/{reviewer} 命中)
 * - 拖拽 / 点选上传 .md .txt PRD 文件
 * - workspace Select(从 /api/workspaces 拉)
 * - 评审模式 Tabs(fast / strict)
 * - 评审人补充说明 Textarea
 * - "下一步 → 预检" 按钮(PRD + workspace 就绪才能点)
 *
 * 下一步会保存 draft phase=1 并 setPhase(1),让 review/page.tsx 切换到 Phase1Precheck。
 */

import { useCallback, useState, type ChangeEvent, type DragEvent } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { FileText, Upload, RotateCcw, X, ArrowRight, Info } from "lucide-react";
import { toast } from "sonner";

import {
  workspacesApi,
  draftsApi,
  ApiError,
  type Draft,
  type ReviewMode,
} from "@/lib/api";
import { useReviewStore } from "@/lib/store";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

const MAX_PRD_BYTES = 2 * 1024 * 1024; // 2 MB

export function Phase0Upload() {
  const queryClient = useQueryClient();

  // ========== store 状态 ==========
  const reviewer = useReviewStore((s) => s.reviewer);
  const prdName = useReviewStore((s) => s.prdName);
  const prdContent = useReviewStore((s) => s.prdContent);
  const workspace = useReviewStore((s) => s.workspace);
  const mode = useReviewStore((s) => s.mode);
  const userNotes = useReviewStore((s) => s.userNotes);
  const setUserInput = useReviewStore((s) => s.setUserInput);
  const setPhase = useReviewStore((s) => s.setPhase);
  const hydrateFromDraft = useReviewStore((s) => s.hydrateFromDraft);
  const toDraftPayload = useReviewStore((s) => s.toDraftPayload);

  const [dragOver, setDragOver] = useState(false);
  const [dismissedDraft, setDismissedDraft] = useState(false);

  // ========== workspace 列表 ==========
  const { data: workspaces, isLoading: wsLoading } = useQuery({
    queryKey: ["workspaces"],
    queryFn: () => workspacesApi.list(),
    staleTime: 5 * 60 * 1000,
  });

  // ========== 草稿检查 ==========
  const { data: draft } = useQuery<Draft | null>({
    queryKey: ["draft", reviewer],
    queryFn: async () => {
      if (!reviewer) return null;
      try {
        return await draftsApi.get(reviewer);
      } catch (e) {
        const err = e as ApiError;
        if (err.status === 404) return null;
        throw e;
      }
    },
    enabled: !!reviewer,
    retry: false,
    staleTime: 10 * 1000,
  });

  const hasDraft = !!draft && !dismissedDraft;

  // ========== 文件处理 ==========
  const handleFile = useCallback(
    async (file: File) => {
      if (file.size > MAX_PRD_BYTES) {
        toast.error(`文件过大: ${(file.size / 1024 / 1024).toFixed(1)} MB,上限 2 MB`);
        return;
      }
      const lower = file.name.toLowerCase();
      if (!lower.endsWith(".md") && !lower.endsWith(".txt") && !lower.endsWith(".markdown")) {
        toast.warning("建议使用 .md 或 .txt,其他格式可能解析异常");
      }
      try {
        const content = await file.text();
        setUserInput({ prdName: file.name, prdContent: content });
        toast.success(`已读取 ${file.name} (${content.length} 字)`);
      } catch {
        toast.error("文件读取失败");
      }
    },
    [setUserInput],
  );

  const onPickFile = (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) handleFile(file);
  };

  const onDrop = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setDragOver(false);
    const file = e.dataTransfer.files[0];
    if (file) handleFile(file);
  };

  // ========== 草稿恢复 ==========
  const handleResume = () => {
    if (!draft) return;
    hydrateFromDraft(draft);
    toast.success(`已恢复草稿 — Phase ${draft.phase}`);
    // hydrate 会把 phase 写成草稿里的 phase,review/page.tsx 自动切换
  };

  const handleDiscardDraft = async () => {
    if (!reviewer) return;
    try {
      await draftsApi.delete(reviewer);
      queryClient.setQueryData(["draft", reviewer], null);
      setDismissedDraft(true);
      toast.success("草稿已清除");
    } catch (e) {
      const err = e as ApiError;
      toast.error(`清除失败: ${err.detail ?? err.message}`);
    }
  };

  // ========== 下一步 ==========
  const canProceed = prdContent.length > 0 && workspace.length > 0;

  const handleNext = async () => {
    if (!canProceed || !reviewer) return;
    try {
      // 先保存 draft(phase=1),浏览器挂了也能回到预检页
      await draftsApi.save(reviewer, { ...toDraftPayload(), phase: 1 });
    } catch {
      // 草稿保存失败不阻塞前进
    }
    setPhase(1);
  };

  return (
    <div className="space-y-4">
      {/* ========== 草稿恢复 Banner ========== */}
      {hasDraft && draft && (
        <Alert className="border-primary/30 bg-primary/5">
          <RotateCcw className="h-4 w-4" />
          <AlertTitle className="flex items-center gap-2">
            发现未完成的评审草稿
            <Badge variant="outline">Phase {draft.phase}</Badge>
          </AlertTitle>
          <AlertDescription className="space-y-2">
            <div className="text-sm">
              <span className="font-medium">{draft.prd_name || "未命名"}</span>
              {draft.workspace && (
                <span className="ml-2 text-muted-foreground">
                  · {draft.workspace.replace(/^workspace-/, "")}
                </span>
              )}
              <span className="ml-2 text-muted-foreground">· {formatTs(draft.ts)}</span>
            </div>
            <div className="flex gap-2 pt-1">
              <Button size="sm" onClick={handleResume}>
                恢复
              </Button>
              <Button size="sm" variant="outline" onClick={handleDiscardDraft}>
                <X className="mr-1 h-3.5 w-3.5" />
                丢弃
              </Button>
            </div>
          </AlertDescription>
        </Alert>
      )}

      {/* ========== 上传区 ========== */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <FileText className="h-5 w-5 text-muted-foreground" />
            PRD 原文
          </CardTitle>
          <CardDescription>
            支持 .md / .txt / .markdown,大小 ≤ 2MB。也可直接粘贴内容到文本框。
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          {/* 拖拽 / 点选区 */}
          <div
            onDragOver={(e) => {
              e.preventDefault();
              setDragOver(true);
            }}
            onDragLeave={() => setDragOver(false)}
            onDrop={onDrop}
            className={cn(
              "flex flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed px-6 py-8 transition-colors",
              dragOver
                ? "border-primary bg-primary/5"
                : "border-border bg-muted/20 hover:border-primary/40",
            )}
          >
            <Upload className="h-6 w-6 text-muted-foreground" />
            <p className="text-sm text-muted-foreground">
              拖入文件 <span className="text-xs">或</span>
            </p>
            <label className="cursor-pointer">
              <input
                type="file"
                accept=".md,.txt,.markdown"
                className="hidden"
                onChange={onPickFile}
              />
              <span className="inline-flex items-center rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground hover:bg-primary/90">
                选择文件
              </span>
            </label>
            {prdName && (
              <p className="mt-1 text-xs text-foreground">
                已选: <span className="font-medium">{prdName}</span>
                {" · "}
                {prdContent.length} 字
              </p>
            )}
          </div>

          {/* 粘贴回退 */}
          <div className="space-y-1.5">
            <Label htmlFor="prd-paste" className="text-xs text-muted-foreground">
              或手工粘贴
            </Label>
            <Textarea
              id="prd-paste"
              placeholder="# PRD 标题..."
              rows={8}
              value={prdContent}
              onChange={(e) => {
                setUserInput({ prdContent: e.target.value });
                if (!prdName && e.target.value) {
                  setUserInput({ prdName: "粘贴内容.md" });
                }
              }}
              className="font-mono text-xs"
            />
          </div>
        </CardContent>
      </Card>

      {/* ========== 参数区 ========== */}
      <Card>
        <CardHeader>
          <CardTitle>评审参数</CardTitle>
          <CardDescription>
            workspace 决定 wiki 检索范围和报告输出目录,模式影响严格度。
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-5">
          {/* Workspace */}
          <div className="space-y-1.5">
            <Label htmlFor="ws">Workspace</Label>
            <Select
              value={workspace}
              onValueChange={(v) => setUserInput({ workspace: v ?? "" })}
              disabled={wsLoading}
            >
              <SelectTrigger id="ws" className="w-full">
                <SelectValue
                  placeholder={wsLoading ? "加载中..." : "选择一个 workspace"}
                />
              </SelectTrigger>
              <SelectContent>
                {(workspaces ?? []).map((w) => (
                  <SelectItem key={w.name} value={w.name}>
                    <span className="mr-2 font-medium">{w.display_name}</span>
                    <span className="text-xs text-muted-foreground">
                      wiki {w.wiki_page_count} · PRD {w.prd_count}
                    </span>
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {/* Mode */}
          <div className="space-y-1.5">
            <Label>评审模式</Label>
            <Tabs
              value={mode}
              onValueChange={(v) => setUserInput({ mode: v as ReviewMode })}
            >
              <TabsList className="grid w-full max-w-sm grid-cols-2">
                <TabsTrigger value="quick">快速</TabsTrigger>
                <TabsTrigger value="standard">严格(默认)</TabsTrigger>
              </TabsList>
            </Tabs>
            <p className="text-xs text-muted-foreground">
              {mode === "quick"
                ? "快速 = 全 sonnet 走一遍,~45 秒,跳过终审。适合初稿粗检。"
                : "严格 = 4 位编辑并行 + 终审交叉校验,~90-150 秒。默认推荐。"}
            </p>
          </div>

          {/* User notes */}
          <div className="space-y-1.5">
            <Label htmlFor="notes">补充说明(可选)</Label>
            <Textarea
              id="notes"
              placeholder="例:本次重点检查字段映射;忽略 UI 交互部分..."
              rows={3}
              value={userNotes}
              onChange={(e) => setUserInput({ userNotes: e.target.value })}
            />
          </div>
        </CardContent>
      </Card>

      {/* ========== 下一步 ========== */}
      <div className="flex items-center justify-between rounded-lg border bg-card px-4 py-3">
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <Info className="h-3.5 w-3.5" />
          下一步会把 PRD 送去"预检":扫 wiki 找相关页、识别评审模式。
        </div>
        <Button onClick={handleNext} disabled={!canProceed}>
          下一步:预检
          <ArrowRight className="ml-1 h-4 w-4" />
        </Button>
      </div>
    </div>
  );
}

function formatTs(ts: string): string {
  // "2026-04-15T16:52:17" → "04-15 16:52"
  const match = ts.match(/^\d{4}-(\d{2}-\d{2})T(\d{2}:\d{2})/);
  return match ? `${match[1]} ${match[2]}` : ts;
}
