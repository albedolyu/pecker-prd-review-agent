# Eval Report Metric Diagnosis (2026-04-28)

Scope: recent `eval_reports/*.json` from 2026-04-27, focused on negative cost, long p95, and issues-task F1=0.

## Findings

1. Negative cost in `verify.nli` is a runner accounting bug in old reports.
   - Evidence: `eval_reports/verify_nli_anthropic_haiku_20260427_230500.json` records `n_samples_succeeded: -1` for fake-ref fast-path cases, then aggregates `input_tokens=-4000`, `output_tokens=-800`, `cost_usd_total=-0.024`.
   - Status: fixed for future runs in `eval/route_eval/runner.py` by clamping fast-path sentinel samples to zero usage. Covered by `tests/test_route_eval_nli_cost.py`.
   - Action: do not use the old negative-cost reports as cost baselines. Regenerate `verify.nli` baseline before admission comparison.

2. Long p95 is route-run latency, not per-case or per-LLM-call latency.
   - Evidence: route reports generally contain one `call_record` for a batched pattern; for example `baseline_real_p2_final.json` has `verify.nli` p95 `549431 ms` for 20 cases and `router.intent` p95 `432138 ms` for 20 cases.
   - Status: report wording now clarifies that classification patterns may batch many cases into one route-run record. See `eval/route_eval/report.py`.
   - Action: keep p95 for admission as a coarse route-run budget, but add per-case/per-call telemetry before using it for latency optimization.

3. `worker.compliance` F1=0 was a report-adapter issue, not proof that the scorer found zero true positives.
   - Evidence: `eval_reports/worker_compliance_anthropic_sonnet_20260427_233651.json` has `output_tokens=11342`, but `responses=[[]]`, so the old runner parsed no items and cuckoo scored 21 misses.
   - Root cause: `_call_worker_pattern` asked for a free-form JSON list and only parsed text. It did not reuse the production `submit_review_items` schema/tool parser, so rich model output could collapse into zero items.
   - Status: fixed for future runs by routing worker eval calls through `SUBMIT_REVIEW_ITEMS_TOOL` and `_extract_items_from_response`, with text JSON as fallback. Covered by `tests/test_route_eval_worker_tool_parse.py`.
   - Action: regenerate `worker.*` / `eval.cuckoo` issues baselines before interpreting F1.

4. `advisor.goshawk` F1=0 in `baseline_real_p2_final.json` is now partly adapter-sensitive.
   - Evidence: earlier dry-run `advisor_goshawk_anthropic_sonnet_20260427_163813.json` had zero misses because ground truth normalization was empty. Current `baseline_real_p2_final.json` has `total_items=10`, `fps=10`, `misses=0`, which suggests predictions are present but not matching normalized GT.
   - Status: ground-truth collection for `advisor_conflicts` has already been corrected to collect `ground_truth_resolution.merged` ids. Covered by `tests/test_route_eval_advisor_gt.py`.
   - Action: rerun `advisor.goshawk` after the worker/tool parser fix and inspect unmatched IDs if F1 remains zero.

## Baseline Policy

Treat 2026-04-27 reports before this fix as diagnostic artifacts, not stable admission baselines, when they show negative cost or `responses=[[]]` with nonzero output tokens. The next reliable baseline should be generated from the current checkout after Python/web gates are green enough for the eval runner.
