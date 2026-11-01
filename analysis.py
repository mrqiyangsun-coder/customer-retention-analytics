"""Descriptive SQL analysis of the versioned retail database."""

import argparse
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import sqlite3

import pandas as pd


ROOT = Path(__file__).resolve().parent
COHORT_COLUMNS = ["cohort_month", "activity_month", "month_age", "cohort_size", "active_customers", "activity_rate"]


def read_analysis(db):
    metadata = dict(db.execute("SELECT key, value FROM pipeline_metadata"))
    span = json.loads(metadata["source_date_range"])
    if not span.get("start") or not span.get("end"):
        raise ValueError("An observed source date range is required for calendar comparisons")
    monthly = pd.read_sql_query((ROOT / "sql/02_monthly_analysis.sql").read_text(encoding="utf-8"), db)
    activity = pd.read_sql_query((ROOT / "sql/03_cohort_activity.sql").read_text(encoding="utf-8"), db)
    concentration = pd.read_sql_query((ROOT / "sql/04_customer_concentration.sql").read_text(encoding="utf-8"), db)
    complete = monthly.loc[monthly["is_complete_month"].eq(1), "month"].tolist()
    active_lookup = {(row.cohort_month, row.activity_month): int(row.active_customers)
                     for row in activity.itertuples()}
    records = []
    for row in activity[["cohort_month", "cohort_size"]].drop_duplicates().itertuples(index=False):
        if row.cohort_month not in complete:
            continue
        for month in complete:
            if month >= row.cohort_month:
                age = pd.Period(month, freq="M").ordinal - pd.Period(row.cohort_month, freq="M").ordinal
                active = active_lookup.get((row.cohort_month, month), 0)
                records.append({"cohort_month": row.cohort_month, "activity_month": month,
                                "month_age": age, "cohort_size": int(row.cohort_size),
                                "active_customers": active, "activity_rate": active / row.cohort_size})
    cohorts = pd.DataFrame(records, columns=COHORT_COLUMNS)
    # Independent population/accounting contracts, not just successful query execution.
    segments = monthly[["first_observed_month_value", "previously_observed_value", "anonymous_value"]].sum(axis=1)
    if not all(math.isclose(a, b, rel_tol=1e-12, abs_tol=.01) for a, b in zip(segments, monthly["positive_sales_value"])):
        raise AssertionError("Monthly customer-segment value does not reconcile")
    if not monthly["identified_active_customers"].eq(monthly["first_observed_customers"] + monthly["previously_observed_customers"]).all():
        raise AssertionError("Monthly customer populations do not reconcile")
    if not cohorts.empty and not cohorts["activity_rate"].between(0, 1).all():
        raise AssertionError("Cohort activity rate outside [0, 1]")
    return {"monthly": monthly, "cohorts": cohorts, "concentration": concentration}


def build_summary(tables):
    monthly, cohorts, concentration = (tables[name] for name in ["monthly", "cohorts", "concentration"])
    full = monthly.loc[monthly["is_complete_month"].eq(1)].copy()
    comparison = None
    years = sorted(full["month"].str[:4].unique())
    if len(years) >= 2:
        earlier, later = years[-2:]
        first = full.loc[full.month.str.startswith(earlier)].set_index(full.loc[full.month.str.startswith(earlier), "month"].str[5:])
        second = full.loc[full.month.str.startswith(later)].set_index(full.loc[full.month.str.startswith(later), "month"].str[5:])
        shared = sorted(set(first.index) & set(second.index))
        if shared:
            previous_value, current_value = float(first.loc[shared, "positive_sales_value"].sum()), float(second.loc[shared, "positive_sales_value"].sum())
            previous_orders, current_orders = int(first.loc[shared, "orders"].sum()), int(second.loc[shared, "orders"].sum())
            previous_aov = previous_value / previous_orders if previous_orders else None
            current_aov = current_value / current_orders if current_orders else None
            comparison = {"earlier_year": earlier, "later_year": later, "matched_month_numbers": shared,
                          "earlier_value": previous_value, "later_value": current_value,
                          "value_change": current_value / previous_value - 1 if previous_value else None,
                          "earlier_orders": previous_orders, "later_orders": current_orders,
                          "order_change": current_orders / previous_orders - 1 if previous_orders else None,
                          "earlier_aov": previous_aov, "later_aov": current_aov,
                          "aov_change": current_aov / previous_aov - 1 if previous_aov and current_aov is not None else None}
    latest = None
    if not full.empty:
        row = full.iloc[-1]
        identified_value = float(row.first_observed_month_value + row.previously_observed_value)
        latest = {"month": row.month, "positive_sales_value": float(row.positive_sales_value),
                  "orders": int(row.orders),
                  "mom_sales_change": None if pd.isna(row.mom_sales_change) else float(row.mom_sales_change),
                  "yoy_sales_change": None if pd.isna(row.yoy_sales_change) else float(row.yoy_sales_change),
                  "previously_observed_value_share_identified": float(row.previously_observed_value) / identified_value if identified_value else None}
    top = None
    if not concentration.empty:
        count = math.ceil(len(concentration) * .1)
        row = concentration.iloc[count - 1]
        top = {"customer_count": count, "total_identified_customers": len(concentration),
               "identified_value_share": None if pd.isna(row.cumulative_value_share) else float(row.cumulative_value_share)}
    month1 = cohorts.loc[cohorts["month_age"].eq(1) & cohorts["cohort_month"].ne(monthly.iloc[0]["month"])]
    month1_summary = None
    if not month1.empty:
        denominator, numerator = int(month1.cohort_size.sum()), int(month1.active_customers.sum())
        month1_summary = {"eligible_cohorts": len(month1), "customers": denominator,
                          "active_customers": numerator, "activity_rate": numerator / denominator}
    return {"observed_orders": int(monthly.orders.sum()), "observed_positive_value": float(monthly.positive_sales_value.sum()),
            "complete_month_count": len(full), "partial_months": monthly.loc[monthly.is_complete_month.eq(0), "month"].tolist(),
            "latest_complete_month": latest, "matched_year_comparison": comparison, "top_decile": top,
            "month1_activity_excluding_initial_cohort": month1_summary}


def percentage(value):
    return "undefined" if value is None else f"{value:+.1%}"


def render_memo(summary):
    lines = ["# First business analysis memo", "", "## Scope", "",
             "Historical UK retail records, December 2009-December 2011. Results use the documented version 1 positive-purchase definition. Values are GBP recorded positive charges, not net revenue or profit. No causal effect is estimated.",
             "", "## Findings", ""]
    comparison = summary["matched_year_comparison"]
    if comparison:
        months = ", ".join(comparison["matched_month_numbers"])
        lines.append(f"1. Comparing the same complete calendar months ({months}) in {comparison['earlier_year']} and {comparison['later_year']}, positive value changed from GBP {comparison['earlier_value']:,.2f} to GBP {comparison['later_value']:,.2f} ({percentage(comparison['value_change'])}). Orders changed from {comparison['earlier_orders']:,} to {comparison['later_orders']:,} ({percentage(comparison['order_change'])}). These are matched-period comparisons, not full-year growth claims.")
        if comparison["earlier_aov"] is not None and comparison["later_aov"] is not None:
            lines.append(f"   Average positive order value changed from GBP {comparison['earlier_aov']:,.2f} to GBP {comparison['later_aov']:,.2f} ({percentage(comparison['aov_change'])}). This describes the value/order-count decomposition; it does not establish a price increase or explain changes in customer/product mix.")
    else:
        lines.append("1. There are insufficient shared complete months across two years for a matched-year comparison.")
    latest = summary["latest_complete_month"]
    if latest:
        lines.extend(["", f"2. The latest complete month, {latest['month']}, recorded GBP {latest['positive_sales_value']:,.2f}. Month-over-month change was {percentage(latest['mom_sales_change'])}; the same-month prior-year change was {percentage(latest['yoy_sales_change'])}. Seasonal and year-over-year context must accompany short-term changes."])
        share = latest["previously_observed_value_share_identified"]
        if share is not None:
            lines.append(f"   Customers observed before that month supplied {share:.1%} of identified-customer value. Customers in their first observed month include any purchases within that month. This is not proof of true acquisition or improving causal retention.")
    top = summary["top_decile"]
    if top and top["identified_value_share"] is not None:
        lines.extend(["", f"3. The top {top['customer_count']:,} of {top['total_identified_customers']:,} identified customers (the rounded-up top 10%) account for {top['identified_value_share']:.1%} of identified positive value across observed histories. Anonymous sales are outside that denominator; customers also have unequal history lengths."])
    month1 = summary["month1_activity_excluding_initial_cohort"]
    if month1:
        lines.extend(["", f"4. Among {month1['customers']:,} customers in {month1['eligible_cohorts']} cohorts with a fully observed following calendar month, excluding the initial dataset cohort, {month1['active_customers']:,} ({month1['activity_rate']:.1%}) purchased in that next month. This measures exact-month activity, not continuous survival or permanent churn. The initial cohort is excluded from this aggregate because it is especially left-truncated."])
    lines.extend(["", "## Decisions and next investigations", "",
        "- Monitor matched-month sales and order counts together. Inspect customer and country mix before assigning a cause to any change.",
        "- Investigate dependence on large identified customers; use a later time window to check whether concentration persists.",
        "- Use mature cohort patterns to form retention hypotheses. Design a randomized outreach/offer experiment before claiming an intervention improves purchases; purchase propensity alone does not identify treatment uplift.",
        "- Quantify sensitivity to adjustment treatment, charges and within-sheet repeats before making financial decisions.",
        "", "## Coverage and limitations", "",
        f"- Partial months excluded from trend comparisons: {', '.join(summary['partial_months']) or 'none'}.",
        "- Customer analyses cover identified orders only. The cleaning report documents the sales-value coverage of that subset.",
        "- First observed purchase is not necessarily acquisition. Monthly customer mix changes partly as the observation window accumulates history.",
        "- Cohort charts omit partial/future windows; an observed inactive month is zero, but an unobserved month is blank.",
        "- Cohort activity allows customers to leave and return; it does not require uninterrupted monthly purchases.",
        "- The historical retailer includes wholesalers. These associations do not establish current-market behavior or causal explanations.",
        "", "## Figures", "",
        "![Monthly positive recorded sales, complete months](figures/monthly_sales.png)", "",
        "![Customer-month value mix](figures/customer_mix.png)", "",
        "![Monthly cohort activity](figures/cohort_activity.png)", "",
        "![Identified-customer value concentration](figures/customer_concentration.png)", "",
        "## Reproduce", "", "Run `.\\.venv\\Scripts\\python.exe analysis.py` from the project folder. SQL sources are in `sql/02_monthly_analysis.sql`, `sql/03_cohort_activity.sql` and `sql/04_customer_concentration.sql`. CSV files contain all computed values, including partial months labeled explicitly.", ""])
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=ROOT / "data/processed/retail.sqlite")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "reports")
    args = parser.parse_args(argv)
    path = args.database.resolve()
    if not path.is_file():
        parser.error("Analysis database missing; run clean.py first")
    checksum = hashlib.sha256(path.read_bytes()).hexdigest()
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db:
        tables = read_analysis(db)
        metadata = {key: json.loads(value) for key, value in db.execute("SELECT key, value FROM pipeline_metadata")}
    summary = build_summary(tables)
    summary.update({"database_sha256": checksum, "source_sha256": metadata.get("source_sha256"),
                    "rules_version": metadata.get("rules_version"), "generated_at_utc": datetime.now(timezone.utc).isoformat()})
    args.output_dir.mkdir(parents=True, exist_ok=True)
    tables["monthly"].to_csv(args.output_dir / "monthly_analysis.csv", index=False)
    tables["cohorts"].to_csv(args.output_dir / "cohort_activity.csv", index=False)
    tables["concentration"].to_csv(args.output_dir / "customer_concentration.csv", index=False)
    from charts import create_charts
    create_charts(tables, args.output_dir / "figures")
    if hashlib.sha256(path.read_bytes()).hexdigest() != checksum:
        raise AssertionError("Analysis database changed during read-only analysis")
    (args.output_dir / "analysis_summary.json").write_text(json.dumps(summary, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    (args.output_dir / "business_memo.md").write_text(render_memo(summary), encoding="utf-8")
    print(f"Analyzed {summary['complete_month_count']} complete months; database unchanged.")
    print(f"Memo: {(args.output_dir / 'business_memo.md').resolve()}")


if __name__ == "__main__":
    main()

