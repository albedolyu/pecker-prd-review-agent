import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, test, vi } from "vitest";

import { ReviewWorkspace } from "@/components/review-workspace";
import {
  createReview,
  getReviewReport,
  listSamples,
  updateReviewDecisions,
} from "@/lib/api";

vi.mock("@/lib/api", () => ({
  createReview: vi.fn(),
  getReviewReport: vi.fn(),
  listSamples: vi.fn(),
  updateReviewDecisions: vi.fn(),
}));

const samples = [
  {
    id: "team-notes-search",
    label: "Lantern Notes Search (Synthetic demo)",
    description: "A deliberately incomplete collaborative-notes search PRD.",
    synthetic: true,
    content: "# Lantern Notes Search\n\nRanking details are TBD.",
  },
  {
    id: "export-center",
    label: "Atlas Export Center (Synthetic demo)",
    description: "A more complete export workflow.",
    synthetic: true,
    content: "# Atlas Export Center\n\nRetention is TBD.",
  },
];

const findings = [
  {
    id: "finding-structure",
    worker: "structure",
    category: "structure",
    severity: "high" as const,
    title: "Acceptance criteria are missing",
    evidence: "Ranking details are TBD.",
    line: 3,
    recommendation: "Define measurable ranking acceptance criteria.",
    confidence: 0.94,
    decision: null,
  },
  {
    id: "finding-product",
    worker: "product_quality",
    category: "product quality",
    severity: "medium" as const,
    title: "Failure state is undefined",
    evidence: "What should a user see when indexing fails?",
    line: 9,
    recommendation: "Specify the indexing failure experience.",
    confidence: 0.82,
    decision: null,
  },
  {
    id: "finding-data",
    worker: "data_quality",
    category: "data quality",
    severity: "low" as const,
    title: "Result fields need a contract",
    evidence: "Which result fields are required?",
    line: 10,
    recommendation: "List required fields and nullability.",
    confidence: 0.76,
    decision: null,
  },
];

const review = {
  review_id: "review-demo",
  title: "Lantern Notes Search (Synthetic demo)",
  content: samples[0].content,
  status: "completed" as const,
  mode: "deterministic-demo" as const,
  created_at: "2026-07-21T00:00:00Z",
  findings,
  worker_runs: {
    structure: { status: "completed" as const, output: [findings[0]], confidence: 0.94, tokens_used: 0 },
    product_quality: { status: "completed" as const, output: [findings[1]], confidence: 0.82, tokens_used: 0 },
    ai_coding_readiness: { status: "completed" as const, output: [], confidence: 0.7, tokens_used: 0 },
    data_quality: { status: "completed" as const, output: [findings[2]], confidence: 0.76, tokens_used: 0 },
  },
  advisor: { gaps: ["Clarify how stale index results are communicated."] },
};

const mockedListSamples = vi.mocked(listSamples);
const mockedCreateReview = vi.mocked(createReview);
const mockedUpdateDecisions = vi.mocked(updateReviewDecisions);
const mockedGetReport = vi.mocked(getReviewReport);

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((promiseResolve, promiseReject) => {
    resolve = promiseResolve;
    reject = promiseReject;
  });
  return { promise, reject, resolve };
}

function decidedReview(
  id: string,
  decision: { action: "accept" | "reject" | "edit"; edited_title?: string; edited_recommendation?: string },
) {
  return {
    ...review,
    findings: review.findings.map((finding) =>
      finding.id === id ? { ...finding, decision } : finding,
    ),
  };
}

async function renderLoadedWorkspace() {
  mockedListSamples.mockResolvedValue(samples);
  const user = userEvent.setup();
  render(<ReviewWorkspace />);
  await screen.findByText(samples[0].label);
  await user.click(screen.getByRole("button", { name: /load lantern notes search/i }));
  return user;
}

async function startReview() {
  const user = await renderLoadedWorkspace();
  mockedCreateReview.mockResolvedValue(review);
  await user.click(screen.getByRole("button", { name: /start specialist review/i }));
  await screen.findByText(review.findings[0].title);
  return user;
}

beforeEach(() => {
  vi.resetAllMocks();
});

describe("ReviewWorkspace", () => {
  test("loads a synthetic sample into the input workspace", async () => {
    mockedListSamples.mockResolvedValue(samples);
    const user = userEvent.setup();
    render(<ReviewWorkspace />);
    await screen.findByText(samples[0].label);

    expect(screen.getByLabelText(/prd title/i)).toHaveValue("");
    await user.click(screen.getByRole("button", { name: /load lantern notes search/i }));

    expect(screen.getByLabelText(/prd title/i)).toHaveValue(samples[0].label);
    expect(screen.getByLabelText(/prd content/i)).toHaveValue(samples[0].content);
    expect(screen.getByText(/synthetic data/i)).toBeInTheDocument();
  });

  test("moves through Input, Specialist Review, PM Confirmation, and Report", async () => {
    let finishReview: (value: typeof review) => void = () => undefined;
    mockedListSamples.mockResolvedValue(samples);
    mockedCreateReview.mockReturnValue(
      new Promise((resolve) => {
        finishReview = resolve;
      }),
    );
    mockedGetReport.mockResolvedValue("# Confirmed Review");
    const user = userEvent.setup();
    render(<ReviewWorkspace />);
    await screen.findByText(samples[0].label);
    await user.click(screen.getByRole("button", { name: /load lantern notes search/i }));

    await user.click(screen.getByRole("button", { name: /start specialist review/i }));
    expect(screen.getByTestId("phase-specialist-review")).toHaveAttribute("data-status", "current");
    expect(screen.getByTestId("phase-specialist-review")).toHaveAttribute("aria-current", "step");
    expect(screen.getByLabelText(/prd title/i)).toBeDisabled();
    expect(screen.getByRole("button", { name: /load atlas export center/i })).toBeDisabled();
    expect(screen.getByRole("button", { name: /running specialists/i })).toBeDisabled();
    finishReview(review);
    await screen.findByText(review.findings[0].title);
    expect(screen.getByTestId("phase-pm-confirmation")).toHaveAttribute("data-status", "current");
    expect(screen.getByTestId("phase-pm-confirmation")).toHaveAttribute("aria-current", "step");

    mockedUpdateDecisions.mockResolvedValue(decidedReview("finding-structure", { action: "accept" }));
    await user.click(screen.getByRole("button", { name: /accept acceptance criteria are missing/i }));
    await user.click(screen.getByRole("button", { name: /generate confirmed report/i }));
    expect(await screen.findByText("# Confirmed Review")).toBeInTheDocument();
    expect(screen.getByTestId("phase-report")).toHaveAttribute("data-status", "current");
  });

  test("shows finding and decision counts computed from the current review", async () => {
    await startReview();

    expect(screen.getByText("3 findings")).toBeInTheDocument();
    expect(screen.getByText("0 of 3 decided")).toBeInTheDocument();

    mockedUpdateDecisions.mockResolvedValue(decidedReview("finding-structure", { action: "accept" }));
    await userEvent.click(screen.getByRole("button", { name: /accept acceptance criteria are missing/i }));
    expect(await screen.findByText("1 of 3 decided")).toBeInTheDocument();
  });

  test("accepts and rejects findings through partial decision requests", async () => {
    const user = await startReview();
    mockedUpdateDecisions
      .mockResolvedValueOnce(decidedReview("finding-structure", { action: "accept" }))
      .mockResolvedValueOnce({
        ...decidedReview("finding-product", { action: "reject" }),
        findings: review.findings.map((finding) => {
          if (finding.id === "finding-structure") return { ...finding, decision: { action: "accept" as const } };
          if (finding.id === "finding-product") return { ...finding, decision: { action: "reject" as const } };
          return finding;
        }),
      });

    await user.click(screen.getByRole("button", { name: /accept acceptance criteria are missing/i }));
    expect(await screen.findByText("Accepted")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /reject failure state is undefined/i }));
    expect(await screen.findByText("Rejected")).toBeInTheDocument();

    expect(mockedUpdateDecisions).toHaveBeenNthCalledWith(1, "review-demo", [
      { finding_id: "finding-structure", action: "accept" },
    ]);
    expect(mockedUpdateDecisions).toHaveBeenNthCalledWith(2, "review-demo", [
      { finding_id: "finding-product", action: "reject" },
    ]);
  });

  test("edits a finding with keyboard-operable labelled fields", async () => {
    const user = await startReview();
    const edited = decidedReview("finding-data", {
      action: "edit",
      edited_title: "Define the result schema",
      edited_recommendation: "Document required fields, types, and nullability.",
    });
    mockedUpdateDecisions.mockResolvedValue(edited);

    await user.click(screen.getByRole("button", { name: /edit result fields need a contract/i }));
    const editor = screen.getByRole("dialog", { name: /edit finding/i });
    await user.clear(within(editor).getByLabelText(/finding title/i));
    await user.type(within(editor).getByLabelText(/finding title/i), "Define the result schema");
    await user.clear(within(editor).getByLabelText(/recommendation/i));
    await user.type(within(editor).getByLabelText(/recommendation/i), "Document required fields, types, and nullability.");
    await user.click(within(editor).getByRole("button", { name: /save edit/i }));

    expect(await screen.findByText("Define the result schema")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /edit define the result schema/i })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /edit result fields need a contract/i })).not.toBeInTheDocument();
    expect(mockedUpdateDecisions).toHaveBeenCalledWith("review-demo", [
      {
        finding_id: "finding-data",
        action: "edit",
        edited_title: "Define the result schema",
        edited_recommendation: "Document required fields, types, and nullability.",
      },
    ]);
  });

  test("recovers after the sample API fails", async () => {
    mockedListSamples
      .mockRejectedValueOnce(new Error("Sample service unavailable"))
      .mockResolvedValueOnce(samples);
    const user = userEvent.setup();
    render(<ReviewWorkspace />);

    expect(await screen.findByRole("alert")).toHaveTextContent("Sample service unavailable");
    await user.click(screen.getByRole("button", { name: /retry loading samples/i }));
    expect(await screen.findByText(samples[0].label)).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  test("keeps the PRD available and offers retry after review API failure", async () => {
    const user = await renderLoadedWorkspace();
    mockedCreateReview
      .mockRejectedValueOnce(new Error("Review service unavailable"))
      .mockResolvedValueOnce(review);

    await user.click(screen.getByRole("button", { name: /start specialist review/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Review service unavailable");
    expect(screen.getByLabelText(/prd content/i)).toHaveValue(samples[0].content);
    await user.click(screen.getByRole("button", { name: /retry specialist review/i }));
    expect(await screen.findByText(review.findings[0].title)).toBeInTheDocument();
  });

  test("renders the backend Markdown report from confirmed decisions", async () => {
    const user = await startReview();
    mockedUpdateDecisions.mockResolvedValue(decidedReview("finding-structure", { action: "accept" }));
    mockedGetReport.mockResolvedValue(
      "# Lantern Notes Search - Confirmed Review\n\n## 1. Acceptance criteria are missing",
    );

    await user.click(screen.getByRole("button", { name: /accept acceptance criteria are missing/i }));
    await user.click(screen.getByRole("button", { name: /generate confirmed report/i }));

    expect(await screen.findByText(/# Lantern Notes Search - Confirmed Review/)).toBeInTheDocument();
    expect(mockedGetReport).toHaveBeenCalledWith("review-demo");
  });

  test("keeps one decision operation exclusive until its own deferred request settles", async () => {
    const user = await startReview();
    const mutation = deferred<ReturnType<typeof decidedReview>>();
    mockedUpdateDecisions.mockReturnValue(mutation.promise);

    await user.click(screen.getByRole("button", { name: /accept acceptance criteria are missing/i }));

    const conflictingDecision = screen.getByRole("button", { name: /reject failure state is undefined/i });
    expect(conflictingDecision).toBeDisabled();
    expect(screen.getByRole("button", { name: /load atlas export center/i })).toBeDisabled();
    expect(screen.getByLabelText(/prd title/i)).toBeDisabled();
    expect(screen.getByLabelText(/prd content/i)).toBeDisabled();
    expect(screen.getByRole("button", { name: /start specialist review/i })).toBeDisabled();
    expect(screen.getByRole("button", { name: /generate confirmed report/i })).toBeDisabled();

    await user.click(conflictingDecision);
    expect(mockedUpdateDecisions).toHaveBeenCalledTimes(1);
    expect(conflictingDecision).toBeDisabled();

    await act(async () => mutation.resolve(decidedReview("finding-structure", { action: "accept" })));
    expect(await screen.findByText("Accepted")).toBeInTheDocument();
    expect(conflictingDecision).toBeEnabled();
  });

  test("ignores a deferred mutation snapshot for a different review", async () => {
    const user = await startReview();
    const mutation = deferred<ReturnType<typeof decidedReview>>();
    mockedUpdateDecisions.mockReturnValue(mutation.promise);

    await user.click(screen.getByRole("button", { name: /accept acceptance criteria are missing/i }));
    await act(async () => mutation.resolve({
      ...decidedReview("finding-structure", { action: "accept" }),
      review_id: "review-stale",
    }));

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /accept acceptance criteria are missing/i })).toBeEnabled();
    });
    expect(screen.getByText("0 of 3 decided")).toBeInTheDocument();
    expect(screen.queryByText("Accepted")).not.toBeInTheDocument();
  });

  test("keeps the workspace mutually locked while a report request is pending", async () => {
    const user = await startReview();
    const pendingReport = deferred<string>();
    mockedGetReport.mockReturnValue(pendingReport.promise);

    await user.click(screen.getByRole("button", { name: /generate confirmed report/i }));

    expect(screen.getByRole("button", { name: /load atlas export center/i })).toBeDisabled();
    expect(screen.getByLabelText(/prd title/i)).toBeDisabled();
    expect(screen.getByRole("button", { name: /start specialist review/i })).toBeDisabled();
    expect(screen.getByRole("button", { name: /accept acceptance criteria are missing/i })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: /accept acceptance criteria are missing/i }));
    expect(mockedUpdateDecisions).not.toHaveBeenCalled();

    await act(async () => pendingReport.resolve("# Current confirmed report"));
    expect(await screen.findByText("# Current confirmed report")).toBeInTheDocument();
  });

  test("shows edit failures inside the dialog without losing draft fields", async () => {
    const user = await startReview();
    mockedUpdateDecisions.mockRejectedValue(new Error("Decision service unavailable"));

    await user.click(screen.getByRole("button", { name: /edit result fields need a contract/i }));
    const editor = screen.getByRole("dialog", { name: /edit finding/i });
    const titleField = within(editor).getByLabelText(/finding title/i);
    const recommendationField = within(editor).getByLabelText(/recommendation/i);
    await user.clear(titleField);
    await user.type(titleField, "Keep this draft title");
    await user.clear(recommendationField);
    await user.type(recommendationField, "Keep this draft recommendation.");
    await user.click(within(editor).getByRole("button", { name: /save edit/i }));

    expect(await within(editor).findByRole("alert")).toHaveTextContent("Decision service unavailable");
    expect(titleField).toHaveValue("Keep this draft title");
    expect(recommendationField).toHaveValue("Keep this draft recommendation.");
    expect(editor).toBeInTheDocument();
  });

  test("traps keyboard focus, closes on Escape, and restores the Edit trigger", async () => {
    const user = await startReview();
    const editTrigger = screen.getByRole("button", { name: /edit result fields need a contract/i });
    await user.click(editTrigger);
    const editor = screen.getByRole("dialog", { name: /edit finding/i });
    const titleField = within(editor).getByLabelText(/finding title/i);
    const closeButton = within(editor).getByRole("button", { name: /close edit finding/i });
    const saveButton = within(editor).getByRole("button", { name: /save edit/i });

    expect(titleField).toHaveFocus();
    saveButton.focus();
    await user.tab();
    expect(closeButton).toHaveFocus();
    await user.tab({ shift: true });
    expect(saveButton).toHaveFocus();

    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog", { name: /edit finding/i })).not.toBeInTheDocument();
    expect(editTrigger).toHaveFocus();
  });
});
