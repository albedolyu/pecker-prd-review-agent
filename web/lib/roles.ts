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
      "整个编辑部以它命名,但它从不亲自写稿。它的工作是分稿、催稿、把六位编辑的判断收拢成一份能交付的报告。你在 UI 里看不到它单独出现,因为它就是这个产品本身 — 所有编辑能开工,是因为有人在背后把节奏盯住。",
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
      "像织布一样,它在意每一根经线纬线是否对齐。它读 PRD 的方式很轴:章节是不是齐全、字段是不是密、Brief 里答应过的事有没有兑现、每条需求能不能往上追到源头。结构松一寸,它就要拉你回来重新缝一遍。",
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
      "它读得慢、读得细,擅长在你以为说圆了的地方挑出一个矛盾。它会问:这条需求 SMART 吗,逻辑闭环吗,是不是悄悄把实现方案写进了需求里,业务规则有没有踩到合规线。猫头鹰夜里看得清,它在文档里也是。",
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
      "渡鸦聪明,会用工具,也偏执地讲究。它专门替下游写代码的同事把关:技术约定节有没有写、四态 UI 有没有覆盖、关键流程有没有伪代码、筛选条件能不能追到字段。这一类活儿费脑子,所以这位编辑用的是 Opus。",
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
      "鸬鹚下水捕鱼,从不空手。它的活儿是把 PRD 里的字段一条条拎进数据库对照:DDL 里有没有这一列、数值字段的口径来自哪张表、跨表 JOIN 有没有写漏关联键。它出手通常意味着 — 你以为对的字段,其实并不存在。",
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
      "苍鹰在四位编辑都出完稿之后才登场。它不重新审,只做一件事:把四份结论摆在一起交叉看,撤掉证据不足的判断,补上明显被漏掉的(最多两条,它克制),把冲突的部分判一判。它飞得高,是因为它要看全局。",
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
      "信鸽永远在两头之间往返:它从下游代码仓库取回 PRD 实际被改成了什么样,再把这些信号用 EMA 算法慢慢喂回我们的规则库。哪些规则常常说中、哪些常常误伤,它都记着。你看不到它,但你下次评审的权重,是它一趟趟驮回来的。",
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
      "杜鹃干一件有点冒犯的事:在报告交付之前,它先以读者的身份把这份评审本身打一遍分。哪条结论站得住、哪条像凑数,它都打。这份分会进 CI 门禁 — 评审写得太敷衍,它会让流水线红一下。",
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
      "鸮鹦不会飞,在地上慢悠悠地走,但它把整个 workspace 的资料室记得最清楚。它扫 wiki 找孤岛页面、断链、过期内容、彼此打架的说法。当编辑们需要查'我们之前是怎么定义这个的',它早就把答案分门别类放好了。",
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
      "伯劳有把东西串起来挂好的习惯,叫'伯劳挂虫'。它在 push 前最后扫一遍:有没有密钥泄出去、有没有内网 IP、有没有临时文件混进提交,顺便再确认一次完整性门禁。看着不起眼,但它一拦,就是把麻烦挡在了门外。",
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
