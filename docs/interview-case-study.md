# Interview Case Study

This repo is a public-safe slice of a PRD review agent. It is intentionally
small enough to inspect quickly, but it preserves the core engineering shape:
agent nodes, measurable eval loops, and prompt quality scoring.

## What To Review First

1. `src/pecker/graph.py`
   The executable mini graph shows the core node topology:

   ```text
   prepare_context
     -> precheck_assets
     -> fan_out_workers
     -> merge_findings
     -> advisor_cross_check
     -> finalize_report
   ```

2. `apps/api/review/langgraph_orchestration.py`
   The larger backend snapshot shows how the same idea becomes a checkpointable,
   inspectable LangGraph workflow with worker fan-out, retries, merge, and final
   report assembly.

3. `src/pecker/prompt_quality.py`
   Prompt variants are scored with explicit dimensions instead of relying on
   taste:

   | Dimension | Meaning |
   | --- | --- |
   | instruction_coverage | Required controls present in the prompt |
   | evidence_contract | Whether the prompt asks for quote/source/citation evidence |
   | output_schema | Whether the prompt constrains machine-readable fields |
   | improvement_guidance | Whether the prompt asks for actionable fixes |
   | safety_boundary | Whether the prompt avoids unsafe or leakage-prone behavior |

## Runnable Demo

```bash
python -m pip install -e ".[dev]"
pecker-eval-suite --dry-run
pecker-review examples/sample_prd.md --json
pecker-channel-eval --config config/model_channels.example.yaml --dry-run
pecker-prompt-quality --config config/prompt_quality.example.yaml
pytest -q
```

`pecker-eval-suite --dry-run` is the fastest interview walkthrough. It produces
one JSON report with:

- review trace and worker count
- how-to-fix and acceptance-check coverage
- model channel ranking and admission gate pass rate
- prompt ranking, prompt gate pass rate, and missing controls by prompt

Expected review trace:

```json
[
  "prepare_context",
  "precheck_assets",
  "fan_out_workers",
  "merge_findings",
  "advisor_cross_check",
  "finalize_report"
]
```

Expected prompt-quality outcome: the v2 worker prompts rank above the v1 prompts
because they include rule IDs, evidence requirements, structured output fields,
confidence, how-to-fix guidance, and acceptance checks.

## Evaluation Design

The project uses three evaluation surfaces:

| Surface | Question | Example proof |
| --- | --- | --- |
| Output contract | Did workers return useful, adoptable findings? | `tests/test_public_smoke.py` checks `how_to_fix` and `acceptance_check`. |
| Channel evaluation | Which model/API route is stable enough? | `pecker-channel-eval` ranks by success rate, p95 latency, cost, and gate result. |
| Prompt quality | Did a prompt revision improve measurable controls? | `pecker-prompt-quality` ranks prompt variants and lists missing controls. |

`src/pecker/eval_suite.py` ties these surfaces together so the project can be
judged with one command before drilling into individual modules.

The private production version also uses PM adjudication, rule-performance
history, and regression cases. The public edition keeps the structure and
removes private workspaces, reports, wiki pages, service URLs, and keys.

## Why This Matters

The product problem is not just "call an LLM on a PRD." The interesting part is
making review behavior inspectable and improvable:

- Nodes make responsibility boundaries visible.
- Worker return schemas make outputs comparable.
- Advisor checks reduce low-adoption findings.
- Eval gates make model and prompt changes reviewable.
- Prompt scores give a quantitative starting point before live PM feedback.
