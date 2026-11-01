# Data quality audit

Generated (UTC): 2026-10-31T23:37:41.296306+00:00

Source: [UCI Online Retail II](https://archive.ics.uci.edu/dataset/502/online+retail+ii); CC BY 4.0; Chen, D. (2012), DOI 10.24432/C5CG6D.

## Observed workbook

- Raw invoice lines: **1,067,371** (not distinct orders).
- Observed dates: 2009-12-01T07:45:00 to 2011-12-09T12:50:00.
- Missing customer IDs: **243,007 (22.77%)**.
- Extra exact rows beyond first occurrences: **34,335**.
- Exact row patterns appearing in multiple sheets: **22,202**.

| Sheet | Raw rows | First timestamp | Last timestamp |
|---|---:|---|---|
| Year 2009-2010 | 525,461 | 2009-12-01T07:45:00 | 2010-12-09T20:01:00 |
| Year 2010-2011 | 541,910 | 2010-12-01T08:26:00 | 2011-12-09T12:50:00 |

## Missing values

| Column | Missing or blank |
|---|---:|
| invoice_no | 0 |
| stock_code | 0 |
| description | 4,382 |
| quantity | 0 |
| invoice_date | 0 |
| unit_price | 0 |
| customer_id | 243,007 |
| country | 0 |

## Quality flags (overlapping counts)

| Flag | Rows |
|---|---:|
| cancellation_rows | 19,494 |
| negative_quantity | 22,950 |
| zero_quantity | 0 |
| negative_unit_price | 5 |
| zero_unit_price | 6,202 |
| invalid_quantity | 0 |
| invalid_unit_price | 0 |
| invalid_invoice_date | 0 |

## Sheet date overlap

- Year 2009-2010 / Year 2010-2011: 2010-12-01T08:26:00 through 2010-12-09T20:01:00.

## Purchase-candidate diagnostics

Known invoice/date, positive quantity/price, invoice not prefixed C. Provisional audit diagnostic; duplicates retained.

- rows: 1,041,670
- distinct_invoices: 40,077
- rows_without_customer_id: 236,121
- known_customers: 5,878
- customers_with_multiple_invoices: 4,255

## Decisions required before cleaning

1. Investigate cross-sheet overlap and distinguish repeated exports from legitimate repeated line items.
2. Define purchases, cancellations and adjustment handling; do not silently discard negative lines.
3. Keep unidentified-customer coverage visible and define the population for retention analysis.
4. Treat partial months and incomplete future observation windows explicitly.

## Limitations

- Raw records are retained; counts and temporal summaries may include workbook overlap and duplicate patterns.
- Flag counts overlap and must not be added as mutually exclusive categories.
- An invoice can have many lines; invoice counts are not line counts.
- First/last observed months need completeness review before comparing monthly totals.
- Observed first purchase is not necessarily acquisition; no causal campaign effect or profit is established.

## Reproducibility

Workbook SHA-256: `bcbe73b35f5b7babf197fb0cb983a11f5d9ff929078d4aa53d171b1f2df2e980`

Runtime: `{"openpyxl": "3.1.5", "pandas": "3.0.1", "python": "3.12.14"}`
