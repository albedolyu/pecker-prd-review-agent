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
});
