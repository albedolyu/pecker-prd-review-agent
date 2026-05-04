"use client";

/**
 * Phase 1 · v8 · 盲区预检(工作台气质)
 *
 * 数据契约和 v7 Phase1Precheck 一致(reviewApi.precheck + store 零改动),
 * 只换 UI 层:
 * - 去刊头"先看看自己的书柜" + LoadingDots 呼吸 + paper-card 纸卡
 * - 顶部简洁标题 + 3 列汇总卡(strong/weak/gap,和 DocumentView summary 同色)
 * - 自动触发预检 · 完成后 0.8s 自动跳 Phase 2
 * - 底部补充说明 + 返回 / 重新预检 / 下一步按钮
 */

import { useEffect, useRef } from "react";
import { useMutation } from "@tanstack/react-query";
import { toast } from "sonner";

import {
  reviewApi,
  draftsApi,
  ApiError,
  type PrecheckResponse,
} from "@/lib/api";
import { useReviewStore } from "@/lib/store";

export function Phase1PrecheckV8() {
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
        `预检完成 · 已覆盖 ${data.strong.length} 项,${data.gaps.length} 项可能是知识盲区`,
      );
      setTimeout(() => setPhase(2), 800);
    },
    onError: (e: ApiError) => {
      toast.error(`预检失败: ${e.detail ?? e.message}`);
    },
  });

  const triggered = useRef(false);
  useEffect(() => {
    if (!precheckResult && !triggered.current && prdContent && workspace) {
      triggered.current = true;
      mutation.mutate();
    }
  }, [precheckResult, prdContent, workspace, mutation]);

  const handleRetry = () => {
    triggered.current = true;
    mutation.mutate();
  };

  const handleNext = async () => {
    if (!precheckResult) {
      toast.warning("预检还没完成,请稍候");
      return;
    }
    if (Object.keys(wikiPages).length === 0) {
      toast.warning("知识库为空,接下来的评审拿不到上下文");
    }
    try {
      if (reviewer) {
        await draftsApi.save(reviewer, { ...toDraftPayload(), phase: 2 });
      }
    } catch {
      /* 非阻塞 */
    }
    setPhase(2);
  };

  const isLoading = mutation.isPending;
  const hasResult = !!precheckResult;

  return (
    <div
      style={{
        maxWidth: 920,
        margin: "0 auto",
        padding: "32px 24px 80px",
        fontFamily: "var(--font-sans)",
      }}
    >
      {/* ── header ── */}
      <header style={{ marginBottom: 24 }}>
        <h1
          style={{
            fontSize: 22,
            fontWeight: 600,
            color: "var(--text-strong)",
            margin: 0,
            letterSpacing: "-0.015em",
          }}
        >
          盲区预检
        </h1>
        <p
          style={{
            fontSize: 13,
            color: "var(--text-muted)",
            marginTop: 4,
          }}
        >
          先翻一遍资料库,看 PRD 哪些点已有依据、哪些点是知识盲区
        </p>
      </header>

      {/* ── 加载态 ── */}
      {isLoading && !hasResult && (
        <LoadingCard />
      )}

      {/* ── 错误态 ── */}
      {mutation.isError && !hasResult && (
        <div
          style={{
            marginBottom: 16,
            padding: "12px 16px",
            borderRadius: "var(--r-4)",
            border: "1px solid var(--status-failed-fg)",
            background: "var(--status-failed-bg)",
          }}
        >
          <div
            style={{
              fontSize: 13,
              fontWeight: 600,
              color: "var(--status-failed-fg)",
              marginBottom: 6,
            }}
          >
            预检失败
          </div>
          <p
            style={{
              fontSize: 13,
              color: "var(--text-default)",
              margin: "0 0 10px",
              lineHeight: 1.55,
            }}
          >
            {(mutation.error as ApiError)?.detail ??
              (mutation.error as Error)?.message}
          </p>
          <button
            type="button"
            onClick={handleRetry}
            style={btnSecondaryStyle}
          >
            重试
          </button>
        </div>
      )}

      {/* ── 3 列结果 ── */}
      {hasResult && precheckResult && (
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(3, 1fr)",
            gap: 12,
            marginBottom: 20,
          }}
        >
          <ResultColumn
            kind="strong"
            title="已覆盖"
            hint="资料库里有充分依据"
            items={precheckResult.strong}
            empty="没有强相关的资料"
          />
          <ResultColumn
            kind="weak"
            title="部分覆盖"
            hint="资料库里只提了一两句"
            items={precheckResult.weak}
            empty="没有弱相关的资料"
          />
          <ResultColumn
            kind="gap"
            title="知识盲区"
            hint="资料库缺这个主题,评审可能信息不足"
            items={precheckResult.gaps}
            empty="未发现明显盲区"
          />
        </div>
      )}

      {/* ── 补充说明 ── */}
      {hasResult && (
        <div style={{ marginBottom: 20 }}>
          <div
            style={{
              display: "flex",
              alignItems: "baseline",
              gap: 8,
              marginBottom: 6,
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
              补充说明
            </label>
            <span
              style={{
                fontSize: 11,
                color: "var(--text-faint)",
              }}
            >
              可选
            </span>
            <span style={{ fontSize: 11, color: "var(--text-muted)" }}>
              看过预检后可以再提醒一句评审重点
            </span>
          </div>
          <textarea
            placeholder="例:本次重点检查字段映射;忽略 UI 交互部分…"
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
        </div>
      )}

      {/* ── 底部动作行 ── */}
      <footer
        style={{
          marginTop: 24,
          paddingTop: 20,
          borderTop: "1px solid var(--border-subtle)",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 12,
        }}
      >
        <button
          type="button"
          onClick={() => setPhase(0)}
          style={btnGhostStyle}
        >
          ← 返回
        </button>
        <div style={{ display: "flex", gap: 8 }}>
          {hasResult && (
            <button
              type="button"
              onClick={handleRetry}
              style={btnSecondaryStyle}
            >
              重新预检
            </button>
          )}
          <button
            type="button"
            onClick={handleNext}
            disabled={!hasResult || isLoading}
            style={
              !hasResult || isLoading
                ? btnPrimaryDisabledStyle
                : btnPrimaryStyle
            }
          >
            下一步:开始评审 →
          </button>
        </div>
      </footer>
    </div>
  );
}

// ============================================================
// subcomponents

function LoadingCard() {
  return (
    <div
      style={{
        marginBottom: 16,
        padding: "16px 18px",
        borderRadius: "var(--r-4)",
        border: "1px dashed var(--border-default)",
        background: "var(--surface-sunken)",
        display: "flex",
        alignItems: "center",
        gap: 14,
      }}
    >
      <span
        aria-hidden
        style={{
          display: "inline-flex",
          gap: 5,
        }}
      >
        {[0, 1, 2].map((i) => (
          <span
            key={i}
            style={{
              width: 7,
              height: 7,
              borderRadius: "50%",
              background: "var(--accent-500)",
              animation: `dot-breathe 1.4s var(--ease-out) infinite`,
              animationDelay: `${i * 0.2}s`,
            }}
          />
        ))}
      </span>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div
          style={{
            fontSize: 13,
            fontWeight: 500,
            color: "var(--text-strong)",
            marginBottom: 2,
          }}
        >
          正在查阅资料库…
        </div>
        <div
          style={{
            fontSize: 12,
            color: "var(--text-muted)",
            lineHeight: 1.55,
          }}
        >
          扫一遍知识库索引,再让 AI 检查 PRD 可能的盲点。约 10-15 秒,请不要关闭页面。
        </div>
      </div>
    </div>
  );
}

type ColumnKind = "strong" | "weak" | "gap";

interface ResultColumnProps {
  kind: ColumnKind;
  title: string;
  hint: string;
  items: ReadonlyArray<string>;
  empty: string;
}

function ResultColumn({ kind, title, hint, items, empty }: ResultColumnProps) {
  const tone = {
    strong: {
      fg: "var(--status-done-fg)",
      bg: "var(--status-done-bg)",
      dot: "var(--status-done-dot)",
    },
    weak: {
      fg: "var(--status-warn-fg)",
      bg: "var(--status-warn-bg)",
      dot: "var(--status-warn-dot)",
    },
    gap: {
      fg: "var(--status-failed-fg)",
      bg: "var(--status-failed-bg)",
      dot: "var(--status-failed-dot)",
    },
  }[kind];

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        background: "var(--surface-raised)",
        border: "1px solid var(--border-default)",
        borderRadius: "var(--r-4)",
        overflow: "hidden",
      }}
    >
      {/* header */}
      <div
        style={{
          padding: "10px 14px",
          borderBottom: "1px solid var(--border-subtle)",
          display: "flex",
          alignItems: "center",
          gap: 8,
        }}
      >
        <span
          style={{
            width: 8,
            height: 8,
            borderRadius: "50%",
            background: tone.dot,
            flexShrink: 0,
          }}
        />
        <span
          style={{
            fontSize: 13,
            fontWeight: 600,
            color: "var(--text-strong)",
          }}
        >
          {title}
        </span>
        <span style={{ flex: 1 }} />
        <span
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: 12,
            fontWeight: 600,
            color: tone.fg,
            padding: "2px 8px",
            borderRadius: "var(--r-pill)",
            background: tone.bg,
            fontVariantNumeric: "tabular-nums",
          }}
        >
          {items.length}
        </span>
      </div>
      <div
        style={{
          fontSize: 11,
          color: "var(--text-muted)",
          padding: "6px 14px",
          borderBottom: "1px solid var(--border-subtle)",
        }}
      >
        {hint}
      </div>
      {/* list */}
      <ul
        style={{
          listStyle: "none",
          margin: 0,
          padding: "8px 14px 12px",
          display: "flex",
          flexDirection: "column",
          gap: 4,
          maxHeight: 320,
          overflow: "auto",
          fontSize: 13,
          color: "var(--text-default)",
        }}
      >
        {items.length === 0 ? (
          <li
            style={{
              fontSize: 12,
              color: "var(--text-faint)",
              fontStyle: "italic",
            }}
          >
            {empty}
          </li>
        ) : (
          <>
            {items.slice(0, 20).map((item, idx) => (
              <li
                key={idx}
                style={{
                  display: "flex",
                  gap: 8,
                  padding: "4px 0",
                  lineHeight: 1.55,
                }}
              >
                <span
                  style={{
                    fontSize: 11,
                    color: "var(--text-faint)",
                    minWidth: 18,
                    paddingTop: 2,
                    fontVariantNumeric: "tabular-nums",
                  }}
                >
                  {idx + 1}
                </span>
                <span style={{ flex: 1, wordBreak: "break-word" }}>{item}</span>
              </li>
            ))}
            {items.length > 20 && (
              <li
                style={{
                  fontSize: 11,
                  color: "var(--text-faint)",
                  fontStyle: "italic",
                  marginTop: 4,
                }}
              >
                还有 {items.length - 20} 条省略
              </li>
            )}
          </>
        )}
      </ul>
    </div>
  );
}

// ============================================================
// styles

const btnPrimaryStyle: React.CSSProperties = {
  height: 34,
  padding: "0 14px",
  border: 0,
  borderRadius: "var(--r-3)",
  background: "var(--accent-500)",
  color: "var(--accent-fg)",
  fontSize: 13,
  fontWeight: 600,
  cursor: "pointer",
  fontFamily: "var(--font-sans)",
};

const btnPrimaryDisabledStyle: React.CSSProperties = {
  ...btnPrimaryStyle,
  background: "var(--neutral-200)",
  color: "var(--text-muted)",
  cursor: "not-allowed",
};

const btnSecondaryStyle: React.CSSProperties = {
  height: 34,
  padding: "0 14px",
  border: "1px solid var(--border-default)",
  borderRadius: "var(--r-3)",
  background: "var(--surface-raised)",
  color: "var(--text-default)",
  fontSize: 13,
  fontWeight: 500,
  cursor: "pointer",
  fontFamily: "var(--font-sans)",
};

const btnGhostStyle: React.CSSProperties = {
  height: 34,
  padding: "0 10px",
  border: 0,
  borderRadius: "var(--r-3)",
  background: "transparent",
  color: "var(--text-muted)",
  fontSize: 13,
  fontWeight: 500,
  cursor: "pointer",
  fontFamily: "var(--font-sans)",
};
