# Cleaning and metric definitions - version 1

These are explicit analytical choices for this project, not claims about the retailer's accounting policy. The original workbook is immutable. Every retained or excluded line is traceable by source sheet and Excel row number.

## Evidence about overlap

The two sheets overlap from December 1, 2010 08:26 through December 9, 2010 20:01. Each contains 22,523 lines in that interval. A comparison of all eight original fields, including each row pattern's occurrence count, found zero unmatched occurrences in either direction. These are repeated exports of the same recorded lines, rather than merely similar dates.

## Rules

1. **Repeated exports across sheets:** match all eight original fields. For each identical pattern keep the maximum multiplicity found within one sheet, preferring occurrences from later sheets. If a pattern occurs twice in one sheet and once in another, retain two occurrences. Never apply blanket `drop_duplicates` within a sheet. Retain unmatched records even when their dates overlap. Save every removed source key in `export_exclusions`.
2. **Identifiers:** strip surrounding whitespace; make invoice/stock codes uppercase; normalize integer-like customer IDs without a trailing `.0`. Blank customer IDs remain missing. Do not create a fictional customer or infer identity from country/spending similarity. Preserve literal text such as `NA`.
3. **Core validity:** an analyzable line needs invoice, stock code, a usable timestamp, and finite numeric quantity/price. Invalid lines remain in `transactions` labeled `invalid_core`; they do not enter order/sales metrics.
4. **Adjustments:** valid lines with a C-prefixed invoice or negative quantity are labeled `adjustment`. Retain them for later examination but exclude them from positive-purchase metrics. Do not assume every negative line is a matched refund or subtract it twice.
5. **Nonpositive values:** remaining lines with quantity <= 0 or price <= 0 are labeled `non_purchase`. They remain traceable, but contribute neither a qualifying order nor positive sales. This does not prove those records are business errors.
6. **Purchase lines:** remaining positive-quantity, positive-price, non-C lines qualify. Missing description, country or customer ID alone does not remove a valid sales line. Positive recorded charges can include shipping/manual items; this version reports recorded positive sales value, not merchandise-only sales, accounting net revenue, or profit.
7. **Orders:** one qualifying invoice is one order, even if it contains many lines. Sum qualifying line values for its positive order value. Use its earliest qualifying timestamp. Assign the unique known customer ID observed on the invoice if there is one; leave it missing if there are none or multiple distinct IDs. Retain customer-ID conflicts as flagged orders for sales, excluding them from identified-customer history. Do not alter original line-level missing IDs.
8. **Customers:** build histories only from orders with an unambiguous customer ID. Call the first date `first_observed_order`, not acquisition. One observed order is not proof of a permanently lost customer.
9. **Time coverage:** flag a sales month as fully within the observed date span only when the entire calendar month is covered. December 2011 is partial. This calendar check does not prove absence of data outages. First observed cohorts still have left-truncated history. Future modeling labels require a complete future observation window.

The four line classes (`invalid_core`, `adjustment`, `non_purchase`, `purchase`) are mutually exclusive in the priority listed above. Separate diagnostic flags may overlap.

## Version 1 metrics

- **Positive recorded sales value:** sum(quantity * unit_price) over qualifying purchase lines, including unidentified customers; GBP as recorded in the source. Keep calculation precision and round only displayed totals.
- **Orders:** distinct qualifying invoices.
- **Average order value:** positive recorded sales value / orders; undefined when orders = 0.
- **Identified-customer coverage:** qualifying order count and order value linked to one unambiguous customer, divided by all qualifying orders/value respectively. Line-level missing-ID counts are reported separately.
- **Observed repeat customers:** identified customers with at least two distinct qualifying invoices. This is descriptive observed repeat purchasing, not a fixed-window retention estimate.

No model, causal uplift, actual marketing return, or net profit is estimated by this milestone. Returns/refunds and within-sheet duplicates remain explicit limitations. A later sensitivity analysis may compare alternate policies without silently replacing this version.

## Outputs and reconciliation

Create a reproducible SQLite database with `transactions`, `export_exclusions`, `orders`, `customers`, and `pipeline_metadata`. Views expose purchase lines and identified-customer orders. Produce a cleaning report, monthly sales CSV and a metrics JSON.

Required checks: raw lines = exported copies excluded + retained lines; retained lines = sum of the four line classes; purchase-line value = order value = monthly value within a penny of floating-point aggregation tolerance; source checksum unchanged. Report within-sheet repeats retained and anonymous-customer coverage so exclusions cannot be mistaken for improved business performance.

