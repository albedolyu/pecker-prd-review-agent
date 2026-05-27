import type {
  ItemDecision,
  PrecheckResponse,
  ReviewResult,
} from "./api";

export const DEMO_PRD_NAME = "演示样例-积分抵扣.md";
export const DEMO_WORKSPACE = "workspace-points-payment";

export const DEMO_PRD_CONTENT = `# 积分抵扣能力 PRD

## 背景
用户在购买会员或增值服务时,可以使用账户积分抵扣部分应付金额。

## 范围
- 支持下单页展示可用积分与可抵扣金额
- 支持支付前锁定本次使用的积分
- 支持支付失败后返还锁定积分
- 支持订单取消后释放积分

## 规则
- 100 积分抵扣 1 元
- 单笔订单最多抵扣应付金额的 20%
- 积分抵扣后仍需满足最低支付 0.01 元
`;

export const DEMO_PRECHECK: PrecheckResponse = {
  strong: [
    "[[积分账户规则]] — 命中 6 个关键词",
    "[[订单支付状态机]] — 命中 5 个关键词",
    "[[退款与补偿口径]] — 命中 3 个关键词",
  ],
  weak: [
    "[[会员购买流程]] — 只覆盖下单入口",
    "[[财务对账字段]] — 只提到支付金额,未提积分抵扣金额",
  ],
  gaps: [
    "缺少积分锁定失败时的页面提示和重试口径",
    "缺少部分退款时积分返还比例说明",
    "缺少风控拦截时订单与积分状态的最终一致性要求",
  ],
  wiki_pages: {
    "积分账户规则": "积分余额、冻结积分、解冻积分、扣减流水必须可追溯。",
    "订单支付状态机": "订单包含待支付、支付中、支付成功、支付失败、已取消状态。",
  },
};

export const DEMO_WIKI_PAGES = DEMO_PRECHECK.wiki_pages;

export const DEMO_REVIEW_RESULT: ReviewResult = {
  review_id: "demo_review_points_payment",
  created_at: 1_777_777_777,
  reviewer: "演示用户",
  workspace: DEMO_WORKSPACE,
  prd_name: DEMO_PRD_NAME,
  mode: "standard",
  items: [
    {
      id: "DEMO-001",
      dimension: "structure",
      severity: "must",
      location: "积分锁定流程",
      problem: "PRD 写了支付前锁定积分,但没有说明锁定失败后订单是否继续创建、用户是否可以重试。",
      evidence: "支持支付前锁定本次使用的积分",
      suggestion: "补充锁定失败时的订单状态、页面提示、重试入口和埋点口径。",
      confidence: 0.92,
      rule_id: "rule_state_exception",
      provenance: "worker",
      cited_by_workers: ["structure", "quality"],
      gate_log: [
        { type: "evidence_verify", pass: true, detail: "PRD 中有锁定动作,缺失败分支" },
      ],
    },
    {
      id: "DEMO-002",
      dimension: "data_quality",
      severity: "must",
      location: "抵扣金额字段",
      problem: "缺少订单侧和支付侧字段定义,后续对账无法区分现金支付金额、积分抵扣金额和优惠券金额。",
      evidence: "100 积分抵扣 1 元;单笔订单最多抵扣应付金额的 20%",
      suggestion: "补充字段表: original_amount、points_used、points_deduction_amount、cash_pay_amount。",
      confidence: 0.88,
      rule_id: "rule_data_contract",
      provenance: "worker",
      cited_by_workers: ["data_quality", "ai_coding"],
      gate_log: [
        { type: "evidence_verify", pass: true, detail: "金额规则明确,字段承接缺失" },
      ],
    },
    {
      id: "DEMO-003",
      dimension: "quality",
      severity: "should",
      location: "支付失败返还",
      problem: "只写了支付失败后返还锁定积分,但没有说明返还时效和用户可见状态。",
      evidence: "支持支付失败后返还锁定积分",
      suggestion: "补充返还时效,例如实时返还;若失败需展示处理中并给出客服兜底。",
      confidence: 0.81,
      rule_id: "rule_user_feedback",
      provenance: "worker",
      cited_by_workers: ["quality"],
      gate_log: [
        { type: "evidence_verify", pass: true, detail: "返还动作存在,体验口径不足" },
      ],
    },
    {
      id: "DEMO-004",
      dimension: "ai_coding",
      severity: "must",
      location: "订单取消与支付回调并发",
      problem: "订单取消释放积分与支付成功回调可能并发,PRD 没有说明最终以哪个状态为准。",
      evidence: "支持订单取消后释放积分",
      suggestion: "补充幂等规则和状态优先级:支付成功优先于取消释放,重复回调不重复扣减积分。",
      confidence: 0.86,
      rule_id: "rule_idempotency",
      provenance: "worker",
      cited_by_workers: ["ai_coding", "structure"],
      gate_log: [
        { type: "evidence_verify", pass: true, detail: "存在取消释放,未覆盖并发回调" },
      ],
    },
    {
      id: "DEMO-005",
      dimension: "final-reviewer",
      severity: "should",
      location: "织雀交接",
      problem: "当前 PRD 可生成主流程测试用例,但退款、并发、风控拦截三个场景仍需要 PM 补口径。",
      evidence: "缺少部分退款时积分返还比例说明;缺少风控拦截时订单与积分状态的最终一致性要求",
      suggestion: "在交接织雀前补 3 条验收标准:部分退款、取消并发、风控拦截。",
      confidence: 0.79,
      rule_id: "rule_testability",
      provenance: "meta_added",
      cited_by_workers: ["final-reviewer"],
      gate_log: [
        { type: "evidence_verify", pass: true, detail: "来自预检盲区和多维意见汇总" },
      ],
    },
  ],
  workers: [
    { dimension: "structure", dimension_name: "结构", items_count: 1, error: null },
    { dimension: "data_quality", dimension_name: "数据质量", items_count: 1, error: null },
    { dimension: "quality", dimension_name: "体验", items_count: 1, error: null },
    { dimension: "ai_coding", dimension_name: "风险", items_count: 1, error: null },
  ],
  usage: { total_tokens: 12400, total_cost_usd: 0.42 },
  goshawk_summary: {
    added: 1,
    removed: 0,
    merged_to_facet: 1,
    n_samples: 3,
    n_samples_succeeded: 3,
    retention_kind_dist: { unanimous: 2, majority: 2, minority: 1 },
    minority_kept: 1,
  },
  signature: "demo-signature-not-for-submit",
};

export const DEMO_DECISIONS: Record<string, ItemDecision> = {
  "DEMO-001": { action: "accept" },
  "DEMO-002": {
    action: "edit",
    edited_problem: "补充订单、支付、对账三侧的积分抵扣字段,避免后续金额口径不一致。",
  },
  "DEMO-003": { action: "accept" },
  "DEMO-004": {
    action: "reject",
    reason_category: "known_tradeoff",
    reason: "演示中保留一条拒绝样例,用于查看反馈闭环。",
  },
  "DEMO-005": { action: "accept" },
};

export const DEMO_REPORT_MARKDOWN = `# 演示模式评审报告

> 这是一份前端演示报告,用于查看Pecker完整 UI 流程,不会提交到后端。

## 结论

建议补充后再进入开发。当前样例有 3 条必须修和 2 条建议修,主要风险集中在状态异常、字段口径和织雀测试用例交接。

## PM 下一步

1. 补积分锁定失败、支付失败返还、订单取消并发的验收标准。
2. 补订单、支付、对账三侧金额字段表。
3. 将阻塞缺口同步给织雀测试用例 agent。
`;
