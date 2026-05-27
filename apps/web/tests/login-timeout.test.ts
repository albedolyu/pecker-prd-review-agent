import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, authApi } from "@/lib/api";

describe("login request timeout", () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("fails fast instead of leaving the login button pending forever", async () => {
    vi.useFakeTimers();

    const fetchMock = vi.fn((_path: string, init?: RequestInit) => {
      return new Promise<Response>((_resolve, reject) => {
        const signal = init?.signal;
        signal?.addEventListener("abort", () => {
          const err = new Error("aborted");
          err.name = "AbortError";
          reject(err);
        });
      });
    });
    vi.stubGlobal("fetch", fetchMock);

    const login = authApi.login("123456", "pm-a").catch((e) => e);

    await vi.advanceTimersByTimeAsync(10_001);
    const result = await Promise.race([login, Promise.resolve("still-pending")]);

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/auth/login",
      expect.objectContaining({
        method: "POST",
        signal: expect.any(AbortSignal),
      }),
    );
    expect(result).toBeInstanceOf(ApiError);
    expect(result).toMatchObject({ status: 0 });
    expect((result as ApiError).message).toContain("服务暂时没有响应");
  });

  it("uses PM-facing copy for server errors instead of raw HTTP status text", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        new Response("{}", {
          status: 500,
          statusText: "Internal Server Error",
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );

    const result = await authApi.login("123456", "pm-a").catch((e) => e);

    expect(result).toBeInstanceOf(ApiError);
    expect(result).toMatchObject({ status: 500 });
    expect((result as ApiError).message).toContain("服务暂时不可用");
    expect((result as ApiError).message).not.toContain("API 500");
    expect((result as ApiError).message).not.toContain("Internal Server Error");
  });

  it("does not expose structured validation JSON as a PM-facing detail", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        Response.json(
          { detail: [{ loc: ["body", "prd_content"], msg: "Field required" }] },
          { status: 422 },
        ),
      ),
    );

    const result = await authApi.login("123456", "pm-a").catch((e) => e);

    expect(result).toBeInstanceOf(ApiError);
    expect(result).toMatchObject({ status: 422, detail: undefined });
    expect((result as ApiError).message).toContain("请求内容不完整");
    expect((result as ApiError).message).not.toContain("loc");
    expect((result as ApiError).message).not.toContain("Field required");
  });

  it("does not leave login-state checks pending forever", async () => {
    vi.useFakeTimers();

    const fetchMock = vi.fn((_path: string, init?: RequestInit) => {
      return new Promise<Response>((_resolve, reject) => {
        init?.signal?.addEventListener("abort", () => {
          const err = new Error("aborted");
          err.name = "AbortError";
          reject(err);
        });
      });
    });
    vi.stubGlobal("fetch", fetchMock);

    const me = authApi.me().catch((e) => e);

    await vi.advanceTimersByTimeAsync(5_001);
    const result = await Promise.race([me, Promise.resolve("still-pending")]);

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/me",
      expect.objectContaining({
        signal: expect.any(AbortSignal),
      }),
    );
    expect(result).toBeInstanceOf(ApiError);
    expect(result).toMatchObject({ status: 0 });
    expect((result as ApiError).message).toContain("暂时无法确认登录状态");
  });
});
