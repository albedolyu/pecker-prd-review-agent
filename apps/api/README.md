# Pecker API

Public-safe FastAPI backend snapshot for the Pecker PRD review workbench.

This copy preserves the main backend shape: auth, workspaces, drafts, review
jobs, reports, feedback, model routing, specialist review orchestration, and
LangGraph-style orchestration modules. Private workspaces, real wiki pages,
local SQLite state, internal deployment notes, and the experimental Q&A helper
are intentionally omitted.

For interview review, start with:

- `review/langgraph_orchestration.py` for the checkpointable agent node design.
- `review/prompting.py` and `review-dimensions.yaml` for prompt/rule governance.
- `cuckoo_*`, `rule_perf_*`, and `api/usage_summary.py` for eval and telemetry
  surfaces.

## Run

```bash
python -m pip install -e ".[dev]"
copy .env.example .env
uvicorn api.main:app --reload --host 127.0.0.1 --port 8000
```

The included `.env.example` contains only placeholders. Put real keys in your
local `.env`, which is ignored by git.

## Verify

```bash
python -m compileall -q .
python -m pytest -q
```
