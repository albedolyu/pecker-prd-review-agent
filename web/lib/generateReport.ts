/**
 * 把 ReviewResult + 用户决策合成最终评审报告 markdown。
 *
 * 这个文件是 Phase 4 的核心工具:下载 / save-to-wiki / 飞书推送 都吃同一份
 * markdown,所以集中在这里生成,保证三条出口一致。
 *
 * 格式参考现有 Streamlit 版本的报告结构:
 *   # PRD 评审报告 - {prd_name}
 *   ## 评审概要
 *   ## 决策统计
 *   ## 改进项(按职能分组)
 *     ### 责编
 *     ### 审校
 *     ...
 *   ## 原始评审数据(可选)
 *
 * "啄伤度" (peck score): 0-100 分,基于 items 数量 + severity 加权计算。
 * 这只是一个粗糙启发式,实际业务语义可在 Phase D 细化。
 */

import {
  ROLES,
  WORKER_ROLE_KEYS,
  normalizeDimensionKey,
  type RoleKey,
} from "./roles";
import type {
  ItemDecision,
  RejectReason,
  ReviewItem,
  ReviewResult,
} from "./api";

/**
 * 7 类 reject reason 的报告显示标签 — 与 Phase3ConfirmV8 REJECT_CATEGORIES 一致.
 * 改这里要同步 components/phases/Phase3ConfirmV8.tsx::REJECT_CATEGORIES.
 */
const REJECT_CATEGORY_LABELS: Record<RejectReason, string> = {
  good_issue: "实际是好问题(手滑点错)",
  false_positive: "误报",
  known_tradeoff: "已知取舍, 不改",
  wiki_missing: "知识库缺失",
  rule_too_strict: "规则太严",
  impl_detail: "实现细节, 不该 PRD 管",
  model_noise: "模型噪音",
};

export interface ReportStats {
  total: number;
  accepted: number;
  rejected: number;
  edited: number;
  pending: number;
  peckScore: number;
  peckLabel: string;
}

/**
 * 基于决策计算 "啄伤度" — 经验公式:
 *   base = min(100, accepted * 10 + edited * 6 + rejected * 2)
 *   severity multiplier: must 权重 1.0,should 0.6,其他 0.3
 */
export function computeStats(
  result: ReviewResult,
  decisions: Record<string, ItemDecision>,
): ReportStats {
  const total = result.items.length;
  let accepted = 0;
  let rejected = 0;
  let edited = 0;

  let weightedScore = 0;
  for (const item of result.items) {
    const d = decisions[item.id];
    if (!d) continue;
    const sevWeight =
      item.severity === "must"
        ? 1.0
        : item.severity === "should"
          ? 0.6
          : 0.3;
    if (d.action === "accept") {
      accepted += 1;
      weightedScore += 10 * sevWeight;
    } else if (d.action === "edit") {
      edited += 1;
      weightedScore += 6 * sevWeight;
    } else if (d.action === "reject") {
      rejected += 1;
      weightedScore += 2 * sevWeight;
    }
  }

  const peckScore = Math.min(100, Math.round(weightedScore));
  const peckLabel =
    peckScore >= 80
      ? "严重"
      : peckScore >= 50
        ? "中等"
        : peckScore >= 20
          ? "轻微"
          : "极少";

  return {
    total,
    accepted,
    rejected,
    edited,
    pending: total - accepted - rejected - edited,
    peckScore,
    peckLabel,
  };
}

/**
 * 生成完整的评审报告 markdown 字符串。
 */
export function generateReportMarkdown(
  result: ReviewResult,
  decisions: Record<string, ItemDecision>,
): string {
  const stats = computeStats(result, decisions);
  const createdAt = new Date(result.created_at * 1000).toLocaleString("zh-CN", {
    hour12: false,
  });

  const lines: string[] = [];
  lines.push(`# PRD 评审报告 - ${result.prd_name}`);
  lines.push("");
  lines.push(`> **评审人**: ${result.reviewer}  `);
  lines.push(`> **Workspace**: ${result.workspace}  `);
  lines.push(`> **模式**: ${result.mode}  `);
  lines.push(`> **生成时间**: ${createdAt}  `);
  lines.push(`> **Review ID**: \`${result.review_id}\``);
  lines.push("");

  // ===== 概要 =====
  lines.push("## 评审概要");
  lines.push("");
  lines.push(`- **啄伤度**: **${stats.peckScore} / 100** (${stats.peckLabel})`);
  lines.push(`- **改进项**: ${stats.total} 条`);
  lines.push(
    `- **决策**: 接受 ${stats.accepted} · 改写 ${stats.edited} · 拒绝 ${stats.rejected} · 待决 ${stats.pending}`,
  );
  if (result.workers.length > 0) {
    const workerSummary = result.workers
      .map((w) => `${w.dimension_name} ${w.items_count}`)
      .join(" · ");
    lines.push(`- **worker 贡献**: ${workerSummary}`);
  }
  if (result.goshawk_summary) {
    const fp = (result.goshawk_summary["flagged_as_false_positive"] as unknown[] | undefined)?.length ?? 0;
    const add = (result.goshawk_summary["additional_findings"] as unknown[] | undefined)?.length ?? 0;
    lines.push(`- **终审交叉校验**: 撤回 ${fp} 条,补充 ${add} 条`);
  }
  lines.push("");

  // ===== 按职能分组 =====
  const byDim = groupByDimension(result.items);

  // 展示顺序: 4 个 worker + final-reviewer(终审补充项)
  const dimOrder: ReadonlyArray<RoleKey> = [
    ...WORKER_ROLE_KEYS,
    "final-reviewer",
  ];

  for (const dim of dimOrder) {
    const items = byDim.get(dim);
    if (!items || items.length === 0) continue;

    const role = ROLES[dim];
    lines.push(`## ${role.label}(${role.responsibility})`);
    lines.push("");
    lines.push(`> 又名 ${role.birdEmoji} ${role.birdName} — ${role.description.split("。")[0]}。`);
    lines.push("");

    items.forEach((item, idx) => {
      const d = decisions[item.id];
      const action = d?.action ?? "pending";
      const actionTag =
        action === "accept"
          ? "✅ 已接受"
          : action === "edit"
            ? "✏️ 已改写"
            : action === "reject"
              ? "❌ 已拒绝"
              : "⏳ 待决";
      const severity = formatSeverity(item.severity);

      lines.push(`### ${idx + 1}. ${item.id ?? "-"} ${severity} ${actionTag}`);
      lines.push("");
      if (item.location) lines.push(`- **位置**: ${item.location}`);
      // 改写态:显示改写后的问题;否则显示原始
      if (action === "edit" && d?.edited_problem) {
        lines.push(`- **问题(改写后)**: ${d.edited_problem}`);
        if (item.problem) {
          lines.push(`  - 原始: ${item.problem}`);
        }
      } else if (item.problem) {
        lines.push(`- **问题**: ${item.problem}`);
      }
      if (item.evidence) lines.push(`- **依据**: ${item.evidence}`);
      if (item.suggestion) lines.push(`- **建议**: ${item.suggestion}`);
      if (action === "reject") {
        // P0 step 2 (2026-04-28): 报告里区分 7 类 reason_category + 自由文本备注
        // 老版本只有 reason 自由文本, 现在带 category label 让读报告的人知道驳因归类
        const cat = d?.reason_category;
        if (cat) {
          lines.push(`- **拒绝原因**: ${REJECT_CATEGORY_LABELS[cat] ?? cat}`);
        }
        if (d?.reason) {
          lines.push(`- **驳回备注**: ${d.reason}`);
        }
      }
      if (typeof item.confidence === "number") {
        lines.push(`- **置信度**: ${(item.confidence * 100).toFixed(0)}%`);
      }
      lines.push("");
    });
  }

  // 无改进项 case
  if (result.items.length === 0) {
    lines.push("## 改进项");
    lines.push("");
    lines.push("> 本次评审**没有发现问题**。PRD 结构清晰、逻辑自洽、技术约定完整。");
    lines.push("");
  }

  // ===== 原始 JSON(便于后续 eval) =====
  lines.push("---");
  lines.push("");
  lines.push("<details>");
  lines.push("<summary>原始 Opaque Handle(调试用)</summary>");
  lines.push("");
  lines.push("```json");
  lines.push(
    JSON.stringify(
      {
        review_id: result.review_id,
        signature: result.signature,
        items_count: result.items.length,
        usage: result.usage,
      },
      null,
      2,
    ),
  );
  lines.push("```");
  lines.push("");
  lines.push("</details>");
  lines.push("");

  return lines.join("\n");
}

function groupByDimension(
  items: ReadonlyArray<ReviewItem>,
): Map<RoleKey, ReviewItem[]> {
  const map = new Map<RoleKey, ReviewItem[]>();
  for (const item of items) {
    const key = normalizeDimensionKey(item.dimension);
    const arr = map.get(key) ?? [];
    arr.push(item);
    map.set(key, arr);
  }
  return map;
}

function formatSeverity(sev?: string): string {
  if (!sev) return "";
  if (sev === "must") return "**[必须]**";
  if (sev === "should") return "**[建议]**";
  if (sev === "suggest") return "[参考]";
  return `[${sev}]`;
}
