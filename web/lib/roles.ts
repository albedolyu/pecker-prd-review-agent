/**
 * 啄木鸟角色术语映射 — Single Source of Truth
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
  | "editor-in-chief" // 啄木鸟 — 主编(orchestrator,产品名,不在 UI 展示)
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
    label: "主编",
    birdName: "啄木鸟",
    birdEmoji: "🪵",
    responsibility: "主控协调",
    description:
      "啄木鸟本鸟,协调其他编辑。它是产品本身的名字,不在评审 UI 里作为单独卡片出现。",
    frequency: "hidden",
    isWorker: false,
    accentColor: "neutral",
  },
  structure: {
    key: "structure",
    label: "责编",
    birdName: "织布鸟",
    birdEmoji: "🪡",
    responsibility: "结构 / 格式 / 信息密度",
    description:
      "检查 PRD 模板遵循度、Brief 覆盖率、信息完整性、可追溯链。对应 BMAD V-02~V-06,模型 sonnet。",
    frequency: "high",
    isWorker: true,
    accentColor: "blue",
  },
  quality: {
    key: "quality",
    label: "审校",
    birdName: "猫头鹰",
    birdEmoji: "🦉",
    responsibility: "质量 / 逻辑 / 合规",
    description:
      "检查逻辑一致性、实现泄漏、SMART 验证、领域合规、完整性评估。对应 BMAD V-07~V-12,模型 sonnet。",
    frequency: "high",
    isWorker: true,
    accentColor: "amber",
  },
  ai_coding: {
    key: "ai_coding",
    label: "技术编辑",
    birdName: "渡鸦",
    birdEmoji: "🐦‍⬛",
    responsibility: "AI Coding 友好度 / 技术约定",
    description:
      "检查技术约定节、四态 UI、图片相对路径、伪代码、筛选追溯、字段追溯。对应 RC-004~RC-015,模型 opus(需要深度推理)。",
    frequency: "high",
    isWorker: true,
    accentColor: "violet",
  },
  data_quality: {
    key: "data_quality",
    label: "数据核对员",
    birdName: "鸬鹚",
    birdEmoji: "🐟",
    responsibility: "字段映射 / 数值核对",
    description:
      "检查字段映射与物理表 DDL 一致性、数值类字段来源标注、跨表 JOIN 追溯。对应 RC-009~RC-010,模型 sonnet。",
    frequency: "high",
    isWorker: true,
    accentColor: "cyan",
  },
  "final-reviewer": {
    key: "final-reviewer",
    label: "终审",
    birdName: "苍鹰",
    birdEmoji: "🦅",
    responsibility: "meta-review 交叉校验",
    description:
      "4 个并行编辑完成后做交叉校验:撤回低置信度、补充漏报(最多 2 条)、解决冲突。对应后端 goshawk_advisor,不做重审只做审核。",
    frequency: "medium",
    isWorker: false,
    accentColor: "slate",
  },
  "reader-feedback": {
    key: "reader-feedback",
    label: "读者反馈员",
    birdName: "信鸽",
    birdEmoji: "🕊️",
    responsibility: "下游信号采集",
    description:
      "从下游代码仓库读取 PRD 修订情况,反哺到规则权重(EMA 更新)。在评审 UI 不出现,只在后台运行。",
    frequency: "low",
    isWorker: false,
    accentColor: "green",
  },
  "sample-reader": {
    key: "sample-reader",
    label: "试读员",
    birdName: "杜鹃",
    birdEmoji: "🌿",
    responsibility: "评审质量 eval",
    description:
      "对评审报告做 LLM-as-judge 评分,用于 CI 门禁和回归测试。在评审 UI 不出现,只在 CI 层运行。",
    frequency: "low",
    isWorker: false,
    accentColor: "pink",
  },
  archivist: {
    key: "archivist",
    label: "资料员",
    birdName: "鸮鹦",
    birdEmoji: "🦜",
    responsibility: "wiki 知识库维护",
    description:
      "扫描 wiki 目录的完整性、一致性、孤岛页面。在评审 UI 不出现,只在运维层运行。",
    frequency: "low",
    isWorker: false,
    accentColor: "teal",
  },
  "qa-gatekeeper": {
    key: "qa-gatekeeper",
    label: "质检员",
    birdName: "伯劳",
    birdEmoji: "🛡️",
    responsibility: "push 前门禁",
    description:
      "push 前做安全红线(密钥/内网 IP/临时文件)和完整性门禁。在评审 UI 不出现,只在 CI 层运行。",
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
