/**
 * Pecker角色术语映射 — Single Source of Truth
 *
 * 原则(plan "品牌术语重构 方向 3 混合方案"):
 * - UI 显示层: 只用中文职能词(主编/责编/审校/...),零生僻字
 * - 代码/tooltip/about 页: 保留鸟名作为品牌彩蛋
 * - 后端日志: 通过 `key` 字段与并行 worker 的 dim_key 对齐
 *
 * 4 个 worker key(structure/quality/ai_coding/data_quality)必须和后端
 * `parallel_review._DEFAULT_REVIEW_DIMENSIONS` 一致,SSE `worker_done` 事件
 * 会用这些 key 来映射到 RoleCard。
 */

export type RoleKey =
  | "editor-in-chief" // Pecker — 主编(orchestrator,产品名,不在 UI 展示)
  | "structure" // 织布鸟 — 责编(worker)
  | "quality" // 猫头鹰 — 审校(worker)
  | "ai_coding" // 渡鸦 — 技术编辑(worker)
  | "data_quality" // 鸬鹚 — 数据核对员(worker)
  | "final-reviewer" // 苍鹰 — 终审(meta-reviewer)
  | "reader-feedback" // 信鸽 — 读者反馈员(后台)
  | "sample-reader" // 杜鹃 — 试读员(CI 评分)
  | "archivist" // 鸮鹦 — 资料员(wiki 运维)
  | "qa-gatekeeper"; // 伯劳 — 质检员(push 门禁)

export type UIFrequency = "high" | "medium" | "low" | "hidden";

export interface Role {
  /** 后端 dim_key 或服务标识,SSE 事件按此映射 */
  readonly key: RoleKey;
  /** UI 显示的中文职能名(高频文案永远用它) */
  readonly label: string;
  /** 原鸟名(仅 tooltip / about 页 / 代码注释允许出现) */
  readonly birdName: string;
  /** 装饰 emoji(tooltip / about 页用,不在卡片主视觉) */
  readonly birdEmoji: string;
  /** 一句话职责 */
  readonly responsibility: string;
  /** 详细说明(tooltip 第二行 / about 页详情) */
  readonly description: string;
  /** UI 出现频度 */
  readonly frequency: UIFrequency;
  /** 是否是并行 worker(决定是否在 Phase 2 RoleCard 出现) */
  readonly isWorker: boolean;
  /** 前端 accent color token,Phase D 视觉迭代时可能调整 */
  readonly accentColor:
    | "neutral"
    | "blue"
    | "amber"
    | "violet"
    | "cyan"
    | "slate"
    | "green"
    | "pink"
    | "teal"
    | "red";
}

export const ROLES: Readonly<Record<RoleKey, Role>> = Object.freeze({
  "editor-in-chief": {
    key: "editor-in-chief",
    label: "评审准备",
    birdName: "Pecker",
    birdEmoji: "🪵",
    responsibility: "资料接入 / 流程收口",
    description:
      "负责把 PRD、资料库和评审模式准备好,确保本次评审有明确范围、可追溯材料和可交付出口。",
    frequency: "hidden",
    isWorker: false,
    accentColor: "neutral",
  },
  structure: {
    key: "structure",
    label: "业务完整性",
    birdName: "织布鸟",
    birdEmoji: "🪡",
    responsibility: "目标 / 范围 / 验收标准",
    description:
      "检查业务目标是否明确、适用范围是否说清、验收标准是否可判断,避免研发评审时还要反复追问“到底做什么”。",
    frequency: "high",
    isWorker: true,
    accentColor: "blue",
  },
  quality: {
    key: "quality",
    label: "使用体验",
    birdName: "猫头鹰",
    birdEmoji: "🦉",
    responsibility: "流程 / 状态 / 文案",
    description:
      "检查主流程、异常流、空态、提示文案和用户操作是否完整,避免 PRD 只写了理想路径。",
    frequency: "high",
    isWorker: true,
    accentColor: "amber",
  },
  ai_coding: {
    key: "ai_coding",
    label: "实现风险",
    birdName: "渡鸦",
    birdEmoji: "🐦‍⬛",
    responsibility: "依赖 / 边界 / 追溯",
    description:
      "检查上下游依赖、边界条件、降级策略和可追溯信息是否写清,方便研发评估实现成本和风险。",
    frequency: "high",
    isWorker: true,
    accentColor: "violet",
  },
  data_quality: {
    key: "data_quality",
    label: "字段口径",
    birdName: "鸬鹚",
    birdEmoji: "🐟",
    responsibility: "字段映射 / 指标口径",
    description:
      "检查数据源、字段映射、枚举值、指标口径和关联关系是否一致,避免上线后才发现口径对不齐。",
    frequency: "high",
    isWorker: true,
    accentColor: "cyan",
  },
  "final-reviewer": {
    key: "final-reviewer",
    label: "意见收口",
    birdName: "苍鹰",
    birdEmoji: "🦅",
    responsibility: "去重 / 补漏 / 证据检查",
    description:
      "把四个方向的意见合并成一份清单,去掉重复项,弱化证据不足的判断,补上明显遗漏的问题。",
    frequency: "medium",
    isWorker: false,
    accentColor: "slate",
  },
  "reader-feedback": {
    key: "reader-feedback",
    label: "反馈回流",
    birdName: "信鸽",
    birdEmoji: "🕊️",
    responsibility: "接受 / 驳回 / 补充",
    description:
      "记录 PM 对每条意见的接受、驳回和补充原因,帮助后续减少误报、补齐漏报。",
    frequency: "low",
    isWorker: false,
    accentColor: "green",
  },
  "sample-reader": {
    key: "sample-reader",
    label: "样例回归",
    birdName: "杜鹃",
    birdEmoji: "🌿",
    responsibility: "固定样例 / 质量回归",
    description:
      "用固定样例检查规则调整后有没有变差,避免一次优化解决了当前问题却影响其他 PRD。",
    frequency: "low",
    isWorker: false,
    accentColor: "pink",
  },
  archivist: {
    key: "archivist",
    label: "资料维护",
    birdName: "鸮鹦",
    birdEmoji: "🦜",
    responsibility: "知识库 / 过期资料",
    description:
      "维护资料库里的历史 PRD、规则说明和业务定义,把过期、冲突、缺失的资料逐步清理掉。",
    frequency: "low",
    isWorker: false,
    accentColor: "teal",
  },
  "qa-gatekeeper": {
    key: "qa-gatekeeper",
    label: "上线检查",
    birdName: "伯劳",
    birdEmoji: "🛡️",
    responsibility: "权限 / 隐私 / 交付检查",
    description:
      "在团队使用前检查权限、隐私、配置和交付材料,避免把不该外发或不完整的内容带进上线环境。",
    frequency: "low",
    isWorker: false,
    accentColor: "red",
  },
} satisfies Record<RoleKey, Role>);

/**
 * 4 个并行 worker 的展示顺序 — 与后端 parallel_review._DEFAULT_REVIEW_DIMENSIONS
 * 的 staggered 启动顺序一致(structure → quality → ai_coding → data_quality)。
 *
 * Phase 2 RoleCard 网格按此顺序从左到右、从上到下排布。
 */
export const WORKER_ROLE_KEYS: readonly RoleKey[] = Object.freeze([
  "structure",
  "quality",
  "ai_coding",
  "data_quality",
] as const);

/**
 * 通过后端 dim_key(或任意字符串)获取 Role 对象。
 * 主要用途:SSE `worker_done` 事件到达时,把 event.dim_key 映射回 UI 卡片。
 */
export function getRoleByKey(key: string): Role | undefined {
  if (key in ROLES) {
    return ROLES[key as RoleKey];
  }
  return undefined;
}

/**
 * 后端 `item.dimension` 在不同路径下可能有 3 种写法:
 *
 * 1. dim_key 原值:`"structure"` / `"quality"` / `"ai_coding"` / `"data_quality"`
 * 2. `dim["name"]`(parallel_review.py line 831):`"结构层"` / `"质量层"` / `"AI Coding 友好度"` / `"数据质量"`
 * 3. 终审补充(goshawk_advisor.py):`"苍鹰补充"`(兼容 legacy) / `"终审补充"`
 *
 * 这个表把任一写法一次性归一化到 RoleKey,让 Phase 3 Tabs 和 generateReport
 * 都只需要处理 RoleKey,避免 UI 里泄漏出 `结构层` / `苍鹰补充` 这种原始字符串。
 */
const DIMENSION_ALIAS: Readonly<Record<string, RoleKey>> = {
  // dim_key 原值(理论 API 契约)
  structure: "structure",
  quality: "quality",
  ai_coding: "ai_coding",
  data_quality: "data_quality",
  // dim["name"] 中文长名(parallel_review 实际写入 item.dimension)
  结构层: "structure",
  质量层: "quality",
  "AI Coding 友好度": "ai_coding",
  数据质量: "data_quality",
  // 终审补充项(goshawk_advisor)
  苍鹰补充: "final-reviewer",
  终审补充: "final-reviewer",
} as const;

/**
 * 把任意 dimension 字符串归一化到 RoleKey。找不到就回退到 "structure"
 * (而不是返回 undefined),避免 Phase 3 Tabs 出现空 key。
 */
export function normalizeDimensionKey(dim: string | undefined | null): RoleKey {
  if (!dim) return "structure";
  return DIMENSION_ALIAS[dim] ?? "structure";
}

/**
 * 所有"在 Phase 2 RoleCard 里出场"的角色 — 即 4 个 worker + 1 个 final-reviewer。
 * 前端 ProgressRail 和 RoleCard 网格用它做遍历。
 */
export const VISIBLE_REVIEW_ROLES: readonly Role[] = Object.freeze([
  ROLES.structure,
  ROLES.quality,
  ROLES.ai_coding,
  ROLES.data_quality,
  ROLES["final-reviewer"],
]);
