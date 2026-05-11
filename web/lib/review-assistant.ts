import { summarizeRawMaterials } from "@/lib/supplemental-materials";
import type { ReviewPhase } from "@/lib/store";
import { reviewAssistantApi, type ReviewResult } from "@/lib/api";

export interface ReviewAssistantContext {
  phase: ReviewPhase;
  rawMaterials: readonly string[];
  reviewResult?: ReviewResult | null;
}

const FENGNIAO_EVIDENCE_TERMS = [
  "风鸟",
  "fengniao",
  "知识库",
  "事实层",
  "源码",
  "原始",
  "接口",
  "字段",
  "页面",
  "模块",
  "已有实现",
];

const FACT_LAYER_TERMS = [
  "事实层",
  "原始",
  "源码",
  "代码",
  "接口",
  "字段",
  "实现",
  "页面",
  "数据库",
  "api",
  "source",
];

export function shouldQueryFengniaoEvidence(question: string): boolean {
  const q = question.toLowerCase();
  return includesAny(q, FENGNIAO_EVIDENCE_TERMS);
}

export function shouldIncludeFactLayer(question: string): boolean {
  const q = question.toLowerCase();
  return includesAny(q, FACT_LAYER_TERMS);
}

export async function answerReviewAssistantQuestionAsync(
  question: string,
  context: ReviewAssistantContext,
): Promise<string> {
  const text = question.trim();
  if (!shouldQueryFengniaoEvidence(text)) {
    return answerReviewAssistantQuestion(text, context);
  }

  try {
    const response = await reviewAssistantApi.askFengniao({
      question: text,
      include_fact_layer: shouldIncludeFactLayer(text),
      max_results: 5,
    });
    if (response.answer.trim()) {
      return response.answer;
    }
  } catch {
    // Keep the assistant usable even if the evidence endpoint is unavailable.
  }

  return [
    answerReviewAssistantQuestion(text, context),
    "风鸟知识库/事实层查询暂时不可用，先按当前页面信息处理；需要核对源码时可以稍后再问“查事实层/源码/接口字段”。",
  ].join("\n\n");
}

export function answerReviewAssistantQuestion(
  question: string,
  context: ReviewAssistantContext,
): string {
  const q = question.toLowerCase();
  if (includesAny(q, ["图片", "截图", "figma", "原型", "附件", "材料"])) {
    const summary = summarizeRawMaterials(context.rawMaterials);
    if (summary.total === 0) {
      return "当前还没有接入图片或 Figma 补充材料。可以在上传页添加图片附件，或粘贴 Figma 链接；进入预检页后会和 PRD 正文一起作为评审上下文。";
    }
    return [
      `当前已接入 ${summary.images} 个图片附件、${summary.figmaLinks} 个 Figma 链接，共 ${summary.total} 条补充材料。`,
      "这些材料会随 PRD 一起进入预检页和评审上下文；如果图片或原型里有关键验收口径，建议也在正文或备注中写一句，能减少漏判。",
    ].join("");
  }

  if (includesAny(q, ["采纳", "驳回", "改写", "接受", "拒绝"])) {
    return "采纳表示认可这条问题，会计入最终报告；驳回表示认为这条不适用，需要选择驳回原因；改写适合方向对但表述不准的情况，会用 PM 改后的内容进入报告。";
  }

  if (includesAny(q, ["导出", "报告", "下载"])) {
    return "报告需要先完成最后一步确认。确认后进入报告页，点击导出报告即可；如果按钮不可用，先检查是否还有待处理条目，或刷新后从草稿恢复。";
  }

  if (includesAny(q, ["卡住", "超时", "524", "没反应", "失败"])) {
    return "大 PRD 评审会进入后台任务。页面断开后可以刷新并恢复进度；如果长时间没有推进，先看当前阶段提示，再联系运维检查 /api/health、后台 worker 和网关超时配置。";
  }

  if (context.phase === 0) {
    return "这一步先准备 PRD 正文、资料库、图片或 Figma 补充材料。正文越明确，后续判断越稳定；图片和原型建议配一两句关键说明。";
  }
  if (context.phase === 3 && context.reviewResult?.items?.length) {
    return `当前有 ${context.reviewResult.items.length} 条评审建议需要确认。建议逐条判断：真实问题就采纳，不适用就驳回，方向对但话术不准就改写。`;
  }
  return "我可以回答上传材料、预检、评审耗时、采纳/驳回/改写、报告导出这些使用问题。你也可以直接问“图片读到了吗”或“这条为什么要驳回”。";
}

function includesAny(value: string, terms: readonly string[]): boolean {
  return terms.some((term) => value.includes(term));
}
