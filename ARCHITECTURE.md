# Pecker Architecture

## System Topology

```mermaid
flowchart TD
    subgraph "Phase 1 — Precheck"
        A["POST /api/review/precheck<br/>wiki scan + Claude gap analysis<br/>model: sonnet | timeout: 30s"]
    end

    subgraph "Phase 2 — Parallel Review (SSE)"
        B["POST /api/review/run<br/>api/routes/review.py<br/>orchestrator"]
        B --> C["precheck<br/>_scan_wiki_for_prd<br/>local, <1s"]
        C --> D0["stagger 0.3s delay per worker"]

        D0 --> D1["Worker: structure<br/>codename: 织布鸟<br/>model: sonnet<br/>timeout: WORKER_TIMEOUT<br/>rules: V-02~V-06"]
        D0 --> D2["Worker: quality<br/>codename: 猫头鹰<br/>model: sonnet<br/>timeout: WORKER_TIMEOUT<br/>rules: V-07~V-12"]
        D0 --> D3["Worker: ai_coding<br/>codename: 渡鸦<br/>model: opus<br/>timeout: WORKER_TIMEOUT<br/>rules: RC-004~RC-008, RC-013~RC-015"]
        D0 --> D4["Worker: data_quality<br/>codename: 鸬鹚<br/>model: sonnet<br/>timeout: WORKER_TIMEOUT<br/>rules: RC-009~RC-010"]

        D1 --> E["merge_and_deduplicate<br/>review/aggregation.py<br/>dedup threshold: 0.8 similarity"]
        D2 --> E
        D3 --> E
        D4 --> E

        E --> F["Goshawk Advisor<br/>codename: 苍鹰<br/>model: opus<br/>timeout: default<br/>goshawk_advisor.py"]

        F --> G["apply_advisor_result<br/>false_positive / additional / conflict"]
        G --> H["Haiku sanity check<br/>_sanity_check_false_positives<br/>model: haiku | timeout: 10s"]
        H --> I["compute_signature<br/>HMAC-SHA256<br/>api/models.py"]
        I --> J["SSE: result event<br/>ReviewResult opaque handle"]
    end

    subgraph "Phase 3 — Confirm"
        K["POST /api/review/confirm<br/>api/routes/review.py"]
        K --> L["verify_signature"]
        L --> M["_update_rule_perf_from_decisions<br/>EMA impact_score update"]
        M --> N["_save_eval_ground_truth<br/>eval/ground_truth/*.json"]
    end

    A --> B
    J --> K
```

## Data Flow

```mermaid
flowchart LR
    PRD["PRD text<br/>+ raw_materials<br/>+ user_notes"] --> Workers
    Wiki["wiki_pages<br/>(dict title->content)"] --> Workers

    Workers --> Items["items[]<br/>id, rule_id, location,<br/>issue, suggestion,<br/>severity, evidence_type,<br/>evidence_content,<br/>confidence_score"]

    Items --> Goshawk["Goshawk<br/>advisor_result"]
    Goshawk --> FinalItems["final_items[]<br/>+ gate_log<br/>+ advisor_note<br/>+ verification_status"]

    FinalItems --> Signature["HMAC signature"]
    Signature --> Frontend["Frontend<br/>ReviewResult handle"]

    Frontend --> Decisions["Y/N/E decisions<br/>per item_id"]
    Decisions --> RulePerf["rule_performance_history.json<br/>impact_score (EMA)"]
    Decisions --> GroundTruth["eval/ground_truth/<br/>workspace_reviewer_ts.json"]
```

## Feedback Loop

```mermaid
flowchart TD
    A["Phase 3: Y/N/E decisions"] --> B["_update_rule_perf_from_decisions"]
    B --> C["rule_performance_history.json<br/>per rule: confirmed/rejected/missed<br/>impact_score (EMA alpha=0.15)"]
    C --> D["_build_feedback_section<br/>review/prompting.py"]
    D --> E["Worker system prompt injection<br/>- rejection_rate > 0.3 warning<br/>- missed > 2 warning<br/>- eval precision/recall < 0.6<br/>- low/high impact_score hints"]
    E --> F["Next review cycle<br/>Workers get feedback-aware prompts"]
    F --> A
```

## File Mapping

| Node / Responsibility | File | Key Function |
|---|---|---|
| Orchestrator (Phase 2 SSE) | `api/routes/review.py` | `run_review()` |
| Precheck (Phase 1) | `api/routes/review.py` | `precheck()` |
| Worker execution | `review/worker.py` | `_worker_core()`, `_run_worker_async()` |
| Parallel dispatch | `review/orchestration.py` | `parallel_review()`, `_single_round_async()` |
| Merge / dedup | `review/aggregation.py` | `merge_and_deduplicate()` |
| Majority vote | `review/aggregation.py` | `majority_vote()` |
| Evidence verification | `review/evidence_verify.py` | `verify_evidence()`, `_find_wiki_page()`, `_find_rule_reference()` |
| Goshawk advisor | `goshawk_advisor.py` | `advisor_review()`, `advisor_review_async()` |
| Goshawk result merge | `goshawk_advisor.py` | `apply_advisor_result()` |
| Haiku sanity check | `goshawk_advisor.py` | `_sanity_check_false_positives()` |
| Opaque handle + signature | `api/models.py` | `ReviewResult`, `compute_signature()` |
| Phase 3 confirm | `api/routes/review.py` | `confirm_review()` |
| Rule perf feedback | `api/routes/review.py` | `_update_rule_perf_from_decisions()` |
| Eval ground truth | `api/routes/review.py` | `_save_eval_ground_truth()` |
| Dimension config | `review/dimensions.py` | `load_review_dimensions()` |
| YAML schema validation | `review/dimensions.py` | `_validate_review_dimensions_yaml()` |
| Worker prompt building | `review/prompting.py` | `_build_worker_system()`, `_build_worker_messages()`, `_build_feedback_section()` |
| Parallel review facade | `parallel_review.py` | re-exports only (1223 → 78 lines after SPLIT_PLAN) |
| Model tiers / config | `agent_config.py` -> `config/` | `MODEL_TIERS` |
| Confidence scoring | `cuckoo_parser.py` | `compute_confidence()` |
| Gate log (decision chain) | `goshawk_advisor.py` | `_build_gate_log()` |
| Prompt cache monitor | `cache_monitor.py` | `PromptCacheMonitor` |
| Event sourcing | `event_store.py` | `EventStore` |
| B-class semantic verify | `review/evidence_verify.py` | `_verify_b_class_semantic()` |

## Model Assignment

| Component | Model | Rationale |
|---|---|---|
| structure worker (织布鸟) | sonnet | Pattern matching, no deep reasoning |
| quality worker (猫头鹰) | sonnet | Logic check, moderate reasoning |
| ai_coding worker (渡鸦) | opus | Deep reasoning for pseudocode / traceability |
| data_quality worker (鸬鹚) | sonnet | Field mapping check |
| Goshawk advisor (苍鹰) | opus | Cross-validation needs strongest model |
| Haiku sanity check | haiku | Cheap binary agree/disagree |
| Precheck gap analysis | sonnet | Lightweight knowledge scan |
