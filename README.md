# Pecker PRD Review Agent

Public-safe reference implementation of a multi-worker PRD review harness.

This repo is designed as an interview-readable case study: it shows how I think
about agent topology, automated evaluation, prompt quality measurement, and
public-safe productization. It contains no private Git history, customer PRDs,
internal deployment notes, production API keys, or experimental Q&A helper code.
The sample data is synthetic.

## What It Shows

- A small LangGraph-style review pipeline with explicit node traces.
- Four specialist workers: structure, quality, data, and implementation.
- A governed tool registry with caller allowlists and redacted audit payloads.
- A model channel evaluation harness for OpenAI-compatible providers.
- A prompt quality scoring harness that turns prompt variants into comparable
  metrics instead of subjective preference.
- Structured review findings with concrete improvement guidance.
- A Next.js workbench UI under `apps/web`, sanitized for public demo use.
- A sanitized FastAPI backend snapshot under `apps/api` for the fuller system
  shape: auth, review jobs, SSE, reports, feedback, LangGraph orchestration,
  model routing, and eval telemetry.

## Architecture Snapshot

```text
review_request
  -> prepare_context
  -> precheck_assets
  -> fan_out_workers
       | structure_worker
       | quality_worker
       | data_worker
       | implementation_worker
  -> merge_findings
  -> advisor_cross_check
  -> finalize_report
```

Each worker returns a stable machine-readable shape:

```json
{
  "status": "ok",
  "output": [],
  "confidence": 0.8,
  "tokens_used": 0
}
```

Findings include `how_to_fix` and `acceptance_check` so a PM can adopt the
suggestion without guessing what to edit.

## Quick Start

```bash
python -m pip install -e ".[dev]"
pecker-review examples/sample_prd.md --json
pecker-channel-eval --config config/model_channels.example.yaml --dry-run
pecker-prompt-quality --config config/prompt_quality.example.yaml
pytest -q
```

### Web Workbench

```bash
cd apps/web
pnpm install --frozen-lockfile
pnpm dev
```

Open `http://127.0.0.1:3000/review?demo=1` to use the public demo flow without
an internal backend.

## Repository Layout

```text
src/pecker/
  graph.py          Review orchestration and traceable node flow
  workers.py        Specialist review workers
  tool_registry.py  Governed tool boundary
  channel_eval.py   Model/API channel comparison helper
  prompt_quality.py Prompt quality scoring helper
  redaction.py      Secret and internal URL redaction
examples/
  sample_prd.md     Synthetic PRD for local testing
config/
  model_channels.example.yaml
  prompt_quality.example.yaml
apps/web/
  app/              Next.js app routes
  components/       Review phases, result cards, and shared UI primitives
  lib/              API types, review store, demo data, and browser helpers
  tests/            Vitest and Playwright checks from the workbench
apps/api/
  api/              FastAPI routes, SSE, auth, reports, admin metrics
  review/           LangGraph orchestration, worker prompts, eval feedback loop
  clients/          OpenAI-compatible and CLI model clients
```

## Evaluation Surfaces

- `pytest -q` verifies the public graph, redaction, tool boundary, channel eval,
  and prompt quality scoring.
- `pecker-channel-eval` ranks model/API channels by success rate, p95 latency,
  cost, and gate pass/fail.
- `pecker-prompt-quality` scores prompt variants on instruction coverage,
  evidence contract, output schema, improvement guidance, and safety boundary.
- The backend snapshot keeps additional eval plumbing (`cuckoo_*`,
  `rule_perf_*`, `review/prompting.py`, `review/langgraph_orchestration.py`) so
  the public repo still demonstrates the production architecture shape without
  private workspaces.

## Safety Notes

This public edition intentionally omits:

- real PRD workspaces and generated review reports
- internal wiki pages and database schema details
- company deployment scripts, private domains, and service URLs
- experimental Q&A helper routes and UI
- local `.env` files and historical Git commits

The web app keeps public-safe demo paths and mock data. Backend-only admin,
authentication, and persistence calls are retained as typed clients for reference,
but the recommended public entry is `/review?demo=1`.

Use `.env.example` as the only supported configuration template.
