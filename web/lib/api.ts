/**
 * 啄木鸟前端 API 层 — 类型化 fetch wrappers
 *
 * 所有调用都走 `/api/*`,在 dev 模式下由 next.config.ts 的 rewrite 代理到
 * FastAPI :8000,在生产模式由反向代理转发。
 *
 * 认证: HttpOnly cookie `pecker_session`(JWT HS256),自动通过 fetch 的
 * `credentials: "include"` 随请求发送。
 *
 * 错误处理: 非 2xx → 抛 `ApiError`,含 status 和后端 detail。
 *
 * 类型原则:
 * - `ReviewResult` 是 Readonly<...>(对应后端 Opaque Handle),前端任何
 *   改动都会让后端 verify_signature 失败。
 * - `items` 是 `ReadonlyArray<ReviewItem>`,TypeScript 编译时阻止 push/splice。
 */

// ============================================================
// 错误类型
// ============================================================

export class ApiError extends Error {
  readonly status: number;
  readonly detail: string | undefined;

  constructor(status: number, detail: string | undefined, message: string) {
    super(message);
    this.status = status;
    this.detail = detail;
    this.name = "ApiError";
  }
}

// ============================================================
// 底层 fetch wrapper
// ============================================================

interface ApiFetchOptions extends Omit<RequestInit, "body"> {
  body?: unknown;
}

async function apiFetch<T>(path: string, options: ApiFetchOptions = {}): Promise<T> {
  const { body, headers, ...rest } = options;

  const init: RequestInit = {
    credentials: "include",
    ...rest,
    headers: {
      ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
      ...headers,
    },
  };

  if (body !== undefined) {
    init.body = JSON.stringify(body);
  }

  const res = await fetch(path, init);

  if (!res.ok) {
    let detail: string | undefined;
    try {
      const json = (await res.json()) as { detail?: unknown };
      if (typeof json.detail === "string") {
        detail = json.detail;
      } else if (json.detail !== undefined) {
        detail = JSON.stringify(json.detail);
      }
    } catch {
      // body 不是 JSON,忽略
    }
    throw new ApiError(
      res.status,
      detail,
      `API ${res.status} ${res.statusText}${detail ? ": " + detail : ""}`,
    );
  }

  if (res.status === 204) {
    return undefined as T;
  }

  return (await res.json()) as T;
}

// ============================================================
// auth
// ============================================================

export interface LoginResponse {
  status: string;
  reviewer: string;
  readonly: boolean;
  exp_hours: number;
}

export interface MeResponse {
  reviewer: string;
  readonly: boolean;
}

export const authApi = {
  login: (password: string, reviewer: string) =>
    apiFetch<LoginResponse>("/api/auth/login", {
      method: "POST",
      body: { password, reviewer },
    }),
  me: () => apiFetch<MeResponse>("/api/me"),
  logout: () =>
    apiFetch<{ status: string }>("/api/auth/logout", { method: "POST" }),
} as const;

// ============================================================
// workspaces
// ============================================================

export interface Workspace {
  name: string;
  display_name: string;
  path: string;
  has_prd_dir: boolean;
  has_wiki_dir: boolean;
  wiki_page_count: number;
  prd_count: number;
}

export const workspacesApi = {
  list: () => apiFetch<Workspace[]>("/api/workspaces"),
} as const;

// ============================================================
// drafts(浏览器崩溃恢复)
// ============================================================

export interface DraftPayload {
  phase: number;
  prd_name: string;
  prd_content: string;
  raw_materials: string[];
  user_notes: string;
  review_result: ReviewResult | null;
  item_decisions: Record<string, ItemDecision>;
  confirmed_report_markdown: string;
  workspace: string;
}

export interface Draft extends DraftPayload {
  ts: string;
  reviewer: string;
}

export const draftsApi = {
  get: (reviewer: string) =>
    apiFetch<Draft>(`/api/drafts/${encodeURIComponent(reviewer)}`),
  save: (reviewer: string, payload: DraftPayload) =>
    apiFetch<{ status: string; path: string; ts: string }>(
      `/api/drafts/${encodeURIComponent(reviewer)}`,
      { method: "PUT", body: payload },
    ),
  delete: (reviewer: string) =>
    apiFetch<{ status: string }>(
      `/api/drafts/${encodeURIComponent(reviewer)}`,
      { method: "DELETE" },
    ),
} as const;

// ============================================================
// review(Opaque Handle + Precheck + Confirm)
// ============================================================

/**
 * 单条改进项。后端定义是 Dict[str, Any],字段不固定,这里列出的是常见字段,
 * 其他通过 `[key: string]: unknown` 兜底。
 *
 * Phase G #3:加 provenance / cited_by_workers,用来在 Phase 3 卡片上区分
 * "worker 原生输出" / "苍鹰补遗" / "共识被 N 个 worker 同时识别"。
 */
export type ItemProvenance = "worker" | "meta_added" | "meta_dedup_kept";

export interface ReviewItem {
  readonly id: string;
  readonly dimension: string; // 对应 roles.ts 的 RoleKey
  readonly severity?: "must" | "should" | "suggest" | string;
  readonly location?: string;
  readonly problem?: string;
  readonly evidence?: string;
  readonly suggestion?: string;
  readonly confidence?: number;
  /** worker / meta_added / meta_dedup_kept */
  readonly provenance?: ItemProvenance;
  /** 哪些 worker 同时指证了这条 — len ≥ 2 = 共识强信号 */
  readonly cited_by_workers?: ReadonlyArray<string>;
  /** CC-pattern: 苍鹰 gate 链决策日志 */
  readonly gate_log?: ReadonlyArray<{
    type: string;
    pass: boolean;
    detail?: string;
  }>;
  /** CC deep #23: 钉选状态 — compact 时不压缩 */
  readonly pinned?: boolean;
  /**
   * 2026-04-28 step 1b: 跨维度合法 rule_id 标 (review/worker.py:192)
   *
   * 当 worker 引用的 rule_id 在 schema_registry 总表内但不在本维度 dim_rule_ids 时,
   * 保留该 item + 打 cross_boundary=true + confidence -0.3 降权.
   * 与"幻觉 rule_id" (registry 都没有, 直接 drop) 区分.
   *
   * 用途:Phase4ReportV8 渲染时给 cross_boundary item 加视觉标 (step 1c 渲染用).
   */
  readonly cross_boundary?: boolean;
  readonly [key: string]: unknown;
}

export interface ReviewWorkerInfo {
  readonly dimension: string;
  readonly dimension_name: string;
  readonly items_count: number;
  readonly error: string | null;
}

/**
 * 后端 Opaque Handle — 前端拿到后只读,不能改 items 或 signature,
 * 否则 POST /api/review/confirm 会 403。
 */
export interface ReviewResult {
  readonly review_id: string;
  readonly created_at: number;
  readonly reviewer: string;
  readonly workspace: string;
  readonly prd_name: string;
  readonly mode: string;
  readonly items: ReadonlyArray<ReviewItem>;
  readonly workers: ReadonlyArray<ReviewWorkerInfo>;
  readonly usage: Readonly<Record<string, number>>;
  readonly goshawk_summary: Readonly<Record<string, unknown>> | null;
  readonly signature: string;
  /** CC-pattern: 各维度成本归因(dim_key → USD) */
  readonly cost_breakdown?: Readonly<Record<string, number>>;
  /** CC advanced: telemetry 汇总(总时长 + 各 worker 指标) */
  readonly telemetry?: Readonly<{
    total_duration_ms?: number;
    total_cost_usd?: number;
    workers?: Readonly<Record<string, unknown>>;
  }>;
}

export interface PrecheckRequest {
  workspace: string;
  prd_content: string;
  raw_materials?: string[];
}

/**
 * 预检返回 — 对齐 api/routes/review.py::PrecheckResponse
 * - strong/weak: 格式化后的字符串列表,每条形如 `[[page_name]] — 命中 N 个关键词`
 * - gaps: Claude 分析的知识盲区描述
 * - wiki_pages: 页面标题 → 完整 md 内容,Phase 2 调 /api/review/run 时必须原样带回去
 */
export interface PrecheckResponse {
  strong: ReadonlyArray<string>;
  weak: ReadonlyArray<string>;
  gaps: ReadonlyArray<string>;
  wiki_pages: Readonly<Record<string, string>>;
}

export type ReviewMode = "standard" | "quick";

export interface ReviewRunRequest {
  prd_content: string;
  raw_materials?: string[];
  user_notes?: string;
  workspace: string;
  prd_name: string;
  reviewer: string;
  mode: ReviewMode;
  /** Phase 1 precheck 返回的 wiki_pages,原样透传 */
  wiki_pages: Record<string, string>;
}

/**
 * PM 驳回原因 7 分类 — 与后端 models.py:RejectReason 严格对齐。
 * 修改这里时必须同步:
 *   - models.py::RejectReason 枚举
 *   - api/models.py::_VALID_REJECT_REASONS
 *   - components/phases/Phase3ConfirmV8.tsx::REJECT_CATEGORIES
 *   - tests/test_reject_reason_category.py 的 enum drift 守护
 */
export type RejectReason =
  | "good_issue"        // 实际是好问题(PM 手滑 / 改主意)
  | "false_positive"    // 误报, PRD 确实没这问题
  | "known_tradeoff"    // 已知取舍, 业务允许
  | "wiki_missing"      // 知识库缺上下文导致误判
  | "rule_too_strict"   // 规则太严, 不适用本 PRD
  | "impl_detail"       // 实现细节, 不该 PRD 管
  | "model_noise";      // 模型噪音, 无业务意义

/**
 * 用户在 Phase 3 对每个 item 做的决定。
 * action: 接受 / 拒绝 / 编辑;edited_problem 仅在 action=edit 时有意义。
 *
 * reject 必须带 reason_category(7 类下拉), reason 为可选自由文本备注:
 *   - reason_category 缺失 → 后端走 "model_noise" 兜底, 但 EMA 反馈闭环吃错信号
 *   - reason_category 不在 7 种之一 → 后端 422
 */
export interface ItemDecision {
  action: "accept" | "reject" | "edit";
  /** 仅 reject 时有意义, 7 类下拉之一 */
  reason_category?: RejectReason;
  /** 可选自由文本备注(对应后端 reason_note), 老字段名保留兼容报告生成 */
  reason?: string;
  edited_problem?: string;
}

export interface ConfirmRequest {
  review_result: ReviewResult;
  decisions: Record<string, ItemDecision>;
}

/**
 * 对齐后端 /api/review/confirm — 验证 signature + 返回统计 + 后端同源报告 markdown。
 * Phase 4 优先使用 report_markdown,客户端 lib/generateReport.ts 仅作为旧草稿 fallback。
 */
export interface ConfirmResponse {
  status: string;
  review_id: string;
  accepted: number;
  rejected: number;
  edited: number;
  pending: number;
  total: number;
  report_markdown: string;
}

// precheck 和 SSE 一样直连后端,绕开 Next.js dev rewrite 的 30s timeout。
// 48 页 wiki 扫描 + 构建可能 > 30s,rewrite proxy 会提前返 500。
// dev: web/.env.local 里设 NEXT_PUBLIC_SSE_BASE=http://localhost:8000
// prod: 不设,走同源,由反代 / Tunnel 按 path 分流
const API_BASE = process.env.NEXT_PUBLIC_SSE_BASE ?? "";

export const reviewApi = {
  precheck: (req: PrecheckRequest) =>
    apiFetch<PrecheckResponse>(`${API_BASE}/api/review/precheck`, {
      method: "POST",
      body: req,
    }),
  // review.run 走 SSE,在 useReviewStream.ts 里独立实现,这里不暴露
  confirm: (req: ConfirmRequest) =>
    apiFetch<ConfirmResponse>("/api/review/confirm", {
      method: "POST",
      body: req,
    }),
} as const;

// ============================================================
// reports
// ============================================================

export interface ReportFile {
  filename: string;
  size: number;
  mtime: number;
}

export interface SaveToWikiRequest {
  prd_name: string;
  report_markdown: string;
  items_count: number;
  accepted_count: number;
  rejected_count: number;
  edited_count: number;
  peck_score: number;
  peck_label: string;
}

export const reportsApi = {
  list: (workspace: string) =>
    apiFetch<{ reports: ReadonlyArray<ReportFile> }>(
      `/api/reports/${encodeURIComponent(workspace)}`,
    ),
  /** 直接给 <a href> 用,不走 fetch — 浏览器原生下载 */
  downloadUrl: (workspace: string, filename: string) =>
    `/api/reports/${encodeURIComponent(workspace)}/download?filename=${encodeURIComponent(filename)}`,
  saveToWiki: (workspace: string, payload: SaveToWikiRequest) =>
    apiFetch<{ status: string; filename?: string; wiki_path?: string }>(
      `/api/reports/${encodeURIComponent(workspace)}/save-to-wiki`,
      { method: "POST", body: payload },
    ),
} as const;

// ============================================================
// audit(前端事件追踪)
// ============================================================

export interface AuditEvent {
  event: string;
  workspace?: string;
  prd_name?: string;
  extra?: Record<string, unknown>;
}

export const auditApi = {
  log: (ev: AuditEvent) =>
    apiFetch<{ status: string }>("/api/audit", {
      method: "POST",
      body: ev,
    }),
  todayCount: (reviewer: string) =>
    apiFetch<{ reviewer: string; count: number }>(
      `/api/audit/today/${encodeURIComponent(reviewer)}`,
    ),
} as const;

// ============================================================
// feishu
// ============================================================

export interface FeishuSendRequest {
  prd_name: string;
  report_markdown: string;
  chat_id?: string;
}

export const feishuApi = {
  send: (req: FeishuSendRequest) =>
    apiFetch<{ status: string; msg_id?: string }>("/api/feishu/send", {
      method: "POST",
      body: req,
    }),
} as const;
