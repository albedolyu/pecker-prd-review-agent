# Pecker PRD Review Agent

Public-safe reference implementation of a multi-worker PRD review harness.

This repository is a clean-room public edition. It contains no private Git
history, no customer PRDs, no internal deployment notes, and no production API
keys. The sample data is synthetic.

## What It Shows

- A small LangGraph-style review pipeline with explicit node traces.
- Four specialist workers: structure, quality, data, and implementation.
- A governed tool registry with caller allowlists and redacted audit payloads.
- A model channel evaluation harness for OpenAI-compatible providers.
- Structured review findings with concrete improvement guidance.
- A Next.js workbench UI under `apps/web`, sanitized for public demo use.

## Quick Start

```bash
python -m pip install -e ".[dev]"
pecker-review examples/sample_prd.md --json
pecker-channel-eval --config config/model_channels.example.yaml --dry-run
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
  redaction.py      Secret and internal URL redaction
examples/
  sample_prd.md     Synthetic PRD for local testing
apps/web/
  app/              Next.js app routes
  components/       Review phases, result cards, and shared UI primitives
  lib/              API types, review store, demo data, and browser helpers
  tests/            Vitest and Playwright checks from the workbench
```

## Safety Notes

This public edition intentionally omits:

- real PRD workspaces and generated review reports
- internal wiki pages and database schema details
- company deployment scripts, private domains, and service URLs
- local `.env` files and historical Git commits

The web app keeps public-safe demo paths and mock data. Backend-only admin,
authentication, and persistence calls are retained as typed clients for reference,
but the recommended public entry is `/review?demo=1`.

Use `.env.example` as the only supported configuration template.
