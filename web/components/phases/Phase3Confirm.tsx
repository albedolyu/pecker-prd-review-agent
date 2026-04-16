"use client";

/**
 * Phase 3 — 逐条确认
 *
 * 展示 reviewResult.items,按 dimension 分 Tabs(责编/审校/技术编辑/数据核对员),
 * 每条可选: accept / reject / edit(带 textarea 改写 problem)。
 *
 * 底部统计: 已决 / 待决 / Accept / Reject / Edit 数量。
 * 全部决策后点"生成报告",POST /api/review/confirm 把原样 reviewResult + decisions
 * 回传,后端验证 HMAC signature 后生成报告。
 */

import { useMemo, useState } from "react";
import {
  ArrowLeft,
  ArrowRight,
  Check,
  X,
  Pencil,
  AlertTriangle,
  Loader2,
} from "lucide-react";
import { toast } from "sonner";
import { useMutation } from "@tanstack/react-query";

import { useReviewStore } from "@/lib/store";
import { ROLES, normalizeDimensionKey, type RoleKey } from "@/lib/roles";
import {
  reviewApi,
  ApiError,
  type ConfirmResponse,
  type ReviewItem,
  type ItemDecision,
} from "@/lib/api";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Separator } from "@/components/ui/separator";
import { cn } from "@/lib/utils";

export function Phase3Confirm() {
  const reviewResult = useReviewStore((s) => s.reviewResult);
  const decisions = useReviewStore((s) => s.decisions);
  const setDecision = useReviewStore((s) => s.setDecision);
  const setPhase = useReviewStore((s) => s.setPhase);

  // 归一化 item.dimension 到 RoleKey(后端可能写 "结构层" / "苍鹰补充" / "structure" 3 种)
  const itemsByDim = useMemo(() => {
    const map = new Map<RoleKey, ReviewItem[]>();
    if (!reviewResult) return map;
    for (const item of reviewResult.items) {
      const key = normalizeDimensionKey(item.dimension);
      const arr = map.get(key) ?? [];
      arr.push(item);
      map.set(key, arr);
    }
    return map;
  }, [reviewResult]);

  const activeDims = useMemo(
    () => Array.from(itemsByDim.keys()),
    [itemsByDim],
  );
  const [currentTab, setCurrentTab] = useState<RoleKey>(
    activeDims[0] ?? "structure",
  );

  const stats = useMemo(() => {
    const total = reviewResult?.items.length ?? 0;
    const decided = Object.keys(decisions).length;
    const counts = { accept: 0, reject: 0, edit: 0 };
    for (const d of Object.values(decisions)) {
      counts[d.action] = (counts[d.action] ?? 0) + 1;
    }
    return { total, decided, pending: total - decided, ...counts };
  }, [reviewResult, decisions]);

  // ========== 提交 ==========
  // 后端 /api/review/confirm 只做 signature verify + 计数,不生成文件。
  // 真正的 markdown 报告由 Phase 4 用 lib/generateReport.ts 前端合成。
  const confirmMutation = useMutation({
    mutationFn: () => {
      if (!reviewResult) throw new Error("缺少 reviewResult");
      return reviewApi.confirm({
        review_result: reviewResult,
        decisions: { ...decisions },
      });
    },
    onSuccess: (resp: ConfirmResponse) => {
      toast.success(
        `决策已确认:${resp.accepted} 接受 · ${resp.edited} 改写 · ${resp.rejected} 拒绝`,
      );
      setPhase(4);
    },
    onError: (e: ApiError) => {
      if (e.status === 403) {
        toast.error("签名验证失败 — 数据可能被篡改,请重新评审");
      } else {
        toast.error(`确认失败: ${e.detail ?? e.message}`);
      }
    },
  });

  // ========== 没有 reviewResult 的保护 ==========
  if (!reviewResult) {
    return (
      <Alert variant="destructive">
        <AlertTriangle className="h-4 w-4" />
        <AlertTitle>缺少评审结果</AlertTitle>
        <AlertDescription>
          没有找到上一步的评审结果,请返回重新评审。
          <Button
            size="sm"
            variant="outline"
            className="ml-3"
            onClick={() => setPhase(2)}
          >
            返回
          </Button>
        </AlertDescription>
      </Alert>
    );
  }

  return (
    <div className="space-y-4">
      {/* ========== 统计卡 ========== */}
      <Card>
        <CardContent className="flex flex-wrap items-center gap-x-6 gap-y-2 p-4">
          <div>
            <div className="text-xs text-muted-foreground">总计</div>
            <div className="text-xl font-semibold">{stats.total}</div>
          </div>
          <Separator orientation="vertical" className="h-10" />
          <StatPill label="待决" value={stats.pending} tone="muted" />
          <StatPill label="接受" value={stats.accept} tone="success" />
          <StatPill label="拒绝" value={stats.reject} tone="destructive" />
          <StatPill label="改写" value={stats.edit} tone="primary" />
          <div className="ml-auto text-xs text-muted-foreground">
            {reviewResult.items.length === 0
              ? "本次评审没有发现问题"
              : `已决 ${stats.decided} / ${stats.total}`}
          </div>
        </CardContent>
      </Card>

      {/* ========== 按职能分组的 Tabs ========== */}
      {reviewResult.items.length > 0 && (
        <Tabs
          value={currentTab}
          onValueChange={(v) => setCurrentTab((v ?? "structure") as RoleKey)}
        >
          <TabsList
            className="grid w-full gap-1"
            style={{
              gridTemplateColumns: `repeat(${Math.max(activeDims.length, 1)}, minmax(0, 1fr))`,
            }}
          >
            {activeDims.map((dim) => {
              const role = ROLES[dim];
              const count = itemsByDim.get(dim)?.length ?? 0;
              return (
                <TabsTrigger
                  key={dim}
                  value={dim}
                  className="flex items-center gap-1.5"
                >
                  <span>{role.label}</span>
                  <Badge variant="secondary" className="h-4 px-1 text-[10px]">
                    {count}
                  </Badge>
                </TabsTrigger>
              );
            })}
          </TabsList>

          {activeDims.map((dim) => {
            const role = ROLES[dim];
            const items = itemsByDim.get(dim) ?? [];
            return (
              <TabsContent key={dim} value={dim} className="mt-4 space-y-3">
                {items.map((item, idx) => (
                  <ItemCard
                    key={item.id ?? `${dim}-${idx}`}
                    item={item}
                    role={role}
                    decision={decisions[item.id] ?? null}
                    onChange={(d) => setDecision(item.id, d)}
                  />
                ))}
              </TabsContent>
            );
          })}
        </Tabs>
      )}

      {/* ========== 底部操作 ========== */}
      <Separator />
      <div className="flex items-center justify-between">
        <Button
          variant="ghost"
          onClick={() => setPhase(2)}
          disabled={confirmMutation.isPending}
        >
          <ArrowLeft className="mr-1 h-4 w-4" />
          返回
        </Button>
        <Button
          onClick={() => confirmMutation.mutate()}
          disabled={confirmMutation.isPending}
        >
          {confirmMutation.isPending ? (
            <>
              <Loader2 className="mr-1 h-4 w-4 animate-spin" />
              生成中...
            </>
          ) : (
            <>
              生成报告
              <ArrowRight className="ml-1 h-4 w-4" />
            </>
          )}
        </Button>
      </div>
    </div>
  );
}

// ============================================================
// 单条 Item 卡
// ============================================================

interface ItemCardProps {
  item: ReviewItem;
  role: (typeof ROLES)[RoleKey];
  decision: ItemDecision | null;
  onChange: (d: ItemDecision) => void;
}

function ItemCard({ item, role, decision, onChange }: ItemCardProps) {
  const action = decision?.action ?? null;

  return (
    <Card
      className={cn(
        "transition-colors",
        action === "accept" &&
          "border-emerald-500/50 bg-emerald-50/30 dark:bg-emerald-950/10",
        action === "reject" && "border-destructive/40 bg-destructive/5",
        action === "edit" && "border-primary/50 bg-primary/5",
      )}
    >
      <CardContent className="space-y-3 p-4">
        {/* 顶部: ID + severity + provenance + location */}
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <span className="font-mono text-muted-foreground">{item.id}</span>
          {item.severity && <SeverityBadge severity={item.severity} />}
          {/* Phase G #3 + #7: provenance badge */}
          <ProvenanceBadge
            provenance={item.provenance}
            citedByWorkers={item.cited_by_workers}
          />
          <span className="text-muted-foreground">· {role.label}</span>
          {item.location && (
            <span className="text-muted-foreground">· {item.location}</span>
          )}
          {typeof item.confidence === "number" && (
            <span className="ml-auto text-[10px] text-muted-foreground">
              置信度 {(item.confidence * 100).toFixed(0)}%
            </span>
          )}
        </div>

        {/* 问题 */}
        <div className="text-sm font-medium leading-snug">
          {item.problem ?? "(无描述)"}
        </div>

        {/* Evidence / Suggestion */}
        {item.evidence && (
          <div className="rounded-md bg-muted/50 px-3 py-2 text-xs leading-relaxed">
            <span className="font-medium text-muted-foreground">依据: </span>
            {item.evidence}
          </div>
        )}
        {item.suggestion && (
          <div className="rounded-md bg-primary/5 px-3 py-2 text-xs leading-relaxed">
            <span className="font-medium text-primary">建议: </span>
            {item.suggestion}
          </div>
        )}

        {/* Action buttons */}
        <div className="flex flex-wrap gap-1.5 pt-1">
          <ActionButton
            label="接受"
            icon={<Check className="h-3.5 w-3.5" />}
            active={action === "accept"}
            tone="success"
            onClick={() => onChange({ action: "accept" })}
          />
          <ActionButton
            label="拒绝"
            icon={<X className="h-3.5 w-3.5" />}
            active={action === "reject"}
            tone="destructive"
            onClick={() => onChange({ action: "reject" })}
          />
          <ActionButton
            label="改写"
            icon={<Pencil className="h-3.5 w-3.5" />}
            active={action === "edit"}
            tone="primary"
            onClick={() =>
              onChange({
                action: "edit",
                edited_problem: decision?.edited_problem ?? (item.problem ?? ""),
              })
            }
          />
        </div>

        {/* Edit textarea */}
        {action === "edit" && (
          <Textarea
            rows={3}
            value={decision?.edited_problem ?? ""}
            onChange={(e) =>
              onChange({
                action: "edit",
                edited_problem: e.target.value,
              })
            }
            placeholder="改写后的问题描述..."
            className="text-sm"
          />
        )}

        {/* Reject reason */}
        {action === "reject" && (
          <Textarea
            rows={2}
            value={decision?.reason ?? ""}
            onChange={(e) =>
              onChange({
                action: "reject",
                reason: e.target.value,
              })
            }
            placeholder="拒绝原因(可选)"
            className="text-sm"
          />
        )}
      </CardContent>
    </Card>
  );
}

function SeverityBadge({ severity }: { severity: string }) {
  const tone =
    severity === "must"
      ? "bg-destructive/15 text-destructive"
      : severity === "should"
        ? "bg-amber-500/15 text-amber-700 dark:text-amber-400"
        : "bg-muted text-muted-foreground";
  const label =
    severity === "must"
      ? "必须"
      : severity === "should"
        ? "建议"
        : severity === "suggest"
          ? "参考"
          : severity;
  return (
    <span
      className={cn(
        "inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-medium",
        tone,
      )}
    >
      {label}
    </span>
  );
}

/**
 * Phase G #3 + #7: ProvenanceBadge
 *
 * 按这条改进项的来源在 ID 旁边显示一个小章:
 * - worker (默认)         : 不显示(原生输出无需特殊标注)
 * - meta_added            : 红色"补遗"小章,代表苍鹰发现的漏报
 * - meta_dedup_kept       : 灰色"裁定"小章,代表苍鹰判定的去重赢家
 * - cited_by_workers ≥ 2  : ★ 共识星,N 个 worker 同时指证
 */
function ProvenanceBadge({
  provenance,
  citedByWorkers,
}: {
  provenance?: string;
  citedByWorkers?: ReadonlyArray<string>;
}) {
  // 共识 boost 优先(更强的信号)
  const consensus = (citedByWorkers?.length ?? 0) >= 2;
  if (consensus) {
    return (
      <span
        className="inline-flex items-center gap-0.5 rounded border border-amber-500/40 bg-amber-500/10 px-1.5 py-0.5 text-[10px] font-medium text-amber-700 dark:text-amber-400"
        title={`${citedByWorkers?.length} 位编辑同时指出: ${citedByWorkers?.join(" / ")}`}
      >
        ★ 共识 {citedByWorkers?.length}
      </span>
    );
  }
  if (provenance === "meta_added") {
    return (
      <span
        className="inline-flex items-center rounded border border-pecker-red/40 bg-pecker-red/10 px-1.5 py-0.5 text-[10px] font-medium italic text-pecker-red/85"
        title="苍鹰交叉校验时发现的漏报,worker 都没看到"
      >
        ✱ 苍鹰补遗
      </span>
    );
  }
  if (provenance === "meta_dedup_kept") {
    return (
      <span
        className="inline-flex items-center rounded border border-foreground/30 bg-foreground/5 px-1.5 py-0.5 text-[10px] font-medium text-foreground/65"
        title="苍鹰判定保留的去重赢家"
      >
        ⚖ 终审保留
      </span>
    );
  }
  // worker 原生输出,不加 badge,保持卡片整洁
  return null;
}

function ActionButton({
  label,
  icon,
  active,
  tone,
  onClick,
}: {
  label: string;
  icon: React.ReactNode;
  active: boolean;
  tone: "success" | "destructive" | "primary";
  onClick: () => void;
}) {
  const activeCls =
    tone === "success"
      ? "bg-emerald-600 text-white hover:bg-emerald-600/90"
      : tone === "destructive"
        ? "bg-destructive text-destructive-foreground hover:bg-destructive/90"
        : "bg-primary text-primary-foreground hover:bg-primary/90";
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "inline-flex items-center gap-1 rounded-md border px-2.5 py-1 text-xs font-medium transition-colors",
        active ? activeCls : "border-border bg-background hover:bg-muted",
      )}
    >
      {icon}
      {label}
    </button>
  );
}

function StatPill({
  label,
  value,
  tone,
}: {
  label: string;
  value: number;
  tone: "muted" | "success" | "destructive" | "primary";
}) {
  const cls =
    tone === "success"
      ? "text-emerald-700 dark:text-emerald-400"
      : tone === "destructive"
        ? "text-destructive"
        : tone === "primary"
          ? "text-primary"
          : "text-muted-foreground";
  return (
    <div>
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className={cn("text-xl font-semibold tabular-nums", cls)}>
        {value}
      </div>
    </div>
  );
}
