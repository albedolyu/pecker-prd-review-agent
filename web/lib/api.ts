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
 * 其他通过 `[key: string]: unknown` 兜底。Phase C 根据实际报告细化。
 */
export interface ReviewItem {
  readonly id: string;
  readonly dimension: string; // 对应 roles.ts 的 RoleKey
  readonly severity?: "must" | "should" | "suggest" | string;
  readonly location?: string;
  readonly problem?: string;
  readonly evidence?: string;
  readonly suggestion?: string;
  readonly confidence?: number;
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
}

export interface PrecheckRequest {
  workspace: string;
  prd_content: string;
  prd_name: string;
  reviewer: string;
}

export interface PrecheckResponse {
  wiki_hits: ReadonlyArray<{
    title: string;
    path: string;
    snippet: string;
    score?: number;
  }>;
  suggested_notes: string;
  detected_mode: string;
}

export interface ReviewRunRequest {
  workspace: string;
  prd_content: string;
  prd_name: string;
  reviewer: string;
  mode: "fast" | "strict" | string;
  user_notes?: string;
}

/**
 * 用户在 Phase 3 对每个 item 做的决定。
 * action: 接受 / 拒绝 / 编辑;edited_problem 仅在 action=edit 时有意义。
 */
export interface ItemDecision {
  action: "accept" | "reject" | "edit";
  reason?: string;
  edited_problem?: string;
}

export interface ConfirmRequest {
  review_result: ReviewResult;
  decisions: Record<string, ItemDecision>;
}

export interface ConfirmResponse {
  status: string;
  report_files: ReadonlyArray<{
    kind: "full" | "summary" | "json" | string;
    filename: string;
  }>;
}

export const reviewApi = {
  precheck: (req: PrecheckRequest) =>
    apiFetch<PrecheckResponse>("/api/review/precheck", {
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
  kind: string;
}

export const reportsApi = {
  list: (workspace: string) =>
    apiFetch<ReadonlyArray<ReportFile>>(
      `/api/reports/${encodeURIComponent(workspace)}`,
    ),
  download: (workspace: string, filename: string) => {
    const url = `/api/reports/${encodeURIComponent(workspace)}/download?filename=${encodeURIComponent(filename)}`;
    return url; // 直接给 <a href> 用,不走 fetch
  },
  saveToWiki: (workspace: string, filename: string) =>
    apiFetch<{ status: string; wiki_path?: string }>(
      `/api/reports/${encodeURIComponent(workspace)}/save-to-wiki`,
      { method: "POST", body: { filename } },
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
  workspace: string;
  report_filename: string;
  reviewer?: string;
  prd_name?: string;
}

export const feishuApi = {
  send: (req: FeishuSendRequest) =>
    apiFetch<{ status: string; chat_id?: string }>("/api/feishu/send", {
      method: "POST",
      body: req,
    }),
} as const;
