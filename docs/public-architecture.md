# Public Architecture

The public edition keeps the harness shape while replacing all private context
with synthetic examples.

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

Workers return a stable shape:

```json
{
  "status": "ok",
  "output": [],
  "confidence": 0.8,
  "tokens_used": 0
}
```

External tools are not called directly by workers. They must be registered in
`ToolRegistry` with caller allowlists, risk metadata, timeout metadata, and a
redacted audit payload.

## Evaluation Loop

The public repo keeps three measurable loops:

- Review output checks: findings must include issue, evidence, recommendation,
  how_to_fix, and acceptance_check.
- Channel checks: model/API candidates are ranked by success rate, p95 latency,
  cost, and gate pass/fail.
- Prompt checks: prompt variants are scored by instruction coverage, evidence
  contract, output schema, improvement guidance, and safety boundary.

The sanitized backend snapshot in `apps/api` keeps the larger implementation
shape: LangGraph orchestration, checkpoint helpers, worker prompt construction,
scenario detection, rule-performance feedback, and eval telemetry. It excludes
private workspaces, internal wiki pages, generated reports, local databases, and
the experimental Q&A helper.
