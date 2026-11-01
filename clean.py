"""Build traceable analysis tables under documented version 1 rules."""

import argparse
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import sqlite3
import uuid

import pandas as pd

from audit import ALIASES, COLUMNS, iso, normalized_text, parsed_dates


ROOT = Path(__file__).resolve().parent
ORDER_COLUMNS = ["invoice_no", "order_date", "order_value", "line_count", "customer_id", "country", "customer_id_conflict"]
CUSTOMER_COLUMNS = ["customer_id", "first_observed_order", "last_observed_order", "observed_orders", "positive_order_value"]
MONTH_COLUMNS = ["month", "orders", "positive_sales_value", "identified_orders", "is_complete_month"]


def load_source(path):
    """Read original cell fields plus sheet/Excel-row provenance."""
    frames = []
    with pd.ExcelFile(path, engine="openpyxl") as workbook:
        for sheet_name in workbook.sheet_names:
            frame = pd.read_excel(workbook, sheet_name=sheet_name, dtype=object, keep_default_na=False)
            frame = frame.rename(columns={
                column: ALIASES.get(str(column).strip().lower().replace(" ", "").replace("_", ""), column)
                for column in frame.columns
            })
            missing = sorted(set(COLUMNS) - set(frame.columns))
            if missing or frame.columns.duplicated().any():
                raise ValueError(f"Invalid source columns in {sheet_name}: missing {missing} or duplicate names")
            frame = frame[COLUMNS].copy()
            frame["source_sheet"] = sheet_name
            frame["source_row"] = range(2, len(frame) + 2)
            frames.append(frame)
    return pd.concat(frames, ignore_index=True)


def build_tables(raw):
    """Preserve provenance, remove cross-sheet copies, then derive analysis tables."""
    data = raw.reset_index(drop=True).copy()
    required = COLUMNS + ["source_sheet", "source_row"]
    missing = sorted(set(required) - set(data.columns))
    if missing:
        raise ValueError(f"Missing source fields: {missing}")
    if data.duplicated(["source_sheet", "source_row"]).any():
        raise ValueError("Source sheet/row keys must identify unique original records")

    pattern = data.groupby(COLUMNS, dropna=False, sort=False).ngroup()
    keys = pd.DataFrame({"pattern": pattern, "sheet": data["source_sheet"]})
    keys["occurrence"] = keys.groupby(["pattern", "sheet"], sort=False).cumcount()
    priority = {name: index for index, name in enumerate(data["source_sheet"].drop_duplicates())}
    keys["priority"] = keys["sheet"].map(priority)
    # Keep one copy of each occurrence rank across sheets, preferring the later
    # export. This preserves max per-sheet multiplicity, not just one row.
    excluded_mask = keys.sort_values("priority", ascending=False, kind="stable").duplicated(["pattern", "occurrence"]).reindex(data.index)
    exclusions = data.loc[excluded_mask].copy()
    exclusions["exclusion_reason"] = "exact_cross_sheet_export_copy"
    retained_raw = data.loc[~excluded_mask].copy()
    transactions = retained_raw.copy()

    transactions["invoice_no"] = normalized_text(transactions["invoice_no"]).str.upper()
    transactions["stock_code"] = normalized_text(transactions["stock_code"]).str.upper()
    transactions["customer_id"] = normalized_text(transactions["customer_id"])
    for field in ["description", "country"]:
        transactions[field] = transactions[field].astype("string").str.strip().replace("", pd.NA)
    dates = parsed_dates(transactions["invoice_date"])
    quantity = pd.to_numeric(transactions["quantity"], errors="coerce")
    price = pd.to_numeric(transactions["unit_price"], errors="coerce")
    # Avoid silent int64 wraparound when both source columns happen to be integers.
    value = quantity.astype(float) * price.astype(float)
    numeric_valid = quantity.notna() & price.notna() & value.notna()
    for series in [quantity, price, value]:
        numeric_valid &= ~series.isin([float("inf"), float("-inf")])
    core_valid = dates.notna() & numeric_valid & transactions["invoice_no"].notna() & transactions["stock_code"].notna()
    adjustment = transactions["invoice_no"].str.startswith("C", na=False) | quantity.lt(0)
    line_type = pd.Series("invalid_core", index=transactions.index, dtype="string")
    line_type.loc[core_valid] = "purchase"
    line_type.loc[core_valid & adjustment] = "adjustment"
    line_type.loc[core_valid & ~adjustment & (quantity.le(0) | price.le(0))] = "non_purchase"
    transactions["quantity"] = quantity
    transactions["unit_price"] = price
    transactions["line_value"] = value.where(core_valid)
    transactions["line_type"] = line_type
    transactions["invoice_date"] = dates.map(iso)

    purchases = transactions.loc[transactions["line_type"].eq("purchase")]
    if purchases.empty:
        orders = pd.DataFrame(columns=ORDER_COLUMNS)
    else:
        orders = purchases.groupby("invoice_no", sort=True).agg(
            order_date=("invoice_date", "min"), order_value=("line_value", "sum"),
            line_count=("invoice_no", "size"), customer_id=("customer_id", "first"),
            country=("country", "first"), customer_count=("customer_id", "nunique"),
            country_count=("country", "nunique"),
        ).reset_index()
        orders["customer_id_conflict"] = orders["customer_count"].gt(1).astype(int)
        orders.loc[orders["customer_count"].ne(1), "customer_id"] = pd.NA
        # A mixed-country invoice cannot truthfully be assigned the first country.
        orders.loc[orders["country_count"].ne(1), "country"] = pd.NA
        orders = orders[ORDER_COLUMNS]

    identified = orders.loc[orders["customer_id"].notna()]
    if identified.empty:
        customers = pd.DataFrame(columns=CUSTOMER_COLUMNS)
    else:
        customers = identified.groupby("customer_id", sort=True).agg(
            first_observed_order=("order_date", "min"), last_observed_order=("order_date", "max"),
            observed_orders=("invoice_no", "nunique"), positive_order_value=("order_value", "sum"),
        ).reset_index()[CUSTOMER_COLUMNS]

    if orders.empty:
        monthly = pd.DataFrame(columns=MONTH_COLUMNS)
    else:
        monthly_orders = orders.assign(month=pd.to_datetime(orders["order_date"], format="mixed").dt.strftime("%Y-%m"))
        monthly = monthly_orders.groupby("month", sort=True).agg(
            orders=("invoice_no", "nunique"), positive_sales_value=("order_value", "sum"),
            identified_orders=("customer_id", "count"),
        ).reset_index()
        first_date, last_date = dates.min().date(), dates.max().date()
        monthly["is_complete_month"] = monthly["month"].map(
            lambda month: pd.Period(month, freq="M").start_time.date() >= first_date
            and pd.Period(month, freq="M").end_time.date() <= last_date
        )

    sales = float(orders["order_value"].sum())
    identified_value = float(identified["order_value"].sum())
    class_counts = {name: int(transactions["line_type"].eq(name).sum())
                    for name in ["invalid_core", "adjustment", "non_purchase", "purchase"]}
    summary = {
        "rules_version": 1, "raw_lines": len(data), "export_copies_excluded": len(exclusions),
        "retained_lines": len(transactions), "line_classes": class_counts,
        "extra_exact_rows_retained": int(retained_raw.duplicated(COLUMNS).sum()),
        "excluded_by_sheet": {str(k): int(v) for k, v in exclusions.groupby("source_sheet").size().items()},
        "orders": len(orders), "positive_recorded_sales_value": sales,
        "average_order_value": sales / len(orders) if len(orders) else None,
        "identified_orders": len(identified), "identified_order_value": identified_value,
        "identified_order_share": len(identified) / len(orders) if len(orders) else None,
        "identified_value_share": identified_value / sales if sales else None,
        "observed_customers": len(customers),
        "observed_repeat_customers": int(customers["observed_orders"].gt(1).sum()),
        "customer_id_conflict_orders": int(orders["customer_id_conflict"].sum()),
        "purchase_lines_missing_customer_id": int(purchases["customer_id"].isna().sum()),
        "source_date_range": {"start": iso(dates.min()), "end": iso(dates.max())},
        "partial_sales_months": monthly.loc[~monthly["is_complete_month"].astype(bool), "month"].tolist(),
    }
    if len(data) != len(transactions) + len(exclusions) or len(transactions) != sum(class_counts.values()):
        raise AssertionError("Row reconciliation failed")
    if not math.isclose(float(purchases["line_value"].sum()), sales, rel_tol=1e-12, abs_tol=0.01):
        raise AssertionError("Purchase lines and order values do not reconcile")
    if not math.isclose(float(monthly["positive_sales_value"].sum()), sales, rel_tol=1e-12, abs_tol=0.01):
        raise AssertionError("Monthly and total order values do not reconcile")
    return {"transactions": transactions, "export_exclusions": exclusions,
            "orders": orders, "customers": customers, "monthly": monthly, "summary": summary}


def save_database(tables, path):
    """Publish a complete derived SQLite file after checking its contents."""
    path = Path(path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".building")
    try:
        with closing(sqlite3.connect(temporary)) as db:
            for name in ["transactions", "orders", "customers"]:
                tables[name].to_sql(name, db, index=False, chunksize=10000)
            exclusions = tables["export_exclusions"][["source_sheet", "source_row", "invoice_no", "stock_code", "exclusion_reason"]].copy()
            exclusions["invoice_no"] = normalized_text(exclusions["invoice_no"])
            exclusions["stock_code"] = normalized_text(exclusions["stock_code"])
            exclusions.to_sql("export_exclusions", db, index=False, chunksize=10000)
            tables["monthly"].to_sql("monthly_sales", db, index=False)
            pd.DataFrame([{"key": key, "value": json.dumps(value, allow_nan=False)}
                          for key, value in tables["summary"].items()]).to_sql("pipeline_metadata", db, index=False)
            db.executescript((ROOT / "sql" / "00_views.sql").read_text(encoding="utf-8"))
            retained = db.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
            excluded = db.execute("SELECT COUNT(*) FROM export_exclusions").fetchone()[0]
            order_count, sales = db.execute("SELECT COUNT(*), COALESCE(SUM(order_value), 0) FROM orders").fetchone()
            if retained + excluded != tables["summary"]["raw_lines"] or order_count != tables["summary"]["orders"]:
                raise AssertionError("SQLite row/order reconciliation failed")
            if not math.isclose(sales, tables["summary"]["positive_recorded_sales_value"], rel_tol=1e-12, abs_tol=0.01):
                raise AssertionError("SQLite sales values do not reconcile")
            if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise AssertionError("SQLite integrity check failed")
        temporary.replace(path)
    finally:
        if temporary.exists():
            # This exact single file was created by this invocation.
            temporary.unlink()


def render_report(summary):
    sales = summary["positive_recorded_sales_value"]
    share = summary["identified_value_share"]
    share_text = f"{share:.2%}" if share is not None else "undefined"
    lines = ["# Cleaning and coverage report", "", "Rules: [version 1](../docs/cleaning_rules.md).", "",
        "## Row reconciliation", "",
        f"- Raw invoice lines: {summary['raw_lines']:,}.",
        f"- Cross-sheet exported copies excluded: {summary['export_copies_excluded']:,}.",
        f"- Retained transaction lines: {summary['retained_lines']:,}.",
        f"- Extra identical raw rows retained: {summary['extra_exact_rows_retained']:,}; within-sheet multiplicity is preserved.",
        "", "| Retained line class | Rows |", "|---|---:|"]
    lines.extend(f"| {key} | {value:,} |" for key, value in summary["line_classes"].items())
    lines.extend(["", "## Purchase and customer populations", "",
        f"- Qualifying orders: {summary['orders']:,}.",
        f"- Positive recorded sales value: GBP {sales:,.2f}.",
        f"- Orders linked to an unambiguous customer: {summary['identified_orders']:,}.",
        f"- Identified-customer order value: GBP {summary['identified_order_value']:,.2f} ({share_text} of positive value).",
        f"- Identified customers: {summary['observed_customers']:,}.",
        f"- Observed customers with multiple distinct orders: {summary['observed_repeat_customers']:,}.",
        f"- Conflicting-customer orders: {summary['customer_id_conflict_orders']:,}.",
        f"- Qualifying purchase lines with missing original customer IDs: {summary['purchase_lines_missing_customer_id']:,}.",
        "", "## Time coverage", "",
        f"Observed span: {summary['source_date_range']['start']} to {summary['source_date_range']['end']}.",
        f"Partial sales months: {', '.join(summary['partial_sales_months']) or 'none'}.",
        "", "## Interpretation and limits", "",
        "- Anonymous purchases remain in sales; identified-customer histories cover a subset of that business activity.",
        "- Positive recorded value includes qualifying positive charges; it is not merchandise-only sales, net revenue or profit.",
        "- Adjustment and nonpositive-value lines remain traceable but are outside the positive-purchase metric.",
        "- Within-sheet repeated lines are not proven errors. Keep the policy visible when interpreting totals.",
        "- Repeat-customer counts describe observed history, not a fixed-window retention rate or causal marketing impact.",
        "", "## Reproducibility", "", f"Source SHA-256: `{summary.get('source_sha256', 'fixture')}`", "",
        "All row/value checks passed before the derived database was published.", ""])
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=ROOT / "data/raw/online_retail_II.xlsx")
    parser.add_argument("--database", type=Path, default=ROOT / "data/processed/retail.sqlite")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "reports")
    args = parser.parse_args(argv)
    if not args.input.is_file():
        parser.error("Source workbook not found; run download_data.py first")
    if args.input.resolve() == args.database.resolve():
        parser.error("Derived database cannot replace the source workbook")
    checksum = hashlib.sha256(args.input.read_bytes()).hexdigest()
    source_metadata = args.input.with_suffix(".source.json")
    if source_metadata.exists() and json.loads(source_metadata.read_text(encoding="utf-8")).get("sha256") != checksum:
        raise ValueError("Source checksum differs from download provenance")
    print("Loading source sheets and applying documented cleaning rules...", flush=True)
    tables = build_tables(load_source(args.input))
    tables["summary"].update({"source_sha256": checksum, "built_at_utc": datetime.now(timezone.utc).isoformat()})
    if hashlib.sha256(args.input.read_bytes()).hexdigest() != checksum:
        raise AssertionError("Source workbook changed during cleaning")
    print("Saving reconciled analysis tables...", flush=True)
    save_database(tables, args.database)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "cleaning_summary.json").write_text(json.dumps(tables["summary"], indent=2, allow_nan=False) + "\n", encoding="utf-8")
    (args.output_dir / "cleaning_report.md").write_text(render_report(tables["summary"]), encoding="utf-8")
    tables["monthly"].to_csv(args.output_dir / "monthly_sales.csv", index=False)
    print(f"Published {len(tables['orders']):,} qualifying orders to {args.database.resolve()}")
    print(f"Cleaning report: {(args.output_dir / 'cleaning_report.md').resolve()}")


if __name__ == "__main__":
    main()

