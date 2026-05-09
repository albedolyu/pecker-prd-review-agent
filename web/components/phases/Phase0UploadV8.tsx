"use client";

/**
 * Phase 0 · v8 · PRD 上传 + 基础参数(工作台气质)
 *
 * 数据契约和 v7 Phase0Upload 保持一致(store + api 零改动),
 * 只换 UI 层:
 * - 去 hero 插画 / 刊头叙事 / 杂志 serif
 * - 单列紧凑表单,像飞书文档新建 / Linear New Issue
 * - 草稿恢复变成顶部一条 banner(accent 色细线)
 * - 保留 workspace select / 拖拽上传 / 粘贴 fallback / 模式卡 / 备注 / 下一步
 */

import {
  useCallback,
  useState,
  type ChangeEvent,
  type DragEvent,
} from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import {
  workspacesApi,
  draftsApi,
  ApiError,
  type Draft,
  type ReviewMode,
} from "@/lib/api";
import { useReviewStore } from "@/lib/store";
import {
  estimateReviewEtaHint,
  estimateReviewEtaLabel,
} from "@/lib/review-eta";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

const MAX_PRD_BYTES = 2 * 1024 * 1024;

export function Phase0UploadV8() {
  const queryClient = useQueryClient();

  const reviewer = useReviewStore((s) => s.reviewer);
  const prdName = useReviewStore((s) => s.prdName);
  const prdContent = useReviewStore((s) => s.prdContent);
  const rawMaterials = useReviewStore((s) => s.rawMaterials);
  const workspace = useReviewStore((s) => s.workspace);
  const mode = useReviewStore((s) => s.mode);
  const userNotes = useReviewStore((s) => s.userNotes);
  const setUserInput = useReviewStore((s) => s.setUserInput);
  const setPhase = useReviewStore((s) => s.setPhase);
  const hydrateFromDraft = useReviewStore((s) => s.hydrateFromDraft);
  const toDraftPayload = useReviewStore((s) => s.toDraftPayload);

  const [dragOver, setDragOver] = useState(false);
  const [dismissedDraft, setDismissedDraft] = useState(false);
  const [customWorkspaceMode, setCustomWorkspaceMode] = useState(false);
  const [previousWorkspace, setPreviousWorkspace] = useState("");

  const { data: workspaces, isLoading: wsLoading } = useQuery({
    queryKey: ["workspaces"],
    queryFn: () => workspacesApi.list(),
    staleTime: 5 * 60 * 1000,
  });

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
  const workspaceInList = (workspaces ?? []).some((w) => w.name === workspace);
  const showCustomWorkspaceInput = customWorkspaceMode || !workspace;
  const selectedWorkspacePageCount =
    (workspaces ?? []).find((w) => w.name === workspace)?.wiki_page_count ?? 0;
  const etaInput = {
    mode,
    prdContent,
    rawMaterials,
    wikiPageCount: selectedWorkspacePageCount,
  };
  const reviewEtaLabel = estimateReviewEtaLabel(etaInput);
  const reviewEtaHint = estimateReviewEtaHint(etaInput);

  const handleSelectWorkspace = (value: string | null) => {
    setPreviousWorkspace(value ?? "");
    setCustomWorkspaceMode(false);
    setUserInput({ workspace: value ?? "" });
  };

  const handleUseCustomWorkspace = () => {
    if (workspace) setPreviousWorkspace(workspace);
    setCustomWorkspaceMode(true);
    setUserInput({ workspace: "" });
  };

  const handleRestoreSelectedWorkspace = () => {
    if (!previousWorkspace) return;
    setCustomWorkspaceMode(false);
    setUserInput({ workspace: previousWorkspace });
  };

  const handleFile = useCallback(
    async (file: File) => {
      if (file.size > MAX_PRD_BYTES) {
        toast.error(
          `文件过大: ${(file.size / 1024 / 1024).toFixed(1)} MB,上限 2 MB`,
        );
        return;
      }
      const lower = file.name.toLowerCase();
      if (
        !lower.endsWith(".md") &&
        !lower.endsWith(".txt") &&
        !lower.endsWith(".markdown")
      ) {
        toast.warning("建议使用 .md 或 .txt");
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

  const handleResume = () => {
    if (!draft) return;
    hydrateFromDraft(draft);
    toast.success(`已恢复上次评审 — 进度: ${phaseLabel(draft.phase)}`);
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

  const canProceed = prdContent.length > 0 && workspace.length > 0;

  const handleNext = async () => {
    if (!canProceed || !reviewer) return;
    try {
      await draftsApi.save(reviewer, { ...toDraftPayload(), phase: 1 });
    } catch {
      /* 非阻塞 */
    }
    setPhase(1);
  };

  return (
    <div
      style={{
        maxWidth: 680,
        margin: "0 auto",
        padding: "32px 24px 80px",
        fontFamily: "var(--font-sans)",
      }}
    >
      {/* ── 页面标题区 ── */}
      <header
        style={{
          marginBottom: 28,
          display: "flex",
          alignItems: "baseline",
          justifyContent: "space-between",
          gap: 12,
          flexWrap: "wrap",
        }}
      >
        <div>
          <h1
            style={{
              fontSize: 22,
              fontWeight: 600,
              color: "var(--text-strong)",
              margin: 0,
              letterSpacing: "-0.015em",
            }}
          >
            新建一次 PRD 评审
          </h1>
          <p
            style={{
              fontSize: 13,
              color: "var(--text-muted)",
              marginTop: 4,
            }}
          >
            上传 PRD,选资料库与评审模式。{mode === "quick" ? "轻评审" : "深评审"}
            {reviewEtaLabel}，{reviewEtaHint}
          </p>
        </div>
        <a
          href="/runs/diff"
          style={{
            fontSize: 12,
            color: "var(--text-muted)",
            textDecoration: "none",
            padding: "4px 10px",
            border: "1px solid var(--border-default)",
            borderRadius: "var(--r-pill)",
          }}
        >
          查看历史评审
        </a>
      </header>

      {/* ── 草稿恢复 banner ── */}
      {hasDraft && draft && <DraftBanner draft={draft} onResume={handleResume} onDiscard={handleDiscardDraft} />}

      {/* ── 表单单列 ── */}
      <div style={{ display: "flex", flexDirection: "column", gap: 24 }}>
        {/* 资料库 */}
        <Field
          label="资料库"
          hint="选择和这份 PRD 最相关的资料库,用于补充业务背景和既有规则"
        >
          <Select
            value={customWorkspaceMode || !workspaceInList ? "" : workspace}
            onValueChange={handleSelectWorkspace}
            disabled={wsLoading}
          >
            <SelectTrigger
              style={{
                width: "100%",
                height: 36,
                border: "1px solid var(--border-default)",
                borderRadius: "var(--r-3)",
                background: "var(--surface-raised)",
                padding: "0 12px",
                fontSize: 13,
                color: "var(--text-default)",
                fontFamily: "var(--font-sans)",
              }}
            >
              <SelectValue placeholder={wsLoading ? "加载中…" : "选一个资料库"} />
            </SelectTrigger>
            <SelectContent>
              {(workspaces ?? []).map((w) => (
                <SelectItem key={w.name} value={w.name}>
                  <span style={{ marginRight: 8, fontWeight: 500 }}>{w.display_name}</span>
                  <span style={{ fontSize: 11, color: "var(--text-muted)" }}>
                    资料 {w.wiki_page_count} 页 · PRD {w.prd_count} 份
                  </span>
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          {workspace && !customWorkspaceMode && (
            <div
              style={{
                marginTop: 8,
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                gap: 10,
                border: "1px solid var(--border-subtle)",
                borderRadius: "var(--r-3)",
                background: "var(--surface-sunken)",
                padding: "7px 10px",
              }}
            >
              <span style={{ fontSize: 12, color: "var(--text-muted)" }}>
                当前资料库：
                <strong style={{ color: "var(--text-default)", fontWeight: 600 }}>
                  {workspace.replace(/^workspace-/, "")}
                </strong>
              </span>
              <button
                type="button"
                onClick={handleUseCustomWorkspace}
                style={{
                  border: 0,
                  background: "transparent",
                  color: "var(--accent-600)",
                  fontSize: 12,
                  fontWeight: 600,
                  cursor: "pointer",
                  fontFamily: "var(--font-sans)",
                  padding: 0,
                  whiteSpace: "nowrap",
                }}
              >
                改为新资料库
              </button>
            </div>
          )}
          {showCustomWorkspaceInput && (
            <div style={{ marginTop: 8 }}>
              <input
                placeholder="输入新资料库名,如 对外投资 / 风险评估"
                value={customWorkspaceMode ? workspace : ""}
                style={{
                  width: "100%",
                  height: 32,
                  border: "1px dashed var(--border-default)",
                  borderRadius: "var(--r-3)",
                  background: "transparent",
                  padding: "0 10px",
                  fontFamily: "var(--font-mono)",
                  fontSize: 12,
                  color: "var(--text-muted)",
                  outline: "none",
                }}
                onFocus={() => setCustomWorkspaceMode(true)}
                onChange={(e) => {
                  const v = e.target.value.trim();
                  setCustomWorkspaceMode(true);
                  setUserInput({ workspace: v });
                }}
              />
              <div
                style={{
                  marginTop: 6,
                  display: "flex",
                  justifyContent: "space-between",
                  gap: 8,
                  fontSize: 12,
                  color: "var(--text-faint)",
                }}
              >
                <span>也可以新建资料库,后续报告会归到这个名称下。</span>
                {previousWorkspace && customWorkspaceMode && (
                  <button
                    type="button"
                    onClick={handleRestoreSelectedWorkspace}
                    style={{
                      border: 0,
                      background: "transparent",
                      color: "var(--accent-600)",
                      fontSize: 12,
                      fontWeight: 600,
                      cursor: "pointer",
                      fontFamily: "var(--font-sans)",
                      padding: 0,
                      whiteSpace: "nowrap",
                    }}
                  >
                    继续使用这个资料库
                  </button>
                )}
              </div>
            </div>
          )}
        </Field>

        {/* 评审模式 */}
        <Field label="评审模式" hint="轻评审适合日常自查,深评审适合发给研发前">
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
            <ModeCardV8
              active={mode === "quick"}
              name="轻评审"
              eta={estimateReviewEtaLabel({ ...etaInput, mode: "quick" })}
              desc="日常自查 · 更快发现明显缺口 · 适合初稿"
              onClick={() => setUserInput({ mode: "quick" as ReviewMode })}
            />
            <ModeCardV8
              active={mode === "standard"}
              name="深评审"
              eta={estimateReviewEtaLabel({ ...etaInput, mode: "standard" })}
              desc="提交前检查 · 覆盖四个方向 · 适合发给同事前"
              onClick={() => setUserInput({ mode: "standard" as ReviewMode })}
            />
          </div>
        </Field>

        {/* PRD 上传 */}
        <Field label="PRD 正文" hint="拖进来 / 点击选 / 粘贴都行 · 上限 2 MB">
          <div
            onDragEnter={(e) => {
              // 用 dragenter 比 dragover 触发更早(光标一进入就响应,
              // 不用等到第一帧 dragover 触发),鸟切换到"接住"姿态更敏锐
              e.preventDefault();
              setDragOver(true);
            }}
            onDragOver={(e) => {
              e.preventDefault();
              if (!dragOver) setDragOver(true);
            }}
            onDragLeave={(e) => {
              // 必须判 relatedTarget 是否还在区域内,否则 children 跨边界会闪烁
              const related = e.relatedTarget as Node | null;
              if (!related || !e.currentTarget.contains(related)) {
                setDragOver(false);
              }
            }}
            onDrop={onDrop}
            onClick={() => {
              const el = document.getElementById("prd-file-input-v8") as HTMLInputElement | null;
              el?.click();
            }}
            style={{
              position: "relative",
              cursor: "pointer",
              borderRadius: "var(--r-4)",
              border: `1px dashed ${dragOver ? "var(--accent-500)" : "var(--border-default)"}`,
              background: dragOver ? "var(--accent-50)" : "var(--surface-sunken)",
              padding: "28px 20px",
              textAlign: "center",
              transition: "all var(--dur-base) var(--ease-out)",
              overflow: "hidden",
            }}
          >
            {/* 小啄木鸟蹲在右下角等 PRD · 拖入悬停时切换为"接住"姿势 */}
            {!prdName && (
              <img
                src={dragOver ? "/birds/biz-happy.png" : "/birds/biz-waiting.png"}
                alt=""
                aria-hidden
                width={88}
                height={88}
                style={{
                  position: "absolute",
                  right: 12,
                  bottom: 8,
                  width: 88,
                  height: 88,
                  opacity: 0.85,
                  pointerEvents: "none",
                  // 镜像让鸟朝向区域中心(文字方向)
                  transform: "scaleX(-1)",
                  transition: "opacity var(--dur-fast) var(--ease-out)",
                  userSelect: "none",
                }}
                onError={(e) => {
                  // PNG 缺失时静默隐藏,不影响拖拽功能
                  (e.currentTarget as HTMLImageElement).style.display = "none";
                }}
              />
            )}
            <div
              style={{
                fontSize: 14,
                fontWeight: 500,
                color: "var(--text-strong)",
                marginBottom: 4,
              }}
            >
              {prdName ? `已读 · ${prdName}` : "拖拽 PRD 到这里,或点击选择"}
            </div>
            <div style={{ fontSize: 12, color: "var(--text-muted)" }}>
              支持 .md / .txt / .markdown
              {prdName && (
                <span style={{ marginLeft: 8, fontFamily: "var(--font-mono)" }}>
                  · {prdContent.length.toLocaleString()} 字
                </span>
              )}
            </div>
            <input
              id="prd-file-input-v8"
              type="file"
              accept=".md,.txt,.markdown"
              style={{ display: "none" }}
              onChange={onPickFile}
            />
          </div>
          <textarea
            placeholder="或把 PRD 正文直接粘在这里……"
            rows={6}
            value={prdContent}
            onChange={(e) => {
              setUserInput({ prdContent: e.target.value });
              if (!prdName && e.target.value) {
                setUserInput({ prdName: "粘贴内容.md" });
              }
            }}
            style={{
              marginTop: 10,
              width: "100%",
              resize: "vertical",
              border: "1px solid var(--border-default)",
              borderRadius: "var(--r-3)",
              background: "var(--surface-raised)",
              padding: "10px 12px",
              fontFamily: "var(--font-mono)",
              fontSize: 12,
              lineHeight: 1.65,
              color: "var(--text-default)",
              outline: "none",
            }}
          />
        </Field>

        {/* 备注 */}
        <Field
          label="评审备注"
          hint="可选 · 写一句关注重点,本次评审会优先看"
          optional
        >
          <textarea
            placeholder="比如:这版改了 2 个字段名,担心字段口径和现有流程对不上"
            rows={3}
            value={userNotes}
            onChange={(e) => setUserInput({ userNotes: e.target.value })}
            style={{
              width: "100%",
              resize: "vertical",
              border: "1px solid var(--border-default)",
              borderRadius: "var(--r-3)",
              background: "var(--surface-raised)",
              padding: "10px 12px",
              fontFamily: "var(--font-sans)",
              fontSize: 13,
              lineHeight: 1.6,
              color: "var(--text-default)",
              outline: "none",
            }}
          />
        </Field>
      </div>

      {/* ── 底部动作行 ── */}
      <div
        style={{
          marginTop: 32,
          paddingTop: 20,
          borderTop: "1px solid var(--border-subtle)",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 12,
        }}
      >
        <span
          style={{
            fontSize: 12,
            color: "var(--text-faint)",
          }}
        >
          {canProceed ? "准备好了,可以开始预检" : "填完资料库与 PRD 后可进入下一步"}
        </span>
        <button
          type="button"
          onClick={handleNext}
          disabled={!canProceed}
          style={{
            height: 36,
            padding: "0 16px",
            border: 0,
            borderRadius: "var(--r-3)",
            background: canProceed
              ? "var(--accent-500)"
              : "var(--neutral-200)",
            color: canProceed ? "var(--accent-fg)" : "var(--text-muted)",
            fontSize: 13,
            fontWeight: 600,
            cursor: canProceed ? "pointer" : "not-allowed",
            fontFamily: "var(--font-sans)",
            transition: "background var(--dur-fast) var(--ease-out)",
          }}
        >
          下一步:资料预检 →
        </button>
      </div>
    </div>
  );
}

// ============================================================
// subcomponents

interface FieldProps {
  label: string;
  hint?: string;
  optional?: boolean;
  children: React.ReactNode;
}

function Field({ label, hint, optional, children }: FieldProps) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
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
            letterSpacing: "0.02em",
          }}
        >
          {label}
        </label>
        {optional && (
          <span
            style={{
              fontSize: 11,
              color: "var(--text-faint)",
            }}
          >
            可选
          </span>
        )}
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

interface ModeCardV8Props {
  active: boolean;
  name: string;
  eta: string;
  desc: string;
  onClick: () => void;
}

function ModeCardV8({ active, name, eta, desc, onClick }: ModeCardV8Props) {
  return (
    <button
      type="button"
      onClick={onClick}
      style={{
        position: "relative",
        cursor: "pointer",
        textAlign: "left",
        padding: "12px 14px",
        border: `1px solid ${active ? "var(--accent-500)" : "var(--border-default)"}`,
        borderRadius: "var(--r-4)",
        background: active ? "var(--accent-50)" : "var(--surface-raised)",
        transition: "all var(--dur-fast) var(--ease-out)",
        fontFamily: "var(--font-sans)",
      }}
    >
      {active && (
        <span
          style={{
            position: "absolute",
            right: 10,
            top: 10,
            width: 6,
            height: 6,
            borderRadius: "50%",
            background: "var(--accent-500)",
          }}
        />
      )}
      <div
        style={{
          fontSize: 13,
          fontWeight: 600,
          color: active ? "var(--accent-700)" : "var(--text-strong)",
          marginBottom: 4,
        }}
      >
        {name}
        <span
          style={{
            marginLeft: 8,
            fontSize: 11,
            fontFamily: "var(--font-mono)",
            fontWeight: 400,
            color: "var(--text-muted)",
          }}
        >
          {eta}
        </span>
      </div>
      <div
        style={{
          fontSize: 12,
          color: "var(--text-muted)",
          lineHeight: 1.55,
        }}
      >
        {desc}
      </div>
    </button>
  );
}

interface DraftBannerProps {
  draft: Draft;
  onResume: () => void;
  onDiscard: () => void;
}

function DraftBanner({ draft, onResume, onDiscard }: DraftBannerProps) {
  return (
    <div
      style={{
        marginBottom: 20,
        padding: "10px 14px",
        borderRadius: "var(--r-4)",
        border: `1px solid color-mix(in oklch, var(--accent-500) 22%, var(--border-subtle))`,
        background: "var(--accent-50)",
        display: "flex",
        alignItems: "center",
        gap: 12,
        flexWrap: "wrap",
        fontFamily: "var(--font-sans)",
      }}
    >
      <span
        style={{
          fontSize: 11,
          fontWeight: 600,
          color: "var(--accent-700)",
          padding: "2px 8px",
          borderRadius: "var(--r-2)",
          background: "var(--surface-raised)",
        }}
      >
        上次评审
      </span>
      <span style={{ fontSize: 13, color: "var(--text-default)", flex: 1 }}>
        <strong style={{ fontWeight: 600 }}>{draft.prd_name || "未命名"}</strong>
        {draft.workspace && (
          <span style={{ marginLeft: 6, color: "var(--text-muted)" }}>
            · {draft.workspace.replace(/^workspace-/, "")}
          </span>
        )}
        <span
          style={{
            marginLeft: 6,
            color: "var(--text-muted)",
            fontSize: 11,
          }}
        >
          · 进度 {phaseLabel(draft.phase)} · {formatTs(draft.ts)}
        </span>
        <span
          style={{
            display: "block",
            marginTop: 3,
            color: "var(--text-muted)",
            fontSize: 12,
            lineHeight: 1.5,
          }}
        >
          如果刚才断网或刷新,点“继续上次评审”即可回到原进度,不用重新跑评审。
        </span>
      </span>
      <div style={{ display: "flex", gap: 6 }}>
        <button
          type="button"
          onClick={onResume}
          style={{
            height: 28,
            padding: "0 10px",
            border: "1px solid var(--accent-500)",
            borderRadius: "var(--r-2)",
            background: "var(--accent-500)",
            color: "var(--accent-fg)",
            fontSize: 12,
            fontWeight: 600,
            cursor: "pointer",
            fontFamily: "var(--font-sans)",
          }}
        >
          继续上次评审
        </button>
        <button
          type="button"
          onClick={onDiscard}
          style={{
            height: 28,
            padding: "0 10px",
            border: "1px solid var(--border-default)",
            borderRadius: "var(--r-2)",
            background: "var(--surface-raised)",
            color: "var(--text-muted)",
            fontSize: 12,
            cursor: "pointer",
            fontFamily: "var(--font-sans)",
          }}
        >
          丢弃草稿
        </button>
      </div>
    </div>
  );
}

function formatTs(ts: string): string {
  const match = ts.match(/^\d{4}-(\d{2}-\d{2})T(\d{2}:\d{2})/);
  return match ? `${match[1]} ${match[2]}` : ts;
}

function phaseLabel(phase: number): string {
  switch (phase) {
    case 0:
      return "上传 PRD";
    case 1:
      return "资料预检";
    case 2:
      return "生成意见中";
    case 3:
      return "逐条确认";
    case 4:
      return "评审报告";
    default:
      return `第 ${phase} 步`;
  }
}
