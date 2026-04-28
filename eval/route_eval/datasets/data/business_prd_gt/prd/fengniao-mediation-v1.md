# Fengniao Pre-Litigation Mediation PRD Fixture

This fixture is a minimal, non-sensitive PRD shell used by offline route-eval
tests. The ground-truth issues for this case live in the adjacent manifest.

## Scope

- Court mediation records need to be distinguished from normal case records.
- Web tables, search, filter, and export behavior should stay consistent with
  the existing case-information UI.
- The backend must define the storage field, valid values, default behavior,
  and Elasticsearch mapping before implementation.

## Known Evaluation Targets

- UI fields and filters are underspecified.
- Filtering rules differ between company-home and risk-query flows.
- Mixed case-number examples need clear ownership rules.
- Effective-data filtering needs explicit `data_status=0` semantics.
