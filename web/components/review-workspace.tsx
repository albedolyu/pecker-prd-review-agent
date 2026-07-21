"use client";

import {
  type KeyboardEvent,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import {
  createReview,
  getReviewReport,
  listSamples,
  updateReviewDecisions,
} from "@/lib/api";
import type {
  DecisionAction,
  DecisionInput,
  Finding,
  ReviewSnapshot,
  SamplePrd,
} from "@/lib/types";

const phases = ["Input", "Specialist Review", "PM Confirmation", "Report"] as const;

function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : "Something went wrong. Please retry.";
}

function phaseId(label: (typeof phases)[number]) {
  return label.toLowerCase().replaceAll(" ", "-");
}

function displayTitle(finding: Finding) {
  return finding.decision?.edited_title ?? finding.title;
}

function displayRecommendation(finding: Finding) {
  return finding.decision?.edited_recommendation ?? finding.recommendation;
}

type OperationKind = "decision" | "report" | "review";

interface OperationToken {
  generation: number;
  id: number;
  kind: OperationKind;
  reviewId?: string;
}

export function ReviewWorkspace() {
  const [samples, setSamples] = useState<SamplePrd[]>([]);
  const [samplesLoading, setSamplesLoading] = useState(true);
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");
  const [review, setReview] = useState<ReviewSnapshot | null>(null);
  const [report, setReport] = useState<string | null>(null);
  const [activeOperation, setActiveOperation] = useState<OperationToken | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [failedAction, setFailedAction] = useState<"samples" | "review" | null>(null);
  const [editing, setEditing] = useState<Finding | null>(null);
  const [editError, setEditError] = useState<string | null>(null);
  const [editedTitle, setEditedTitle] = useState("");
  const [editedRecommendation, setEditedRecommendation] = useState("");
  const activeOperationRef = useRef<OperationToken | null>(null);
  const operationIdRef = useRef(0);
  const workspaceGenerationRef = useRef(0);
  const currentReviewIdRef = useRef<string | null>(null);
  const dialogRef = useRef<HTMLElement | null>(null);
  const editTitleRef = useRef<HTMLInputElement | null>(null);
  const editTriggerRef = useRef<HTMLButtonElement | null>(null);

  const busy = activeOperation !== null;
  const isReviewing = activeOperation?.kind === "review";
  const isReporting = activeOperation?.kind === "report";

  function beginOperation(
    kind: OperationKind,
    options: { newGeneration?: boolean; reviewId?: string } = {},
  ): OperationToken | null {
    if (activeOperationRef.current) return null;
    if (options.newGeneration) workspaceGenerationRef.current += 1;
    const operation = {
      generation: workspaceGenerationRef.current,
      id: operationIdRef.current + 1,
      kind,
      reviewId: options.reviewId,
    };
    operationIdRef.current = operation.id;
    activeOperationRef.current = operation;
    setActiveOperation(operation);
    return operation;
  }

  function operationCanApply(operation: OperationToken) {
    const active = activeOperationRef.current;
    return Boolean(
      active
      && active.id === operation.id
      && active.generation === operation.generation
      && workspaceGenerationRef.current === operation.generation
      && (!operation.reviewId || currentReviewIdRef.current === operation.reviewId),
    );
  }

  function finishOperation(operation: OperationToken) {
    const active = activeOperationRef.current;
    if (!active || active.id !== operation.id || active.generation !== operation.generation) return;
    activeOperationRef.current = null;
    setActiveOperation(null);
  }

  const loadSamples = useCallback(async () => {
    if (activeOperationRef.current) return;
    setSamplesLoading(true);
    setError(null);
    setFailedAction(null);
    try {
      setSamples(await listSamples());
    } catch (caught) {
      setError(errorMessage(caught));
      setFailedAction("samples");
    } finally {
      setSamplesLoading(false);
    }
  }, []);

  useEffect(() => {
    let active = true;
    listSamples()
      .then((result) => {
        if (active) setSamples(result);
      })
      .catch((caught) => {
        if (!active) return;
        setError(errorMessage(caught));
        setFailedAction("samples");
      })
      .finally(() => {
        if (active) setSamplesLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  const currentPhase = report
    ? 3
    : review
      ? 2
      : isReviewing
        ? 1
        : 0;
  const decidedCount = review?.findings.filter((finding) => finding.decision).length ?? 0;

  const counts = useMemo(() => {
    const initial = { high: 0, medium: 0, low: 0 };
    return review?.findings.reduce((result, finding) => {
      result[finding.severity] += 1;
      return result;
    }, initial) ?? initial;
  }, [review]);

  function selectSample(sample: SamplePrd) {
    if (activeOperationRef.current) return;
    workspaceGenerationRef.current += 1;
    currentReviewIdRef.current = null;
    setTitle(sample.label);
    setContent(sample.content);
    setReview(null);
    setReport(null);
    setError(null);
  }

  async function startReview() {
    if (activeOperationRef.current) return;
    if (!title.trim() || !content.trim()) {
      setError("Add a PRD title and content before starting the review.");
      return;
    }
    const operation = beginOperation("review", { newGeneration: true });
    if (!operation) return;
    currentReviewIdRef.current = null;
    setError(null);
    setFailedAction(null);
    setReview(null);
    setReport(null);
    try {
      const nextReview = await createReview(title, content);
      if (!operationCanApply(operation)) return;
      currentReviewIdRef.current = nextReview.review_id;
      setReview(nextReview);
    } catch (caught) {
      if (!operationCanApply(operation)) return;
      setError(errorMessage(caught));
      setFailedAction("review");
    } finally {
      finishOperation(operation);
    }
  }

  async function decide(decision: DecisionInput) {
    if (!review || activeOperationRef.current) return;
    const reviewId = review.review_id;
    const operation = beginOperation("decision", { reviewId });
    if (!operation) return;
    setError(null);
    setEditError(null);
    try {
      const nextReview = await updateReviewDecisions(reviewId, [decision]);
      if (!operationCanApply(operation) || nextReview.review_id !== reviewId) return;
      setReview(nextReview);
      setReport(null);
      setEditing(null);
    } catch (caught) {
      if (!operationCanApply(operation)) return;
      if (decision.action === "edit") setEditError(errorMessage(caught));
      else setError(errorMessage(caught));
    } finally {
      finishOperation(operation);
    }
  }

  function openEditor(finding: Finding, trigger: HTMLButtonElement) {
    if (activeOperationRef.current) return;
    editTriggerRef.current = trigger;
    setEditing(finding);
    setEditError(null);
    setEditedTitle(displayTitle(finding));
    setEditedRecommendation(displayRecommendation(finding));
  }

  function closeEditor() {
    if (activeOperationRef.current) return;
    setEditError(null);
    setEditing(null);
  }

  useEffect(() => {
    if (editing) editTitleRef.current?.focus();
    else if (editTriggerRef.current) {
      editTriggerRef.current.focus();
      editTriggerRef.current = null;
    }
  }, [editing]);

  function handleDialogKeyDown(event: KeyboardEvent<HTMLElement>) {
    if (event.key === "Escape" && !busy) {
      event.preventDefault();
      closeEditor();
      return;
    }
    if (event.key !== "Tab") return;
    const focusable = Array.from(dialogRef.current?.querySelectorAll<HTMLElement>(
      'button:not([disabled]), input:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
    ) ?? []);
    if (!focusable.length) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }

  async function generateReport() {
    if (!review || activeOperationRef.current) return;
    const reviewId = review.review_id;
    const operation = beginOperation("report", { reviewId });
    if (!operation) return;
    setError(null);
    try {
      const nextReport = await getReviewReport(reviewId);
      if (!operationCanApply(operation)) return;
      setReport(nextReport);
    } catch (caught) {
      if (!operationCanApply(operation)) return;
      setError(errorMessage(caught));
    } finally {
      finishOperation(operation);
    }
  }

  return (
    <main className="workspace-shell">
      <header className="workspace-header">
        <div className="brand-lockup">
          <span className="brand-mark" aria-hidden="true">
            <svg viewBox="0 0 24 24" role="img">
              <path d="M5 5.5h10.5L19 9v9.5H5z" />
              <path d="M15.5 5.5V9H19M8 12h8M8 15h5" />
            </svg>
          </span>
          <div>
            <span className="eyebrow">PECKER PUBLIC EDITION</span>
            <h1>PRD review workspace</h1>
          </div>
        </div>
        <div className="demo-badge"><span /> Deterministic demo · Synthetic</div>
      </header>

      <nav className="phase-strip" aria-label="Review progress">
        {phases.map((phase, index) => {
          const status = index < currentPhase ? "complete" : index === currentPhase ? "current" : "upcoming";
          return (
            <div
              className="phase-item"
              aria-current={status === "current" ? "step" : undefined}
              data-status={status}
              data-testid={`phase-${phaseId(phase)}`}
              key={phase}
            >
              <span className="phase-number">{index + 1}</span>
              <span>{phase}</span>
            </div>
          );
        })}
      </nav>

      {error ? (
        <div className="error-banner" role="alert">
          <span>{error}</span>
          {failedAction === "samples" ? (
            <button type="button" disabled={busy} onClick={() => void loadSamples()}>Retry loading samples</button>
          ) : null}
          {failedAction === "review" ? (
            <button type="button" disabled={busy} onClick={() => void startReview()}>Retry specialist review</button>
          ) : null}
        </div>
      ) : null}

      <div className="workspace-grid">
        <aside className="prd-rail" aria-label="PRD input">
          <section className="panel rail-panel">
            <div className="panel-heading">
              <div>
                <span className="section-index">01</span>
                <h2>Input</h2>
              </div>
              <span className="status-dot">Local text</span>
            </div>

            <div className="sample-list" aria-label="Synthetic samples">
              <span className="field-label">Synthetic samples</span>
              {samplesLoading ? <p className="muted">Loading samples…</p> : null}
              {samples.map((sample) => (
                <article className="sample-card" key={sample.id}>
                  <strong>{sample.label}</strong>
                  <p>{sample.description}</p>
                  <button
                    type="button"
                    className="text-button"
                    aria-label={`Load ${sample.label}`}
                    disabled={busy}
                    onClick={() => selectSample(sample)}
                  >
                    Load sample <span aria-hidden="true">→</span>
                  </button>
                </article>
              ))}
            </div>

            <label className="field-label" htmlFor="prd-title">PRD title</label>
            <input
              id="prd-title"
              disabled={busy}
              value={title}
              onChange={(event) => setTitle(event.target.value)}
              placeholder="Name this review"
            />
            <label className="field-label" htmlFor="prd-content">PRD content</label>
            <textarea
              id="prd-content"
              disabled={busy}
              value={content}
              onChange={(event) => setContent(event.target.value)}
              placeholder="Paste local demo text or load a synthetic sample."
              rows={16}
            />
            <p className="privacy-note">
              <strong>Synthetic data only for this demo.</strong> Text is sent to your configured local API.
            </p>
          </section>
        </aside>

        <section className="findings-column" aria-label="Review findings">
          <div className="panel findings-panel">
            <div className="panel-heading findings-heading">
              <div>
                <span className="section-index">02–03</span>
                <h2>Specialist findings</h2>
              </div>
              {review ? (
                <div className="review-counts" aria-label="Finding status">
                  <strong>{review.findings.length} findings</strong>
                  <span>{decidedCount} of {review.findings.length} decided</span>
                </div>
              ) : null}
            </div>

            {!review && !isReviewing ? (
              <div className="empty-state">
                <span className="empty-glyph" aria-hidden="true">⌁</span>
                <h3>Ready for bounded review</h3>
                <p>Load a synthetic PRD or paste local demo text, then run four independent specialists.</p>
              </div>
            ) : null}

            {isReviewing ? (
              <div className="running-state" aria-live="polite">
                <span className="activity-line" />
                <div>
                  <h3>Specialists are reviewing</h3>
                  <p>Structure, product quality, AI-coding readiness, and data quality run independently.</p>
                </div>
              </div>
            ) : null}

            {review ? (
              <div className="findings-list">
                <div className="severity-summary" aria-label="Severity summary">
                  <span><i className="severity-mark high" /> {counts.high} high</span>
                  <span><i className="severity-mark medium" /> {counts.medium} medium</span>
                  <span><i className="severity-mark low" /> {counts.low} low</span>
                </div>
                {review.findings.map((finding, index) => (
                  <FindingCard
                    finding={finding}
                    index={index + 1}
                    key={finding.id}
                    disabled={busy}
                    onDecision={(action) => void decide({ finding_id: finding.id, action })}
                    onEdit={(trigger) => openEditor(finding, trigger)}
                  />
                ))}
              </div>
            ) : null}
          </div>
        </section>

        <aside className="advisor-column" aria-label="Advisor and report">
          <section className="panel advisor-panel">
            <div className="panel-heading">
              <div>
                <span className="section-index">CROSS-CHECK</span>
                <h2>Independent advisor</h2>
              </div>
            </div>
            {review ? (
              <>
                <p className="advisor-lead">Coverage review completed after consolidation. Evidence remains unchanged.</p>
                {review.advisor.gaps.length ? (
                  <ul className="gap-list">
                    {review.advisor.gaps.map((gap) => <li key={gap}>{gap}</li>)}
                  </ul>
                ) : (
                  <p className="clear-state">No bounded coverage gaps detected.</p>
                )}
                <div className="worker-ledger">
                  <span className="field-label">Worker ledger</span>
                  {Object.entries(review.worker_runs).map(([name, run]) => (
                    <div className="worker-row" key={name}>
                      <span>{name.replaceAll("_", " ")}</span>
                      <strong data-status={run.status}>{run.status}</strong>
                    </div>
                  ))}
                </div>
              </>
            ) : (
              <p className="muted">Advisor coverage appears after specialist consolidation.</p>
            )}
          </section>

          <section className="panel report-panel">
            <div className="panel-heading">
              <div>
                <span className="section-index">04</span>
                <h2>Confirmed report</h2>
              </div>
            </div>
            <p>Markdown includes accepted and edited findings only. Rejected and undecided findings stay out.</p>
            <button
              type="button"
              className="secondary-action"
              disabled={!review || busy}
              onClick={() => void generateReport()}
            >
              {isReporting ? "Generating…" : "Generate confirmed report"}
            </button>
            {report ? <pre className="report-preview">{report}</pre> : null}
          </section>
        </aside>
      </div>

      <div className="sticky-action">
        <div>
          <span className="field-label">CURRENT ACTION</span>
          <strong>{review ? `${decidedCount} of ${review.findings.length} findings decided` : "Prepare input"}</strong>
        </div>
        <button
          type="button"
          className="primary-action"
          disabled={busy || !title.trim() || !content.trim()}
          onClick={() => void startReview()}
        >
          {isReviewing ? "Running specialists…" : "Start specialist review"}
        </button>
      </div>

      {editing ? (
        <div className="dialog-backdrop">
          <section
            className="edit-dialog"
            role="dialog"
            aria-modal="true"
            aria-labelledby="edit-title"
            onKeyDown={handleDialogKeyDown}
            ref={dialogRef}
          >
            <div className="panel-heading">
              <div>
                <span className="section-index">PM EDIT</span>
                <h2 id="edit-title">Edit finding</h2>
              </div>
              <button className="icon-button" type="button" aria-label="Close edit finding" disabled={busy} onClick={closeEditor}>×</button>
            </div>
            {editError ? <div className="dialog-error" role="alert">{editError}</div> : null}
            <label className="field-label" htmlFor="edit-finding-title">Finding title</label>
            <input ref={editTitleRef} id="edit-finding-title" disabled={busy} value={editedTitle} onChange={(event) => setEditedTitle(event.target.value)} />
            <label className="field-label" htmlFor="edit-recommendation">Recommendation</label>
            <textarea id="edit-recommendation" rows={5} disabled={busy} value={editedRecommendation} onChange={(event) => setEditedRecommendation(event.target.value)} />
            <div className="dialog-actions">
              <button className="quiet-action" type="button" disabled={busy} onClick={closeEditor}>Cancel</button>
              <button
                className="primary-action"
                type="button"
                disabled={!editedTitle.trim() || !editedRecommendation.trim() || busy}
                onClick={() => void decide({
                  finding_id: editing.id,
                  action: "edit",
                  edited_title: editedTitle,
                  edited_recommendation: editedRecommendation,
                })}
              >
                Save edit
              </button>
            </div>
          </section>
        </div>
      ) : null}
    </main>
  );
}

interface FindingCardProps {
  finding: Finding;
  index: number;
  disabled: boolean;
  onDecision: (action: Exclude<DecisionAction, "edit">) => void;
  onEdit: (trigger: HTMLButtonElement) => void;
}

function FindingCard({ finding, index, disabled, onDecision, onEdit }: FindingCardProps) {
  const decision = finding.decision?.action;
  const title = displayTitle(finding);
  return (
    <article className="finding-card" data-severity={finding.severity}>
      <div className="finding-topline">
        <span className="finding-number">F{String(index).padStart(2, "0")}</span>
        <span className="category-tag">{finding.category}</span>
        <span className={`severity-chip ${finding.severity}`}>{finding.severity}</span>
        <span className="confidence">{Math.round(finding.confidence * 100)}% confidence</span>
      </div>
      <h3>{title}</h3>
      <blockquote>
        <span>Exact evidence · line {finding.line}</span>
        {finding.evidence}
      </blockquote>
      <div className="recommendation">
        <span>Recommendation</span>
        <p>{displayRecommendation(finding)}</p>
      </div>
      <div className="finding-actions">
        <button
          type="button"
          className={decision === "accept" ? "selected accept" : "accept"}
          aria-label={`Accept ${title}`}
          disabled={disabled}
          onClick={() => onDecision("accept")}
        >Accept</button>
        <button
          type="button"
          className={decision === "reject" ? "selected reject" : "reject"}
          aria-label={`Reject ${title}`}
          disabled={disabled}
          onClick={() => onDecision("reject")}
        >Reject</button>
        <button
          type="button"
          className={decision === "edit" ? "selected edit" : "edit"}
          aria-label={`Edit ${title}`}
          disabled={disabled}
          onClick={(event) => onEdit(event.currentTarget)}
        >Edit</button>
        {decision ? <span className={`decision-label ${decision}`}>{decision === "edit" ? "Edited" : `${decision[0].toUpperCase()}${decision.slice(1)}ed`}</span> : null}
      </div>
    </article>
  );
}
