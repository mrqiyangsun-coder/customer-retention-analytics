"""Profile source data without cleaning, deleting or rewriting any records."""

import argparse
from datetime import datetime, timezone
import hashlib
from itertools import combinations
import json
from numbers import Number
from pathlib import Path
import platform

import openpyxl
import pandas as pd


ROOT = Path(__file__).resolve().parent
DATASET_URL = "https://archive.ics.uci.edu/dataset/502/online+retail+ii"
COLUMNS = ["invoice_no", "stock_code", "description", "quantity", "invoice_date", "unit_price", "customer_id", "country"]
ALIASES = {
    "invoice": "invoice_no", "invoiceno": "invoice_no",
    "stockcode": "stock_code", "description": "description",
    "quantity": "quantity", "invoicedate": "invoice_date",
    "price": "unit_price", "unitprice": "unit_price",
    "customerid": "customer_id", "country": "country",
}


def normalized_text(series):
    """Treat blank cells as missing; preserve string IDs and integer-like IDs."""
    return series.astype("string").str.strip().replace("", pd.NA).str.replace(r"^(\d+)\.0$", r"\1", regex=True)


def iso(value):
    return None if pd.isna(value) else value.isoformat()


def parsed_dates(series):
    # openpyxl supplies date-formatted Excel cells as datetime objects.
    # Unformatted numeric cells are ambiguous; never infer epoch nanoseconds.
    numeric_cells = series.map(lambda value: isinstance(value, Number)).astype(bool)
    return pd.to_datetime(series.mask(numeric_cells), errors="coerce", format="mixed")


def audit_workbook(path):
    """Return JSON-safe diagnostics and per-sheet monthly counts."""
    path = Path(path).resolve()
    checksum = hashlib.sha256(path.read_bytes()).hexdigest()
    frames = []
    sheet_reports = []
    with pd.ExcelFile(path, engine="openpyxl") as workbook:
        for sheet_name in workbook.sheet_names:
            source = pd.read_excel(workbook, sheet_name=sheet_name, dtype=object, keep_default_na=False)
            rename = {}
            for column in source.columns:
                key = str(column).strip().lower().replace(" ", "").replace("_", "")
                if key in ALIASES:
                    rename[column] = ALIASES[key]
            frame = source.rename(columns=rename)
            missing = sorted(set(COLUMNS) - set(frame.columns))
            if missing:
                raise ValueError(f"Sheet {sheet_name!r} is missing required columns: {', '.join(missing)}")
            if frame.columns.duplicated().any():
                raise ValueError(f"Sheet {sheet_name!r} has ambiguous duplicate column names")
            frame = frame[COLUMNS].copy()
            # Keep the raw values for exact-row comparisons; parsed columns are
            # separate so invalid values do not collapse into duplicate NaNs.
            frame["source_sheet"] = sheet_name
            frames.append(frame)
            dates = parsed_dates(frame["invoice_date"])
            sheet_reports.append({
                "name": sheet_name, "raw_rows": len(frame),
                "original_columns": [str(c) for c in source.columns],
                "start": iso(dates.min()), "end": iso(dates.max()),
                "extra_exact_rows_within_sheet": int(frame.duplicated(subset=COLUMNS).sum()),
            })

    data = pd.concat(frames, ignore_index=True)
    missing_values = {
        column: int(normalized_text(data[column]).isna().sum()) for column in COLUMNS
    }
    dates = parsed_dates(data["invoice_date"])
    quantity = pd.to_numeric(data["quantity"], errors="coerce")
    price = pd.to_numeric(data["unit_price"], errors="coerce")
    invoices = normalized_text(data["invoice_no"])
    customers = normalized_text(data["customer_id"])
    cancelled = invoices.str.upper().str.startswith("C", na=False)

    flags = {
        "cancellation_rows": int(cancelled.sum()),
        "negative_quantity": int(quantity.lt(0).sum()),
        "zero_quantity": int(quantity.eq(0).sum()),
        "negative_unit_price": int(price.lt(0).sum()),
        "zero_unit_price": int(price.eq(0).sum()),
        "invalid_quantity": int((quantity.isna() & normalized_text(data["quantity"]).notna()).sum()),
        "invalid_unit_price": int((price.isna() & normalized_text(data["unit_price"]).notna()).sum()),
        "invalid_invoice_date": int((dates.isna() & normalized_text(data["invoice_date"]).notna()).sum()),
    }
    valid = (quantity.gt(0) & price.gt(0) & ~cancelled & invoices.notna() & dates.notna()).fillna(False)
    candidate = pd.DataFrame({"invoice": invoices[valid], "customer": customers[valid]})
    orders_per_customer = candidate.dropna(subset=["customer"]).groupby("customer")["invoice"].nunique()
    valid_date_data = pd.DataFrame({
        "source_sheet": data["source_sheet"], "month": dates.dt.strftime("%Y-%m")
    }).dropna(subset=["month"])
    monthly = valid_date_data.groupby(["source_sheet", "month"], sort=True).size().reset_index(name="raw_rows")

    # Group by original cell values, not parsed/coerced values. These are
    # duplicate patterns to investigate, not rows to automatically remove.
    sheet_count_per_pattern = data.groupby(COLUMNS, dropna=False, sort=False)["source_sheet"].nunique()
    overlaps = []
    for first, second in combinations(sheet_reports, 2):
        if first["start"] is not None and second["start"] is not None:
            start = max(first["start"], second["start"])
            end = min(first["end"], second["end"])
            if start <= end:
                overlaps.append({"sheets": [first["name"], second["name"]], "start": start, "end": end})

    provenance = None
    metadata_path = path.with_suffix(".source.json")
    if metadata_path.exists():
        provenance = json.loads(metadata_path.read_text(encoding="utf-8"))
        if provenance.get("sha256") != checksum:
            raise ValueError("Source checksum no longer matches the recorded download provenance")

    report = {
        "dataset": "UCI Online Retail II", "dataset_url": DATASET_URL,
        "audited_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_file": path.name, "sha256": checksum, "size_bytes": path.stat().st_size,
        "download_provenance": provenance,
        "runtime": {"python": platform.python_version(), "pandas": pd.__version__, "openpyxl": openpyxl.__version__},
        "raw_rows": len(data), "sheets": sheet_reports,
        "date_range": {"start": iso(dates.min()), "end": iso(dates.max())},
        "rows_with_valid_dates": int(dates.notna().sum()),
        "missing_values": missing_values, "flags": flags,
        "duplicates": {
            "extra_exact_rows": int(data.duplicated(subset=COLUMNS).sum()),
            "patterns_in_multiple_sheets": int(sheet_count_per_pattern.gt(1).sum()),
        },
        "sheet_date_overlaps": overlaps,
        "purchase_candidates": {
            "definition": "Known invoice/date, positive quantity/price, invoice not prefixed C. Provisional audit diagnostic; duplicates retained.",
            "rows": int(valid.sum()),
            "distinct_invoices": int(candidate["invoice"].nunique()),
            "rows_without_customer_id": int(candidate["customer"].isna().sum()),
            "known_customers": int(candidate["customer"].nunique()),
            "customers_with_multiple_invoices": int(orders_per_customer.gt(1).sum()),
        },
        "limitations": [
            "Raw records are retained; counts and temporal summaries may include workbook overlap and duplicate patterns.",
            "Flag counts overlap and must not be added as mutually exclusive categories.",
            "An invoice can have many lines; invoice counts are not line counts.",
            "First/last observed months need completeness review before comparing monthly totals.",
            "Observed first purchase is not necessarily acquisition; no causal campaign effect or profit is established.",
        ],
    }
    return report, monthly


def render_markdown(report):
    """Write a readable counterpart to the full machine-readable report."""
    count = report["raw_rows"]
    missing_id = report["missing_values"]["customer_id"]
    fraction = f"{missing_id / count:.2%}" if count else "n/a"
    lines = [
        "# Data quality audit", "", f"Generated (UTC): {report['audited_at_utc']}", "",
        f"Source: [UCI Online Retail II]({DATASET_URL}); CC BY 4.0; Chen, D. (2012), DOI 10.24432/C5CG6D.",
        "", "## Observed workbook", "",
        f"- Raw invoice lines: **{count:,}** (not distinct orders).",
        f"- Observed dates: {report['date_range']['start']} to {report['date_range']['end']}.",
        f"- Missing customer IDs: **{missing_id:,} ({fraction})**.",
        f"- Extra exact rows beyond first occurrences: **{report['duplicates']['extra_exact_rows']:,}**.",
        f"- Exact row patterns appearing in multiple sheets: **{report['duplicates']['patterns_in_multiple_sheets']:,}**.",
        "", "| Sheet | Raw rows | First timestamp | Last timestamp |", "|---|---:|---|---|",
    ]
    for sheet in report["sheets"]:
        lines.append(f"| {sheet['name']} | {sheet['raw_rows']:,} | {sheet['start']} | {sheet['end']} |")
    lines.extend(["", "## Missing values", "", "| Column | Missing or blank |", "|---|---:|"])
    lines.extend(f"| {key} | {value:,} |" for key, value in report["missing_values"].items())
    lines.extend(["", "## Quality flags (overlapping counts)", "", "| Flag | Rows |", "|---|---:|"])
    lines.extend(f"| {key} | {value:,} |" for key, value in report["flags"].items())
    lines.extend(["", "## Sheet date overlap", ""])
    if report["sheet_date_overlaps"]:
        lines.extend(f"- {' / '.join(item['sheets'])}: {item['start']} through {item['end']}." for item in report["sheet_date_overlaps"])
    else:
        lines.append("No overlapping observed date ranges found.")
    candidate = report["purchase_candidates"]
    lines.extend(["", "## Purchase-candidate diagnostics", "", candidate["definition"], ""])
    lines.extend(f"- {key}: {value:,}" for key, value in candidate.items() if key != "definition")
    lines.extend(["", "## Decisions required before cleaning", "",
        "1. Investigate cross-sheet overlap and distinguish repeated exports from legitimate repeated line items.",
        "2. Define purchases, cancellations and adjustment handling; do not silently discard negative lines.",
        "3. Keep unidentified-customer coverage visible and define the population for retention analysis.",
        "4. Treat partial months and incomplete future observation windows explicitly.",
        "", "## Limitations", ""])
    lines.extend(f"- {item}" for item in report["limitations"])
    lines.extend(["", "## Reproducibility", "", f"Workbook SHA-256: `{report['sha256']}`", "",
                  f"Runtime: `{json.dumps(report['runtime'], sort_keys=True)}`", ""])
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=ROOT / "data/raw/online_retail_II.xlsx")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "reports")
    args = parser.parse_args(argv)
    if not args.input.is_file():
        parser.error(f"Workbook not found: {args.input}. Run download_data.py first.")
    print("Reading every workbook sheet and auditing raw records...", flush=True)
    report, monthly = audit_workbook(args.input)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "data_audit.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    (args.output_dir / "data_audit.md").write_text(render_markdown(report), encoding="utf-8")
    monthly.to_csv(args.output_dir / "monthly_coverage.csv", index=False)
    print(f"Audited {report['raw_rows']:,} raw lines across {len(report['sheets'])} sheets.")
    print(f"Reports saved to {args.output_dir.resolve()}")


if __name__ == "__main__":
    main()

