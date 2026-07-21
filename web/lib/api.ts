import type { DecisionInput, ReviewSnapshot, SamplePrd } from "@/lib/types";

const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: {
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
      ...init?.headers,
    },
  });

  if (!response.ok) {
    let message = `Request failed (${response.status})`;
    try {
      const payload = (await response.json()) as { detail?: string };
      if (typeof payload.detail === "string") message = payload.detail;
    } catch {
      // Keep the stable status-based fallback for non-JSON errors.
    }
    throw new Error(message);
  }

  return response.json() as Promise<T>;
}

export async function listSamples(): Promise<SamplePrd[]> {
  const payload = await request<{ samples: SamplePrd[] }>("/api/samples");
  return payload.samples;
}

export function createReview(title: string, content: string) {
  return request<ReviewSnapshot>("/api/reviews", {
    method: "POST",
    body: JSON.stringify({ title, content }),
  });
}

export function updateReviewDecisions(
  reviewId: string,
  decisions: DecisionInput[],
) {
  return request<ReviewSnapshot>(`/api/reviews/${reviewId}/decisions`, {
    method: "POST",
    body: JSON.stringify(decisions),
  });
}

export async function getReviewReport(reviewId: string): Promise<string> {
  const response = await fetch(`${API_BASE_URL}/api/reviews/${reviewId}/report`);
  if (!response.ok) throw new Error(`Report request failed (${response.status})`);
  return response.text();
}
