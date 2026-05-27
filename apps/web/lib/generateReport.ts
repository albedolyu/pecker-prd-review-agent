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
  BusinessDecision,
  CorrectnessReason,
  ItemDecision,
  RejectReason,
  ReviewItem,
  ReviewResult,
} from "./api";
import { explainReviewItemForPm } from "./pm-friendly";

/**
 * 7 类 reject reason 的报告显示标签 — 与 Phase3ConfirmV8 REJECT_CATEGORIES 一致.
 * 改这里要同步 components/phases/Phase3ConfirmV8.tsx::REJECT_CATEGORIES.
 */
const REJECT_CATEGORY_LABELS: Record<RejectReason, string> = {
  good_issue: "实际是好问题(手滑点错)",
  false_positive: "误报",
  known_tradeoff: "已知取舍, 不改",
  wiki_missing: "资料库缺背景",
  rule_too_strict: "规则太严",
  impl_detail: "实现细节, 不该 PRD 管",
  model_noise: "判断不准",
};

const CORRECTNESS_REASON_LABELS: Record<CorrectnessReason, string> = {
  false_positive: "误报",
  unsupported_evidence: "依据不足",
  rule_too_strict: "规则过严",
};

const BUSINESS_DECISION_LABELS: Record<BusinessDecision, string> = {
  not_this_iteration: "本期不修",
  risk_accepted: "风险接受",
  handled_elsewhere: "已有安排",
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

const SENSITIVE_WATERMARK =
  "公开演示 / 仅限Pecker本地演示 / 可能包含敏感 PRD 内容";

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
  options: { includeMaintenanceDetails?: boolean } = {},
): string {
  const stats = computeStats(result, decisions);
  const createdAt = new Date(result.created_at * 1000).toLocaleString("zh-CN", {
    hour12: false,
  });

  const lines: string[] = [];
  lines.push(`# PRD 评审报告 - ${result.prd_name}`);
  lines.push("");
  lines.push(`> **评审人**: ${result.reviewer}  `);
  lines.push(`> **资料库**: ${formatWorkspaceName(result.workspace)}  `);
  lines.push(`> **评审模式**: ${formatReviewMode(result.mode)}  `);
  lines.push(`> **生成时间**: ${createdAt}  `);
  lines.push(`> **追踪编号**: \`${result.review_id}\``);
  lines.push("");

  // ===== 概要 =====
  lines.push("## 评审概要");
  lines.push("");
  lines.push(`- **需改强度**: **${stats.peckScore} / 100** (${stats.peckLabel})`);
  lines.push(`- **改进项**: ${stats.total} 条`);
  lines.push(
    `- **决策**: 采纳 ${stats.accepted} · 改写 ${stats.edited} · 驳回 ${stats.rejected} · 待确认 ${stats.pending}`,
  );
  if (result.workers.length > 0) {
    const workerSummary = result.workers
      .map((w) => `${w.dimension_name} ${w.items_count}`)
      .join(" · ");
    lines.push(`- **各方向提交**: ${workerSummary}`);
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
          ? "✅ 已采纳"
          : action === "edit"
            ? "✏️ 已改写"
            : action === "reject"
              ? "❌ 已驳回"
              : "⏳ 待确认";
      const severity = formatSeverity(item.severity);

      lines.push(`### ${idx + 1}. ${severity} ${actionTag}`.replace(/\s+/g, " ").trim());
      lines.push("");
      if (item.location) lines.push(`- **位置**: ${item.location}`);
      // 改写态:显示改写后的问题;否则显示原始
      if (action === "edit" && d?.edited_problem) {
        lines.push(`- **问题(改写后)**: ${d.edited_problem}`);
        if (item.problem) {
          lines.push(`  - 原意见: ${item.problem}`);
        }
      } else if (item.problem) {
        lines.push(`- **问题**: ${item.problem}`);
      }
      if (item.evidence) lines.push(`- **依据**: ${item.evidence}`);
      if (item.suggestion) lines.push(`- **建议**: ${item.suggestion}`);
      const pmExplanation = explainReviewItemForPm(item);
      if (pmExplanation.plain_language_summary) {
        lines.push(`- **PM 处理提示**: ${pmExplanation.plain_language_summary}`);
      }
      if (pmExplanation.pm_question) {
        lines.push(`- **PM 需要判断**: ${pmExplanation.pm_question}`);
      }
      if (pmExplanation.suggested_next_step) {
        lines.push(`- **建议动作**: ${pmExplanation.suggested_next_step}`);
      }
      if (action === "reject") {
        const correctnessReason = d?.correctness_reason;
        const businessDecision = d?.business_decision;
        if (correctnessReason) {
          lines.push(`- **判断问题**: ${CORRECTNESS_REASON_LABELS[correctnessReason] ?? correctnessReason}`);
        }
        if (businessDecision) {
          lines.push(`- **业务处理**: ${BUSINESS_DECISION_LABELS[businessDecision] ?? businessDecision}`);
        }
        const cat = d?.reason_category;
        if (cat && !correctnessReason && !businessDecision) {
          lines.push(`- **驳回原因**: ${REJECT_CATEGORY_LABELS[cat] ?? cat}`);
        }
        if (d?.reason) {
          lines.push(`- **驳回备注**: ${d.reason}`);
        }
      }
      if (typeof item.confidence === "number") {
        lines.push(`- **参考程度**: ${formatConfidenceLabel(item.confidence)}`);
      }
      lines.push("");
    });
  }

  // 无改进项 case
  if (result.items.length === 0) {
    lines.push("## 改进项");
    lines.push("");
    lines.push("> 本次评审**没有发现问题**。PRD 结构清晰、逻辑自洽、实现边界清楚。");
    lines.push("");
  }

  if (options.includeMaintenanceDetails) {
    // ===== 维护人处理记录(默认不放入 PM 下载报告) =====
    lines.push("---");
    lines.push("");
    lines.push("<details>");
    lines.push("<summary>维护人处理记录</summary>");
    lines.push("");
    lines.push("```json");
    lines.push(
      JSON.stringify(
        {
          review_id: result.review_id,
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
  }

  return lines.join("\n");
}

/**
 * 生成 PM 可带回原 PRD 的修订建议包。
 *
 * 不伪造“已自动改好”的正文,只输出 PM 已接受/改写的条目、位置、依据和建议。
 * 这份文件适合发给需求 owner 自己逐条落回原文。
 */
export function generateRevisionAdviceMarkdown(
  result: ReviewResult,
  decisions: Record<string, ItemDecision>,
): string {
  const applicableItems = result.items.filter((item) => {
    const action = decisions[item.id]?.action;
    return action === "accept" || action === "edit";
  });
  const createdAt = new Date().toLocaleString("zh-CN", { hour12: false });

  const lines: string[] = [];
  lines.push(`# PRD 修订建议包 - ${result.prd_name}`);
  lines.push("");
  lines.push(`> ${SENSITIVE_WATERMARK}  `);
  lines.push(`> **生成时间**: ${createdAt}  `);
  lines.push(`> **追踪编号**: \`${result.review_id}\`  `);
  lines.push(`> **说明**: 只收录 PM 已确认采纳或改写的建议；被驳回项不进入本包。`);
  lines.push("");
  lines.push("## 使用方式");
  lines.push("");
  lines.push("1. 回到原 PRD。");
  lines.push("2. 按位置逐条处理下方建议。");
  lines.push("3. 修改后保留本文件作为评审留痕。");
  lines.push("");
  lines.push("## 待落地修订");
  lines.push("");

  if (applicableItems.length === 0) {
    lines.push("> 暂无 PM 确认采纳或改写的建议。");
    lines.push("");
    return lines.join("\n");
  }

  applicableItems.forEach((item, idx) => {
    const decision = decisions[item.id];
    const actionLabel = decision?.action === "edit" ? "PM 改写后采纳" : "确认采纳";
    lines.push(`### ${idx + 1}. ${actionLabel}`);
    lines.push("");
    if (item.location) lines.push(`- **建议落点**: ${item.location}`);
    if (item.severity) lines.push(`- **优先级**: ${formatSeverity(item.severity).replaceAll("*", "")}`);
    if (decision?.action === "edit" && decision.edited_problem) {
      lines.push(`- **PM 修订后的问题描述**: ${decision.edited_problem}`);
      if (item.problem) lines.push(`- **原意见**: ${item.problem}`);
    } else if (item.problem) {
      lines.push(`- **问题**: ${item.problem}`);
    }
    if (item.evidence) lines.push(`- **依据**: ${item.evidence}`);
    if (item.suggestion) lines.push(`- **建议改法**: ${item.suggestion}`);
    if (typeof item.confidence === "number") {
      lines.push(`- **参考程度**: ${formatConfidenceLabel(item.confidence)}`);
    }
    lines.push("");
  });

  return lines.join("\n");
}

/**
 * 生成“修订稿草案”。
 *
 * 为了避免 AI 未经确认改写业务事实,第一版不直接重写 PRD 正文。
 * 输出为: 原 PRD 全文 + PM 已确认建议附录。PM 可在此基础上人工改正文。
 */
export function generateRevisionDraftMarkdown(
  result: ReviewResult,
  decisions: Record<string, ItemDecision>,
  originalPrd: string,
): string {
  const createdAt = new Date().toLocaleString("zh-CN", { hour12: false });
  const adviceMarkdown = generateRevisionAdviceMarkdown(result, decisions);
  const source = originalPrd.trim() || "_原 PRD 正文为空或未在浏览器状态中保留。_";

  const lines: string[] = [];
  lines.push(`# ${result.prd_name.replace(/\.[^.]+$/, "") || "PRD"} - 修订稿草案`);
  lines.push("");
  lines.push(`> ${SENSITIVE_WATERMARK}  `);
  lines.push(`> **生成时间**: ${createdAt}  `);
  lines.push(`> **追踪编号**: \`${result.review_id}\`  `);
  lines.push("> **重要说明**: 本文件没有覆盖原文事实。正文保持原 PRD 内容,附录列出 PM 已确认的修订建议。");
  lines.push("");
  lines.push("## 原 PRD 正文");
  lines.push("");
  lines.push(source);
  lines.push("");
  lines.push("---");
  lines.push("");
  lines.push("## Pecker修订建议附录");
  lines.push("");
  lines.push(adviceMarkdown);
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

function formatWorkspaceName(workspace: string): string {
  return (workspace || "未选资料库").replace(/^workspace-/, "");
}

function formatReviewMode(mode: string): string {
  if (mode === "quick") return "轻评审";
  if (mode === "standard") return "深评审";
  return mode || "未标明";
}

function formatConfidenceLabel(value: number): string {
  if (value >= 0.85) return "依据充分";
  if (value >= 0.7) return "可参考";
  return "需再核对";
}
