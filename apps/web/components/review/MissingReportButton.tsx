"use client";

/**
 * MissingReportButton · v8 harness 增量 P1⑦
 *
 * "➕ 我发现一个他们漏掉的问题" 入口,点开弹 modal,让 PM 填:
 * 1. 问题内容(必填)
 * 2. 对应 PRD 段落 / 位置
 * 3. 应该归哪只鸟(1-5 · worker + 苍鹰)
 *
 * 提交后通过 onSubmit 回调外送；当前正式入口会写入后端 PM 补充线索日志。
 *
 * 按钮常驻 Phase 3/4 底部。Modal 关闭后保持表单草稿(关掉也能回来继续写)。
 */

import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { type BirdId } from "@/components/birds/BirdAvatar";
import { BIRD_META } from "@/components/birds/BirdBadge";

export interface MissingReportPayload {
  problem: string;
  location: string;
  responsibleBirdId: BirdId | null;
  submittedAt: string;
}

interface MissingReportButtonProps {
  /** 可点击鸟 id 集合(默认 1-5:4 worker + 苍鹰) */
  availableBirdIds?: BirdId[];
  onSubmit?: (payload: MissingReportPayload) => void | Promise<void>;
  className?: string;
  style?: React.CSSProperties;
}

const LOCAL_KEY = "pecker_v8_missing_report_draft";

export function MissingReportButton({
  availableBirdIds = [1, 2, 3, 4, 5],
  onSubmit,
  className,
  style,
}: MissingReportButtonProps) {
  const [open, setOpen] = useState(false);
  const [problem, setProblem] = useState("");
  const [location, setLocation] = useState("");
  const [responsible, setResponsible] = useState<BirdId | null>(null);
  const [submitting, setSubmitting] = useState(false);

  // 草稿恢复
  useEffect(() => {
    try {
      const raw = localStorage.getItem(LOCAL_KEY);
      if (raw) {
        const d = JSON.parse(raw);
        setProblem(d.problem ?? "");
        setLocation(d.location ?? "");
        setResponsible(d.responsible ?? null);
      }
    } catch {
      /* ignore */
    }
  }, []);

  // 实时保存草稿
  useEffect(() => {
    if (!open) return;
    try {
      localStorage.setItem(
        LOCAL_KEY,
        JSON.stringify({ problem, location, responsible }),
      );
    } catch {
      /* ignore */
    }
  }, [open, problem, location, responsible]);

  const canSubmit = problem.trim().length > 0;

  const handleSubmit = useCallback(async () => {
    if (!canSubmit) return;
    setSubmitting(true);
    const payload: MissingReportPayload = {
      problem: problem.trim(),
      location: location.trim(),
      responsibleBirdId: responsible,
      submittedAt: new Date().toISOString(),
    };
    try {
      await onSubmit?.(payload);
      toast.success("已记录,将用于后续规则优化");
      try {
        localStorage.removeItem(LOCAL_KEY);
      } catch {
        /* ignore */
      }
      setProblem("");
      setLocation("");
      setResponsible(null);
      setOpen(false);
    } catch (e) {
      toast.error(`提交失败:${(e as Error).message}`);
    } finally {
      setSubmitting(false);
    }
  }, [canSubmit, problem, location, responsible, onSubmit]);

  // esc 关 modal
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className={className}
        style={{
          display: "inline-flex",
          alignItems: "center",
          gap: 6,
          padding: "6px 12px",
          border: "1px dashed var(--border-default)",
          borderRadius: "var(--r-3)",
          background: "transparent",
          color: "var(--text-muted)",
          fontSize: 12,
          fontFamily: "var(--font-sans)",
          cursor: "pointer",
          transition: "all var(--dur-fast) var(--ease-out)",
          ...style,
        }}
        onMouseEnter={(e) => {
          (e.currentTarget as HTMLButtonElement).style.borderColor =
            "var(--accent-500)";
          (e.currentTarget as HTMLButtonElement).style.color =
            "var(--accent-600)";
        }}
        onMouseLeave={(e) => {
          (e.currentTarget as HTMLButtonElement).style.borderColor =
            "var(--border-default)";
          (e.currentTarget as HTMLButtonElement).style.color =
            "var(--text-muted)";
        }}
      >
        <span style={{ fontSize: 14, lineHeight: 1 }}>+</span>
        我还发现一个问题
      </button>

      {open && (
        <Modal onClose={() => setOpen(false)}>
          <div
            style={{
              display: "flex",
              flexDirection: "column",
              gap: 16,
              padding: 22,
            }}
          >
            <header>
              <div
                style={{
                  fontSize: 11,
                  fontWeight: 600,
                  color: "var(--accent-600)",
                  marginBottom: 4,
                }}
              >
                补充评审线索
              </div>
              <h2
                style={{
                  fontSize: 18,
                  fontWeight: 600,
                  color: "var(--text-strong)",
                  margin: 0,
                }}
              >
                我还发现一个问题
              </h2>
              <p
                style={{
                  fontSize: 12,
                  color: "var(--text-muted)",
                  marginTop: 4,
                  lineHeight: 1.55,
                }}
              >
                把评审鸟漏掉的问题补充上来,系统会用于优化下次的检查规则
              </p>
            </header>

            {/* 问题内容 */}
            <Field label="问题描述" required>
              <textarea
                autoFocus
                value={problem}
                onChange={(e) => setProblem(e.target.value)}
                rows={3}
                placeholder="例如:PRD 漏了下游服务降级策略,会影响测试验收"
                style={textareaStyle}
              />
            </Field>

            {/* 对应位置 */}
            <Field label="PRD 位置" hint="可选 · 如 §2.3 或贴一句关键字">
              <input
                type="text"
                value={location}
                onChange={(e) => setLocation(e.target.value)}
                placeholder="§2.3 · 风险服务依赖"
                style={inputStyle}
              />
            </Field>

            {/* 应该归哪只鸟 */}
            <Field
              label="属于哪类问题"
              hint="选一只对应职责的评审鸟,帮助系统下次更准"
            >
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                {availableBirdIds.map((id) => (
                  <BirdChoice
                    key={id}
                    id={id}
                    selected={responsible === id}
                    onClick={() =>
                      setResponsible(responsible === id ? null : id)
                    }
                  />
                ))}
              </div>
            </Field>

            {/* actions */}
            <div
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                gap: 8,
                paddingTop: 8,
                borderTop: "1px solid var(--border-subtle)",
              }}
            >
              <span
                style={{
                  fontSize: 11,
                  color: "var(--text-faint)",
                }}
              >
                草稿自动保存,Esc 可关闭
              </span>
              <div style={{ display: "flex", gap: 8 }}>
                <button
                  type="button"
                  onClick={() => setOpen(false)}
                  style={btnSecondary}
                  disabled={submitting}
                >
                  取消
                </button>
                <button
                  type="button"
                  onClick={handleSubmit}
                  disabled={!canSubmit || submitting}
                  style={
                    !canSubmit || submitting
                      ? btnPrimaryDisabled
                      : btnPrimary
                  }
                >
                  {submitting ? "提交中…" : "提交"}
                </button>
              </div>
            </div>
          </div>
        </Modal>
      )}
    </>
  );
}

// ============================================================
// subcomponents

function Modal({
  children,
  onClose,
}: {
  children: React.ReactNode;
  onClose: () => void;
}) {
  return (
    <div
      role="dialog"
      aria-modal="true"
      onClick={onClose}
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(15, 20, 30, 0.5)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: "var(--z-overlay)" as unknown as number,
        padding: 16,
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          width: "100%",
          maxWidth: 520,
          background: "var(--surface-raised)",
          border: "1px solid var(--border-default)",
          borderRadius: "var(--r-4)",
          boxShadow: "var(--shadow-lg)",
          maxHeight: "90vh",
          overflow: "auto",
        }}
      >
        {children}
      </div>
    </div>
  );
}

function Field({
  label,
  required,
  hint,
  children,
}: {
  label: string;
  required?: boolean;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 6 }}>
        <label
          style={{
            fontSize: 12,
            fontWeight: 600,
            color: "var(--text-strong)",
          }}
        >
          {label}
          {required && (
            <span style={{ color: "var(--status-failed-fg)", marginLeft: 4 }}>
              *
            </span>
          )}
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

function BirdChoice({
  id,
  selected,
  onClick,
}: {
  id: BirdId;
  selected: boolean;
  onClick: () => void;
}) {
  const meta = BIRD_META[id];
  return (
    <button
      type="button"
      onClick={onClick}
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 6,
        padding: "5px 10px",
        borderRadius: "var(--r-pill)",
        border: `1px solid ${selected ? "var(--accent-500)" : "var(--border-default)"}`,
        background: selected ? "var(--accent-50)" : "var(--surface-raised)",
        color: selected ? "var(--accent-700)" : "var(--text-default)",
        fontSize: 12,
        fontWeight: 500,
        cursor: "pointer",
        fontFamily: "var(--font-sans)",
        transition: "all var(--dur-fast) var(--ease-out)",
      }}
    >
      <span
        aria-hidden
        style={{
          width: 6,
          height: 6,
          borderRadius: "50%",
          background: `var(--bird-${id})`,
          flexShrink: 0,
        }}
      />
      <span>{meta.label}鸟</span>
    </button>
  );
}

// ============================================================
// styles

const textareaStyle: React.CSSProperties = {
  width: "100%",
  resize: "vertical",
  border: "1px solid var(--border-default)",
  borderRadius: "var(--r-3)",
  background: "var(--surface-raised)",
  padding: "8px 12px",
  fontFamily: "var(--font-sans)",
  fontSize: 13,
  lineHeight: 1.6,
  color: "var(--text-default)",
  outline: "none",
};

const inputStyle: React.CSSProperties = {
  width: "100%",
  height: 34,
  border: "1px solid var(--border-default)",
  borderRadius: "var(--r-3)",
  background: "var(--surface-raised)",
  padding: "0 12px",
  fontFamily: "var(--font-mono)",
  fontSize: 12,
  color: "var(--text-default)",
  outline: "none",
};

const btnPrimary: React.CSSProperties = {
  height: 32,
  padding: "0 14px",
  border: 0,
  borderRadius: "var(--r-3)",
  background: "var(--accent-500)",
  color: "var(--accent-fg)",
  fontSize: 12,
  fontWeight: 600,
  cursor: "pointer",
  fontFamily: "var(--font-sans)",
};

const btnPrimaryDisabled: React.CSSProperties = {
  ...btnPrimary,
  background: "var(--neutral-200)",
  color: "var(--text-muted)",
  cursor: "not-allowed",
};

const btnSecondary: React.CSSProperties = {
  height: 32,
  padding: "0 14px",
  border: "1px solid var(--border-default)",
  borderRadius: "var(--r-3)",
  background: "var(--surface-raised)",
  color: "var(--text-default)",
  fontSize: 12,
  fontWeight: 500,
  cursor: "pointer",
  fontFamily: "var(--font-sans)",
};
