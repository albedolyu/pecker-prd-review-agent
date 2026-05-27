# Public Architecture

The public edition keeps the harness shape while replacing all private context
with synthetic examples.

```text
review_request
  -> prepare_context
  -> run_workers
  -> merge_findings
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
