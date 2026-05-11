"use client";

import { useState } from "react";
import { HelpCircle, MessageCircle, Send, X } from "lucide-react";

import { answerReviewAssistantQuestion } from "@/lib/review-assistant";
import { summarizeRawMaterials } from "@/lib/supplemental-materials";
import { useReviewStore } from "@/lib/store";

const QUICK_QUESTIONS = [
  "图片和 Figma 读到了吗",
  "采纳驳回改写有什么区别",
  "报告怎么导出",
  "卡住或超时怎么办",
];

type AssistantMessage = {
  role: "assistant" | "user";
  text: string;
};

export function ReviewHelpAssistant() {
  const [open, setOpen] = useState(false);
  const [question, setQuestion] = useState("");
  const [messages, setMessages] = useState<AssistantMessage[]>([
    {
      role: "assistant",
      text: "我可以帮你解释上传材料、预检、评审耗时、采纳/驳回/改写和报告导出。",
    },
  ]);

  const phase = useReviewStore((s) => s.phase);
  const rawMaterials = useReviewStore((s) => s.rawMaterials);
  const reviewResult = useReviewStore((s) => s.reviewResult);
  const materialSummary = summarizeRawMaterials(rawMaterials);

  const ask = (value: string) => {
    const text = value.trim();
    if (!text) return;
    const answer = answerReviewAssistantQuestion(text, {
      phase,
      rawMaterials,
      reviewResult,
    });
    setMessages((current) => [
      ...current,
      { role: "user" as const, text },
      { role: "assistant" as const, text: answer },
    ]);
    setQuestion("");
    setOpen(true);
  };

  return (
    <div
      style={{
        position: "fixed",
        right: 20,
        bottom: 20,
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
            boxShadow: "0 18px 50px rgba(15, 23, 42, 0.18)",
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
              <div style={{ fontSize: 13, fontWeight: 650, color: "var(--text-strong)" }}>
                啄木鸟问答助手
              </div>
              <div style={{ marginTop: 2, fontSize: 11, color: "var(--text-muted)" }}>
                阶段 {phase} · 材料 {materialSummary.total} 条
              </div>
            </div>
            <button
              type="button"
              aria-label="关闭问答助手"
              onClick={() => setOpen(false)}
              style={{
                border: 0,
                background: "transparent",
                color: "var(--text-muted)",
                cursor: "pointer",
                padding: 4,
              }}
            >
              <X size={16} />
            </button>
          </header>

          <div aria-live="polite" style={{ maxHeight: 300, overflowY: "auto", padding: 12 }}>
            {messages.map((message, index) => (
              <div
                key={`${message.role}-${index}`}
                style={{
                  display: "flex",
                  justifyContent: message.role === "user" ? "flex-end" : "flex-start",
                  marginBottom: 8,
                }}
              >
                <div
                  style={{
                    maxWidth: "86%",
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
                  }}
                >
                  {message.text}
                </div>
              </div>
            ))}
          </div>

          <div
            style={{
              display: "flex",
              flexWrap: "wrap",
              gap: 6,
              padding: "0 12px 10px",
            }}
          >
            {QUICK_QUESTIONS.map((item) => (
              <button
                key={item}
                type="button"
                onClick={() => ask(item)}
                style={{
                  border: "1px solid var(--border-default)",
                  borderRadius: 6,
                  background: "transparent",
                  color: "var(--text-muted)",
                  cursor: "pointer",
                  fontSize: 11,
                  padding: "4px 7px",
                }}
              >
                {item}
              </button>
            ))}
          </div>

          <form
            onSubmit={(event) => {
              event.preventDefault();
              ask(question);
            }}
            style={{
              display: "flex",
              gap: 8,
              padding: 12,
              borderTop: "1px solid var(--border-subtle)",
            }}
          >
            <input
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              placeholder="问一个使用问题..."
              style={{
                flex: 1,
                minWidth: 0,
                border: "1px solid var(--border-default)",
                borderRadius: 6,
                background: "var(--surface-raised)",
                color: "var(--text-default)",
                fontSize: 12,
                padding: "0 9px",
                outline: "none",
              }}
            />
            <button
              type="submit"
              aria-label="发送问题"
              style={{
                width: 34,
                height: 34,
                border: 0,
                borderRadius: 6,
                background: "var(--accent-500)",
                color: "var(--accent-fg)",
                cursor: "pointer",
                display: "grid",
                placeItems: "center",
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
          border: "1px solid var(--border-default)",
          borderRadius: 8,
          background: "var(--accent-500)",
          color: "var(--accent-fg)",
          cursor: "pointer",
          display: "grid",
          placeItems: "center",
          boxShadow: "0 12px 36px rgba(15, 23, 42, 0.2)",
        }}
      >
        {open ? <HelpCircle size={20} /> : <MessageCircle size={20} />}
      </button>
    </div>
  );
}
