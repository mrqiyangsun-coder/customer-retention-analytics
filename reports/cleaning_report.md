# Cleaning and coverage report

Rules: [version 1](../docs/cleaning_rules.md).

## Row reconciliation

- Raw invoice lines: 1,067,371.
- Cross-sheet exported copies excluded: 22,523.
- Retained transaction lines: 1,044,848.
- Extra identical raw rows retained: 11,812; within-sheet multiplicity is preserved.

| Retained line class | Rows |
|---|---:|
| invalid_core | 0 |
| adjustment | 22,558 |
| non_purchase | 2,636 |
| purchase | 1,019,654 |

## Purchase and customer populations

- Qualifying orders: 40,077.
- Positive recorded sales value: GBP 20,533,741.92.
- Orders linked to an unambiguous customer: 36,969.
- Identified-customer order value: GBP 17,431,551.18 (84.89% of positive value).
- Identified customers: 5,878.
- Observed customers with multiple distinct orders: 4,255.
- Conflicting-customer orders: 0.
- Qualifying purchase lines with missing original customer IDs: 228,609.

## Time coverage

Observed span: 2009-12-01T07:45:00 to 2011-12-09T12:50:00.
Partial sales months: 2011-12.

## Interpretation and limits

- Anonymous purchases remain in sales; identified-customer histories cover a subset of that business activity.
- Positive recorded value includes qualifying positive charges; it is not merchandise-only sales, net revenue or profit.
- Adjustment and nonpositive-value lines remain traceable but are outside the positive-purchase metric.
- Within-sheet repeated lines are not proven errors. Keep the policy visible when interpreting totals.
- Repeat-customer counts describe observed history, not a fixed-window retention rate or causal marketing impact.

## Reproducibility

Source SHA-256: `bcbe73b35f5b7babf197fb0cb983a11f5d9ff929078d4aa53d171b1f2df2e980`

All row/value checks passed before the derived database was published.
