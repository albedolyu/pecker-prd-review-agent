# Points Payment Deduction PRD Fixture

This fixture is a minimal, non-sensitive PRD shell used by offline route-eval
tests. The ground-truth issues for this case live in the adjacent manifest.

## Scope

- Users can exchange points for payment credits and apply them during checkout.
- The product needs clear quick-select amounts, backend request and response
  contracts, and payment callback behavior.
- Existing point-center redemption may require manual review, which conflicts
  with an immediate checkout deduction flow.

## Known Evaluation Targets

- Quick-select amount counts are inconsistent across prototype and copy.
- Immediate redemption conflicts with manual review assumptions.
- API contracts and error codes are missing.
- Point deduction timing differs between redemption and payment callback text.
