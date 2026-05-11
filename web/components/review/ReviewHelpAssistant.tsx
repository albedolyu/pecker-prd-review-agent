"use client";

import { useRef, useState, type ReactNode } from "react";
import {
  Check,
  Copy,
  HelpCircle,
  MessageCircle,
  Send,
  ThumbsDown,
  ThumbsUp,
  X,
} from "lucide-react";

import { auditApi } from "@/lib/api";
import { answerReviewAssistantQuestionAsync } from "@/lib/review-assistant";
import { summarizeRawMaterials } from "@/lib/supplemental-materials";
import { useReviewStore } from "@/lib/store";

const QUICK_QUESTIONS = [
  "图片和 Figma 读到了吗",
  "采纳驳回改写有什么区别",
  "查风鸟事实层依据",
  "报告怎么导出",
  "卡住或超时怎么办",
];

type AssistantMessage = {
  id: string;
  role: "assistant" | "user";
  text: string;
  feedback?: "up" | "down";
  copied?: boolean;
};

export function ReviewHelpAssistant() {
  const messageSeq = useRef(0);
  const [open, setOpen] = useState(false);
  const [question, setQuestion] = useState("");
  const [isAsking, setIsAsking] = useState(false);
  const [messages, setMessages] = useState<AssistantMessage[]>([
    {
      id: "assistant-welcome",
      role: "assistant",
      text: "我可以帮你解释上传材料、预检、评审耗时、采纳/驳回/改写和报告导出。",
    },
  ]);

  const phase = useReviewStore((s) => s.phase);
  const workspace = useReviewStore((s) => s.workspace);
  const prdName = useReviewStore((s) => s.prdName);
  const rawMaterials = useReviewStore((s) => s.rawMaterials);
  const reviewResult = useReviewStore((s) => s.reviewResult);
  const materialSummary = summarizeRawMaterials(rawMaterials);
  const bottomOffset = phase >= 3 ? 88 : 20;
  const materialSummaryText = [
    `材料 ${materialSummary.total} 条`,
    materialSummary.images > 0 ? `图片 ${materialSummary.images}` : "",
    materialSummary.figmaLinks > 0 ? `Figma ${materialSummary.figmaLinks}` : "",
  ]
    .filter(Boolean)
    .join(" · ");

  const nextMessageId = (role: AssistantMessage["role"]) => {
    messageSeq.current += 1;
    return `${role}-${Date.now()}-${messageSeq.current}`;
  };

  const logAssistantAction = (
    event: "review_assistant_feedback" | "review_assistant_copied",
    message: AssistantMessage,
    extra: Record<string, unknown> = {},
  ) => {
    void auditApi.log({
      event,
      workspace,
      prd_name: prdName,
      extra: {
        phase,
        message_id: message.id,
        answer_length: message.text.length,
        ...extra,
      },
    }).catch(() => undefined);
  };

  const markFeedback = (message: AssistantMessage, feedback: "up" | "down") => {
    setMessages((current) =>
      current.map((item) => (item.id === message.id ? { ...item, feedback } : item)),
    );
    logAssistantAction("review_assistant_feedback", message, { feedback });
  };

  const copyAnswer = async (message: AssistantMessage) => {
    try {
      await writeAnswerToClipboard(message.text);
      setMessages((current) =>
        current.map((item) => (item.id === message.id ? { ...item, copied: true } : item)),
      );
      window.setTimeout(() => {
        setMessages((current) =>
          current.map((item) => (item.id === message.id ? { ...item, copied: false } : item)),
        );
      }, 1600);
      logAssistantAction("review_assistant_copied", message);
    } catch {
      logAssistantAction("review_assistant_copied", message, { status: "failed" });
    }
  };

  const ask = async (value: string) => {
    const text = value.trim();
    if (!text || isAsking) return;
    setQuestion("");
    setOpen(true);
    setIsAsking(true);
    setMessages((current) => [
      ...current,
      { id: nextMessageId("user"), role: "user" as const, text },
    ]);
    try {
      const answer = await answerReviewAssistantQuestionAsync(text, {
        phase,
        rawMaterials,
        reviewResult,
      });
      setMessages((current) => [
        ...current,
        { id: nextMessageId("assistant"), role: "assistant" as const, text: answer },
      ]);
    } finally {
      setIsAsking(false);
    }
  };

  return (
    <div
      style={{
        position: "fixed",
        right: 20,
        bottom: bottomOffset,
        zIndex: 60,
        fontFamily: "var(--font-sans)",
      }}
    >
      {open && (
        <section
          role="dialog"
          aria-label="啄木鸟问答助手"
          style={{
            width: 360,
            maxWidth: "calc(100vw - 32px)",
            marginBottom: 12,
            border: "1px solid var(--border-default)",
            borderRadius: 8,
            background: "var(--surface-raised)",
            boxShadow: "0 18px 46px rgba(15, 23, 42, 0.16)",
            overflow: "hidden",
          }}
        >
          <header
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              gap: 12,
              padding: "12px 14px",
              borderBottom: "1px solid var(--border-subtle)",
            }}
          >
            <div>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <span
                  style={{
                    display: "grid",
                    width: 24,
                    height: 24,
                    placeItems: "center",
                    borderRadius: 6,
                    background: "var(--accent-50)",
                    color: "var(--accent-600)",
                  }}
                >
                  <MessageCircle size={14} />
                </span>
                <span style={{ fontSize: 13, fontWeight: 650, color: "var(--text-strong)" }}>
                  啄木鸟问答助手
                </span>
              </div>
              <div style={{ marginTop: 4, fontSize: 11, color: "var(--text-muted)" }}>
                阶段 {phase} · {materialSummaryText}
              </div>
            </div>
            <button
              type="button"
              aria-label="关闭问答助手"
              onClick={() => setOpen(false)}
              style={{
                width: 28,
                height: 28,
                border: "1px solid transparent",
                borderRadius: 6,
                background: "transparent",
                color: "var(--text-muted)",
                cursor: "pointer",
                display: "grid",
                placeItems: "center",
              }}
            >
              <X size={16} />
            </button>
          </header>

          <div aria-live="polite" style={{ maxHeight: 300, overflowY: "auto", padding: 12 }}>
            {messages.map((message, index) => (
              <div
                key={`${message.id}-${index}`}
                style={{
                  display: "flex",
                  justifyContent: message.role === "user" ? "flex-end" : "flex-start",
                  marginBottom: 8,
                }}
              >
                <div style={{ maxWidth: "86%" }}>
                  <div
                    style={{
                      maxWidth: "100%",
                      borderRadius: 8,
                      padding: "8px 10px",
                      fontSize: 12,
                      lineHeight: 1.6,
                      background:
                        message.role === "user"
                          ? "var(--accent-500)"
                          : "var(--surface-sunken)",
                      color:
                        message.role === "user"
                          ? "var(--accent-fg)"
                          : "var(--text-default)",
                      border:
                        message.role === "user"
                          ? "1px solid transparent"
                          : "1px solid var(--border-subtle)",
                    }}
                  >
                    {message.text}
                  </div>
                  {message.role === "assistant" && (
                    <div
                      style={{
                        display: "flex",
                        gap: 4,
                        marginTop: 5,
                        color: "var(--text-muted)",
                      }}
                    >
                      <AssistantActionButton
                        label="点赞这条回答"
                        active={message.feedback === "up"}
                        onClick={() => markFeedback(message, "up")}
                      >
                        <ThumbsUp size={13} />
                      </AssistantActionButton>
                      <AssistantActionButton
                        label="踩这条回答"
                        active={message.feedback === "down"}
                        onClick={() => markFeedback(message, "down")}
                      >
                        <ThumbsDown size={13} />
                      </AssistantActionButton>
                      <AssistantActionButton
                        label="复制这条回答"
                        active={Boolean(message.copied)}
                        onClick={() => void copyAnswer(message)}
                      >
                        {message.copied ? <Check size={13} /> : <Copy size={13} />}
                      </AssistantActionButton>
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>

          <div
            style={{
              borderTop: "1px solid var(--border-subtle)",
              padding: "10px 12px",
            }}
          >
            <div
              style={{
                marginBottom: 7,
                fontSize: 11,
                fontWeight: 600,
                color: "var(--text-muted)",
              }}
            >
              常见问题
            </div>
            <div
              style={{
                display: "flex",
                flexWrap: "wrap",
                gap: 6,
              }}
            >
              {QUICK_QUESTIONS.map((item) => (
                <button
                  key={item}
                  type="button"
                  disabled={isAsking}
                  onClick={() => void ask(item)}
                  style={{
                    border: "1px solid var(--border-default)",
                    borderRadius: 6,
                    background: "var(--surface-raised)",
                    color: "var(--text-muted)",
                    cursor: isAsking ? "not-allowed" : "pointer",
                    fontSize: 11,
                    padding: "5px 8px",
                    lineHeight: 1.4,
                    opacity: isAsking ? 0.65 : 1,
                  }}
                >
                  {item}
                </button>
              ))}
            </div>
          </div>

          <form
            onSubmit={(event) => {
              event.preventDefault();
              void ask(question);
            }}
            style={{
              display: "flex",
              gap: 8,
              padding: 12,
              borderTop: "1px solid var(--border-subtle)",
              background: "var(--surface-sunken)",
            }}
          >
            <input
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              disabled={isAsking}
              placeholder={isAsking ? "正在查询..." : "问一个使用问题..."}
              style={{
                flex: 1,
                minWidth: 0,
                height: 34,
                border: "1px solid var(--border-default)",
                borderRadius: 6,
                background: isAsking ? "var(--surface-sunken)" : "var(--surface-raised)",
                color: "var(--text-default)",
                fontSize: 12,
                padding: "0 9px",
                outline: "none",
              }}
            />
            <button
              type="submit"
              aria-label="发送问题"
              disabled={isAsking}
              style={{
                width: 34,
                height: 34,
                border: 0,
                borderRadius: 6,
                background: "var(--accent-500)",
                color: "var(--accent-fg)",
                cursor: isAsking ? "not-allowed" : "pointer",
                display: "grid",
                placeItems: "center",
                flex: "0 0 auto",
                opacity: isAsking ? 0.7 : 1,
              }}
            >
              <Send size={15} />
            </button>
          </form>
        </section>
      )}

      <button
        type="button"
        aria-label="打开啄木鸟问答助手"
        onClick={() => setOpen((value) => !value)}
        style={{
          width: 48,
          height: 48,
          border: "1px solid var(--accent-600)",
          borderRadius: 8,
          background: "var(--accent-500)",
          color: "var(--accent-fg)",
          cursor: "pointer",
          display: "grid",
          placeItems: "center",
          boxShadow: "0 12px 32px rgba(15, 23, 42, 0.18)",
        }}
      >
        {open ? <HelpCircle size={20} /> : <MessageCircle size={20} />}
      </button>
    </div>
  );
}

async function writeAnswerToClipboard(text: string) {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(text);
    return;
  }
  const textarea = document.createElement("textarea");
  textarea.value = text;
  textarea.setAttribute("readonly", "true");
  textarea.style.position = "fixed";
  textarea.style.left = "-9999px";
  document.body.appendChild(textarea);
  textarea.select();
  const copied = document.execCommand("copy");
  document.body.removeChild(textarea);
  if (!copied) {
    throw new Error("copy failed");
  }
}

function AssistantActionButton({
  active,
  children,
  label,
  onClick,
}: {
  active?: boolean;
  children: ReactNode;
  label: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      onClick={onClick}
      style={{
        display: "grid",
        width: 24,
        height: 24,
        placeItems: "center",
        border: "1px solid var(--border-subtle)",
        borderRadius: 6,
        background: active ? "var(--accent-50)" : "transparent",
        color: active ? "var(--accent-600)" : "var(--text-muted)",
        cursor: "pointer",
      }}
    >
      {children}
    </button>
  );
}
