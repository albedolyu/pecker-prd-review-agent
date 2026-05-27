import type { ReviewItem, ReviewResult } from "./api";
import { normalizeDimensionKey, type RoleKey } from "./roles";

export type TestabilityVerdict = "blocked" | "partial" | "ready";
export type EstimatedCaseCoverage = "低" | "中" | "高";
export type HandoffType =
  | "blocking_test_generation"
  | "case_quality_risk"
  | "engineering_context";

export interface PmActionItem {
  id: string;
  severity: string;
  dimension: string;
  rule_id: string;
  location: string;
  issue: string;
  why_it_matters: string;
  suggested_change: string;
  prd_patch_label: string;
  prd_patch: string;
  feedback_options: readonly string[];
}

export interface PmItemExplanation {
  plain_language_summary: string;
  pm_question: string;
  suggested_next_step: string;
  why_it_matters: string;
  detail_label: string;
  is_engineering_context: boolean;
}

export interface PmSummary {
  verdict: string;
  rework_risk: "低" | "中" | "高";
  blocking_count: number;
  total_items: number;
  top_risk_dimensions: ReadonlyArray<{ dimension: string; count: number }>;
  priority_items: ReadonlyArray<PmActionItem>;
  feedback_options: readonly string[];
  review_mode: "light" | "deep";
}

export interface PmView {
  pm_count: number;
  engineering_count: number;
  pm_items: ReadonlyArray<PmActionItem>;
  engineering_items: ReadonlyArray<PmActionItem>;
  default_view: "pm";
}

export interface TestabilityGap extends PmActionItem {
  handoff_type: HandoffType;
  case_types_affected: readonly string[];
  needs_pm_confirmation: boolean;
}

export interface TestabilitySummary {
  testability_verdict: TestabilityVerdict;
  estimated_case_coverage: EstimatedCaseCoverage;
  blocking_gap_count: number;
  quality_risk_count: number;
  engineering_context_count: number;
  testable_modules: ReadonlyArray<{
    module: string;
    dimension: string;
    source_item_id: string;
    recommended_case_types: readonly string[];
  }>;
  untestable_gaps: ReadonlyArray<TestabilityGap>;
  case_quality_risks: ReadonlyArray<TestabilityGap>;
  engineering_context: ReadonlyArray<TestabilityGap>;
  acceptance_criteria: ReadonlyArray<{
    source_item_id: string;
    location: string;
    criterion: string;
    status: "missing_or_needs_clarification" | "candidate";
  }>;
}

export interface ZhiquScenario {
  source_item_id: string;
  module: string;
  scenario: string;
  case_types: readonly string[];
  preconditions_needed: string;
  expected_result_needed: string;
  blocked: boolean;
  suggested_pm_input: string;
}

export interface ZhiquTraceItem {
  review_item_id: string;
  rule_id: string;
  dimension: string;
  location: string;
  severity: string;
}

export interface ZhiquHandoff {
  schema_version: "pecker_to_zhiqu.v1";
  source_system: "pecker";
  target_agent: "zhiqu_test_case_agent";
  requirement_id: string;
  prd_id: string;
  prd_version: readonly string[];
  review_id: string;
  review_mode: "light" | "deep";
  pm_verdict: string;
  testability_verdict: TestabilityVerdict;
  estimated_case_coverage: EstimatedCaseCoverage;
  testable_modules: TestabilitySummary["testable_modules"];
  untestable_gaps: TestabilitySummary["untestable_gaps"];
  acceptance_criteria: TestabilitySummary["acceptance_criteria"];
  scenario_matrix: ReadonlyArray<ZhiquScenario>;
  edge_cases: ReadonlyArray<ZhiquScenario>;
  negative_cases: ReadonlyArray<ZhiquScenario>;
  data_requirements: ReadonlyArray<ZhiquScenario>;
  traceability: ReadonlyArray<ZhiquTraceItem>;
  source_trace: {
    workspace: string;
    prd_files: readonly string[];
    prd_hash: string;
    previous_report: string;
    report_paths: Record<string, string>;
  };
  pm_controls: {
    do_not_invent_missing_requirements: true;
    blocked_items_require_pm_input: readonly string[];
    feedback_options: readonly string[];
  };
}

export interface PmFriendlySnapshot {
  pmSummary: PmSummary;
  pmView: PmView;
  testabilitySummary: TestabilitySummary;
  zhiquHandoff: ZhiquHandoff;
}

const FEEDBACK_OPTIONS = [
  "有用",
  "误报",
  "已在别处说明",
  "表达不清",
  "优先级过高",
] as const;

const SEVERITY_RANK: Record<string, number> = {
  must: 0,
  should: 1,
  could: 2,
  suggest: 2,
};

const DIMENSION_LABELS: Record<RoleKey, string> = {
  "editor-in-chief": "主控协调",
  structure: "业务完整性",
  quality: "使用体验",
  ai_coding: "实现风险",
  data_quality: "字段口径",
  "final-reviewer": "终审",
  "reader-feedback": "反馈",
  "sample-reader": "评估",
  archivist: "知识库",
  "qa-gatekeeper": "质检",
};

const DIMENSION_IMPACT: Record<RoleKey, string> = {
  "editor-in-chief": "会影响评审编排和协作节奏。",
  structure: "会影响研发、测试对范围、流程和边界的共同理解。",
  quality: "会影响验收口径，容易在评审后继续返工。",
  ai_coding: "会影响研发拆接口、建模型和生成代码时的确定性。",
  data_quality: "会影响字段口径、数据来源和后续核对成本。",
  "final-reviewer": "会影响跨维度结论是否能被 PM 直接采纳。",
  "reader-feedback": "会影响后续反馈信号回收质量。",
  "sample-reader": "会影响评审输出本身的可读性和稳定性。",
  archivist: "会影响知识库证据和历史口径的可追溯性。",
  "qa-gatekeeper": "会影响交付前的质量门禁和回归检查。",
};

const PM_QUESTIONS: Record<RoleKey, string> = {
  "editor-in-chief": "这条是否会影响本次评审结论的可信度？",
  structure: "PRD 里是否已经把目标、范围、流程和验收讲清楚？",
  quality: "异常、空态、权限、文案或边界场景是否已经能被验收？",
  ai_coding: "这里是 PRD 需要约束的接口/字段/边界，还是研发实现细节？",
  data_quality: "字段口径、数据来源、枚举和校验规则是否已经写清楚？",
  "final-reviewer": "这条是否需要作为最终结论交给 PM 处理？",
  "reader-feedback": "这条反馈是否值得沉淀为后续规则？",
  "sample-reader": "这条是否说明当前评审样例还不够稳定？",
  archivist: "相关背景是否需要补到资料库，避免下次继续误判？",
  "qa-gatekeeper": "这条是否会挡住继续进入下一步确认？",
};

const PM_NEXT_STEPS: Record<string, string> = {
  must: "建议先补到 PRD，再继续推进。",
  should: "建议本轮补齐，减少后面返工。",
  could: "可以作为优化项记录，不一定阻塞本次推进。",
  suggest: "可以作为优化项记录，不一定阻塞本次推进。",
};

const TESTABILITY_BLOCKING_TERMS = [
  "验收",
  "状态",
  "异常",
  "字段",
  "口径",
  "权限",
  "前置",
  "预期",
  "成功",
  "失败",
  "无权限",
  "边界",
  "规则",
  "流程",
  "DDL",
  "acceptance",
  "status",
  "exception",
  "field",
  "permission",
  "precondition",
  "expected",
] as const;

const CASE_TYPE_TERMS: ReadonlyArray<readonly [string, string]> = [
  ["验收", "acceptance"],
  ["成功", "positive"],
  ["失败", "negative"],
  ["异常", "exception"],
  ["权限", "permission"],
  ["无权限", "permission"],
  ["字段", "data"],
  ["口径", "data"],
  ["边界", "boundary"],
  ["状态", "state_transition"],
  ["流程", "workflow"],
  ["acceptance", "acceptance"],
  ["success", "positive"],
  ["failure", "negative"],
  ["exception", "exception"],
  ["permission", "permission"],
  ["field", "data"],
  ["status", "state_transition"],
] as const;

const PM_GLOSSARY_HINTS: ReadonlyArray<readonly [RegExp, string]> = [
  [/状态机|状态流转/i, "状态机可以理解为业务状态怎么流转，要写清每一步怎么进入、怎么退出。"],
  [/回滚|灰度|埋点|上游|下游|事务|超时/i, "回滚是出问题后怎么退回；灰度是先放给一小部分用户；埋点是后续看数据的记录方式；上游下游是前后依赖的系统或流程。"],
  [/SLA|服务等级|服务承诺/i, "SLA 可以理解为服务承诺，要写清失败时谁负责、多久恢复。"],
  [/接口|API/i, "接口可以理解为系统之间的对接方式，要写清谁调用谁、传什么、返回什么。"],
  [/并发|重复提交/i, "并发是多人或多个请求同时发生，要写清重复提交、重复处理时的规则。"],
  [/回调/i, "回调是别的系统处理完后再通知回来，要写清触发时机、成功和失败口径。"],
  [/缓存/i, "缓存是临时保存旧结果来提速，要写清什么时候更新、什么时候失效。"],
  [/DDL|表结构|数据表/i, "DDL 可以理解为数据表结构，要写清字段、类型和约束。"],
  [/枚举|enum/i, "枚举就是可选值清单，要写清每个值代表什么。"],
  [/幂等/i, "幂等是重复操作结果要一致，要写清重复提交怎么处理。"],
  [/异步/i, "异步表示不会马上完成，要写清等待、成功和失败状态。"],
  [/降级/i, "降级是服务异常时的替代方案，要写清用户看到什么、业务怎么兜底。"],
  [/重试/i, "重试是失败后是否自动再试，要写清次数、间隔和最终失败提示。"],
  [/权限|无权限/i, "权限要写清谁能看、谁能改、无权限时怎么提示。"],
  [/P99|QPS|容量|限流|熔断/i, "P99、QPS、限流和熔断都可以先理解为高峰期能不能扛住、流量太大时怎么保护服务，PRD 要写清触发条件和用户提示。"],
  [/队列|积压|排队/i, "队列积压表示异步任务排队太多时怎么处理，要写清等待提示、处理顺序和超时兜底。"],
  [/补偿|补偿任务/i, "补偿任务是失败后怎么补救，要写清谁触发、补哪一步、补失败后怎么处理。"],
  [/脱敏|审计|留痕|白名单|黑名单/i, "脱敏、审计和名单规则都关系到哪些字段不能直接展示或外发，PRD 要写清适用对象和例外情况。"],
] as const;

export function formatReviewModeLabel(mode: string | undefined): string {
  if (mode === "quick") return "轻评审";
  if (mode === "standard") return "深评审";
  return mode || "-";
}

export function buildPmFriendlySnapshot(
  result: ReviewResult,
): PmFriendlySnapshot {
  const pmSummary = buildPmSummary(result);
  const pmView = buildPmView(result);
  const testabilitySummary = buildTestabilitySummary(result);
  const zhiquHandoff = buildZhiquHandoff(result, {
    pmSummary,
    testabilitySummary,
  });
  return {
    pmSummary,
    pmView,
    testabilitySummary,
    zhiquHandoff,
  };
}

export function buildPmSummary(result: ReviewResult): PmSummary {
  const items = sourceItems(result);
  const failedWorkers = result.workers.filter((worker) => worker.error);
  const blockingItems = items.filter(
    (item) => severityOf(item) === "must",
  );
  const priorityItems = sortedItems(items).slice(0, 5).map(pmActionItem);
  const dimensionCounts = countDimensions(items);

  let verdict = "可进入评审";
  let reworkRisk: PmSummary["rework_risk"] = "低";
  if (failedWorkers.length > 0 || blockingItems.length >= 6) {
    verdict = "暂不建议进入开发";
    reworkRisk = "高";
  } else if (blockingItems.length > 0 || items.length >= 10) {
    verdict = "建议补充后再评审";
    reworkRisk = "中";
  }

  return {
    verdict,
    rework_risk: reworkRisk,
    blocking_count: blockingItems.length,
    total_items: items.length,
    top_risk_dimensions: dimensionCounts.slice(0, 3),
    priority_items: priorityItems,
    feedback_options: FEEDBACK_OPTIONS,
    review_mode: reviewModeForHandoff(result.mode),
  };
}

export function buildPmView(result: ReviewResult): PmView {
  const items = sortedItems(sourceItems(result));
  const pmItems = items
    .filter((item) => !isEngineeringItem(item))
    .map(pmActionItem);
  const engineeringItems = items
    .filter((item) => isEngineeringItem(item))
    .map(pmActionItem);

  return {
    pm_count: pmItems.length,
    engineering_count: engineeringItems.length,
    pm_items: pmItems,
    engineering_items: engineeringItems,
    default_view: "pm",
  };
}

export function explainReviewItemForPm(item: ReviewItem): PmItemExplanation {
  const dimKey = normalizeDimensionKey(item.dimension);
  const severity = severityOf(item);
  const fallbackNextStep =
    severity === "must"
      ? PM_NEXT_STEPS.must
      : severity === "should"
        ? PM_NEXT_STEPS.should
        : PM_NEXT_STEPS.suggest;

  const suggestion = stringValue(item.suggestion);
  const isEngineeringContext = isEngineeringItem(item);
  return {
    plain_language_summary: plainLanguageSummary(item, dimKey, severity),
    pm_question: PM_QUESTIONS[dimKey],
    suggested_next_step: isEngineeringContext
      ? "如果 PRD 不需要限定这件事，可以驳回为「实现细节」；如果会影响验收，请补充到 PRD。"
      : suggestion
        ? `${fallbackNextStep} ${suggestion}`
        : fallbackNextStep,
    why_it_matters: DIMENSION_IMPACT[dimKey],
    detail_label: isEngineeringContext ? "偏研发细节" : "PM 可处理",
    is_engineering_context: isEngineeringContext,
  };
}

export function buildReviewItemPatchText(item: ReviewItem): string {
  const proposedPatch = stringValue(item.proposed_patch);
  if (proposedPatch) return proposedPatch;

  const parts: string[] = [];
  const location = itemLocation(item);
  const problem = itemTitle(item);
  const suggestion = stringValue(item.suggestion);
  const evidence = stringValue(item.evidence);

  if (location) parts.push(`位置：${location}`);
  if (problem) parts.push(`问题：${problem}`);
  if (suggestion) parts.push(`建议补丁：${suggestion}`);
  if (evidence) parts.push(`依据：${evidence}`);
  return parts.join("\n");
}

function plainLanguageSummary(
  item: ReviewItem,
  dimKey: RoleKey,
  severity: string,
): string {
  const withHint = (summary: string) => withGlossaryHint(summary, item);
  if (dimKey === "ai_coding") {
    return withHint("这条先不用当成研发方案来看，它是在提醒：这里可能需要 PM 明确边界，否则研发会自己猜。");
  }
  if (dimKey === "data_quality") {
    return withHint("这条主要在问：字段从哪里来、怎么填、错了怎么办，PRD 里是否已经说清。");
  }
  if (dimKey === "quality") {
    return withHint("这条主要在问：真实用户或测试同事走到这个场景时，能不能知道下一步和验收结果。");
  }
  if (dimKey === "structure") {
    return withHint("这条主要在问：目标、范围、流程和验收是不是足够完整，能不能直接给研发排期。");
  }
  if (severity === "must") {
    return withHint("这条属于优先确认项：不处理可能影响研发理解、测试验收或后续交付。");
  }
  return withHint("这条是一个补充提醒：先判断它是否会影响本次交付，再决定接受、驳回或改写。");
}

function withGlossaryHint(summary: string, item: ReviewItem): string {
  const text = itemText(item);
  const hints = PM_GLOSSARY_HINTS
    .filter(([pattern]) => pattern.test(text))
    .map(([, hint]) => hint)
    .slice(0, 4);
  if (hints.length === 0) return summary;
  return `${summary} 术语翻译：${hints.join(" ")}`;
}

export function buildTestabilitySummary(result: ReviewResult): TestabilitySummary {
  const items = sortedItems(sourceItems(result));
  const gaps = items.map(testabilityGap);
  const blockingGaps = gaps.filter(
    (gap) => gap.handoff_type === "blocking_test_generation",
  );
  const qualityRisks = gaps.filter(
    (gap) => gap.handoff_type === "case_quality_risk",
  );
  const engineeringContext = gaps.filter(
    (gap) => gap.handoff_type === "engineering_context",
  );

  const verdict: TestabilityVerdict =
    blockingGaps.length > 0
      ? "blocked"
      : qualityRisks.length > 0
        ? "partial"
        : "ready";
  const coverage: EstimatedCaseCoverage =
    verdict === "blocked" ? "低" : verdict === "partial" ? "中" : "高";

  return {
    testability_verdict: verdict,
    estimated_case_coverage: coverage,
    blocking_gap_count: blockingGaps.length,
    quality_risk_count: qualityRisks.length,
    engineering_context_count: engineeringContext.length,
    testable_modules: items.map((item) => ({
      module: itemLocation(item),
      dimension: dimensionLabel(item),
      source_item_id: itemId(item),
      recommended_case_types: caseTypesForItem(item),
    })),
    untestable_gaps: blockingGaps,
    case_quality_risks: qualityRisks,
    engineering_context: engineeringContext,
    acceptance_criteria: items
      .filter(
        (item) =>
          itemText(item).includes("验收") || severityOf(item) === "must",
      )
      .map((item) => ({
        source_item_id: itemId(item),
        location: itemLocation(item),
        criterion: stringValue(item.suggestion) || itemTitle(item),
        status:
          testHandoffType(item) === "blocking_test_generation"
            ? "missing_or_needs_clarification"
            : "candidate",
      })),
  };
}

export function buildZhiquHandoff(
  result: ReviewResult,
  existing?: {
    pmSummary?: PmSummary;
    testabilitySummary?: TestabilitySummary;
  },
): ZhiquHandoff {
  const pmSummary = existing?.pmSummary ?? buildPmSummary(result);
  const testabilitySummary =
    existing?.testabilitySummary ?? buildTestabilitySummary(result);
  const items = sortedItems(sourceItems(result));
  const scenarioMatrix = items.map(scenarioFromItem);
  const edgeCases = scenarioMatrix.filter((row) =>
    row.case_types.includes("boundary"),
  );
  const negativeCases = scenarioMatrix.filter((row) =>
    row.case_types.some((caseType) =>
      ["negative", "exception", "permission"].includes(caseType),
    ),
  );
  const dataRequirements = scenarioMatrix.filter((row) =>
    row.case_types.some((caseType) =>
      ["data", "state_transition"].includes(caseType),
    ),
  );

  return {
    schema_version: "pecker_to_zhiqu.v1",
    source_system: "pecker",
    target_agent: "zhiqu_test_case_agent",
    requirement_id: result.prd_name,
    prd_id: result.prd_name,
    prd_version: [result.prd_name],
    review_id: result.review_id,
    review_mode: reviewModeForHandoff(result.mode),
    pm_verdict: pmSummary.verdict,
    testability_verdict: testabilitySummary.testability_verdict,
    estimated_case_coverage: testabilitySummary.estimated_case_coverage,
    testable_modules: testabilitySummary.testable_modules,
    untestable_gaps: testabilitySummary.untestable_gaps,
    acceptance_criteria: testabilitySummary.acceptance_criteria,
    scenario_matrix: scenarioMatrix,
    edge_cases: edgeCases,
    negative_cases: negativeCases,
    data_requirements: dataRequirements,
    traceability: items.map(traceItem),
    source_trace: {
      workspace: result.workspace,
      prd_files: [result.prd_name],
      prd_hash: "",
      previous_report: "",
      report_paths: {},
    },
    pm_controls: {
      do_not_invent_missing_requirements: true,
      blocked_items_require_pm_input: testabilitySummary.untestable_gaps.map(
        (gap) => gap.id,
      ),
      feedback_options: FEEDBACK_OPTIONS,
    },
  };
}

function sourceItems(result: ReviewResult): ReadonlyArray<ReviewItem> {
  return result.items;
}

function sortedItems(items: ReadonlyArray<ReviewItem>): ReviewItem[] {
  return [...items].sort(prioritySort);
}

function prioritySort(a: ReviewItem, b: ReviewItem): number {
  const severityDelta =
    (SEVERITY_RANK[severityOf(a)] ?? 9) -
    (SEVERITY_RANK[severityOf(b)] ?? 9);
  if (severityDelta !== 0) return severityDelta;
  const confidenceDelta = itemConfidence(b) - itemConfidence(a);
  if (confidenceDelta !== 0) return confidenceDelta;
  return itemId(a).localeCompare(itemId(b));
}

function pmActionItem(item: ReviewItem): PmActionItem {
  const location = itemLocation(item);
  const suggestion =
    stringValue(item.suggestion) || "补充该处缺失的信息，并写清判断口径。";
  const dimKey = normalizeDimensionKey(item.dimension);
  return {
    id: itemId(item),
    severity: severityOf(item) || "-",
    dimension: dimensionLabel(item),
    rule_id: stringValue(item.rule_id),
    location,
    issue: itemTitle(item),
    why_it_matters: DIMENSION_IMPACT[dimKey],
    suggested_change: suggestion,
    prd_patch_label: "可直接粘贴到 PRD",
    prd_patch: `在「${location}」补充：${suggestion}`,
    feedback_options: FEEDBACK_OPTIONS,
  };
}

function testabilityGap(item: ReviewItem): TestabilityGap {
  return {
    ...pmActionItem(item),
    handoff_type: testHandoffType(item),
    case_types_affected: caseTypesForItem(item),
    needs_pm_confirmation: severityOf(item) === "must",
  };
}

function testHandoffType(item: ReviewItem): HandoffType {
  if (isEngineeringItem(item)) return "engineering_context";
  const text = itemText(item).toLowerCase();
  if (
    severityOf(item) === "must" &&
    TESTABILITY_BLOCKING_TERMS.some((term) =>
      text.includes(term.toLowerCase()),
    )
  ) {
    return "blocking_test_generation";
  }
  return "case_quality_risk";
}

function caseTypesForItem(item: ReviewItem): string[] {
  const text = itemText(item).toLowerCase();
  const caseTypes = CASE_TYPE_TERMS.flatMap(([term, caseType]) =>
    text.includes(term.toLowerCase()) ? [caseType] : [],
  );
  const unique = Array.from(new Set(caseTypes));
  return unique.length > 0 ? unique : ["functional"];
}

function scenarioFromItem(item: ReviewItem): ZhiquScenario {
  const action = pmActionItem(item);
  const text = itemText(item);
  return {
    source_item_id: itemId(item),
    module: action.location,
    scenario: action.issue,
    case_types: caseTypesForItem(item),
    preconditions_needed: text.includes("前置") ? "补齐前置条件" : "",
    expected_result_needed: ["验收", "预期", "成功", "失败"].some((term) =>
      text.includes(term),
    )
      ? "补齐预期结果/验收标准"
      : "",
    blocked: testHandoffType(item) === "blocking_test_generation",
    suggested_pm_input: action.suggested_change,
  };
}

function traceItem(item: ReviewItem): ZhiquTraceItem {
  return {
    review_item_id: itemId(item),
    rule_id: stringValue(item.rule_id),
    dimension: dimensionLabel(item),
    location: itemLocation(item),
    severity: severityOf(item) || "-",
  };
}

function countDimensions(
  items: ReadonlyArray<ReviewItem>,
): Array<{ dimension: string; count: number }> {
  const counts = new Map<string, number>();
  for (const item of items) {
    const label = dimensionLabel(item);
    counts.set(label, (counts.get(label) ?? 0) + 1);
  }
  return Array.from(counts.entries())
    .map(([dimension, count]) => ({ dimension, count }))
    .sort((a, b) => b.count - a.count || a.dimension.localeCompare(b.dimension));
}

function itemTitle(item: ReviewItem): string {
  return (
    stringValue(item.problem) ||
    stringValue(item.suggestion) ||
    stringValue(item.id) ||
    "未命名问题"
  );
}

function itemText(item: ReviewItem): string {
  return [
    item.problem,
    item.evidence,
    item.suggestion,
    item.location,
    item.rule_id,
    item.dimension,
  ]
    .map(stringValue)
    .filter(Boolean)
    .join(" ");
}

function itemId(item: ReviewItem): string {
  return stringValue(item.id) || "-";
}

function itemLocation(item: ReviewItem): string {
  return stringValue(item.location) || "未标注位置";
}

function itemConfidence(item: ReviewItem): number {
  const value = item.confidence;
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}

function severityOf(item: ReviewItem): string {
  return stringValue(item.severity).toLowerCase();
}

function dimensionLabel(item: ReviewItem): string {
  return DIMENSION_LABELS[normalizeDimensionKey(item.dimension)];
}

function isEngineeringItem(item: ReviewItem): boolean {
  return normalizeDimensionKey(item.dimension) === "ai_coding";
}

function reviewModeForHandoff(mode: string | undefined): "light" | "deep" {
  return mode === "quick" ? "light" : "deep";
}

function stringValue(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}
