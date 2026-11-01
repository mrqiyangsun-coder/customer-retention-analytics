import hashlib
import json
from pathlib import Path
import subprocess
import sys
import shutil
import unittest
import uuid

import pandas as pd

from audit import audit_workbook


LEGACY = ["Invoice", "StockCode", "Description", "Quantity", "InvoiceDate", "Price", "Customer ID", "Country"]
MODERN = ["InvoiceNo", "StockCode", "Description", "Quantity", "InvoiceDate", "UnitPrice", "CustomerID", "Country"]


class AuditTests(unittest.TestCase):
    def setUp(self):
        # Use ordinary inherited permissions; Windows restricted temp-directory
        # ACLs can prevent workbook writes in the desktop execution sandbox.
        root = Path(__file__).resolve().parents[1] / "data" / "test_artifacts"
        self.temp_path = root / uuid.uuid4().hex
        self.temp_path.mkdir(parents=True)
        self.addCleanup(self.clean_artifacts, root)
        self.path = self.temp_path / "fixture.xlsx"
        shared = ["A101", "X", "Item X", 1, "2010-01-02", 5, 10, "UK"]
        first = [
            ["A100", "X", "Item X", 2, "2010-01-01", 5, 10, "UK"],
            ["A100", "Y", "Item Y", 1, "2010-01-01", 3, 10, "UK"],
            shared,
            ["c100", "X", "Item X", -1, "2010-01-03", 5, 10, "UK"],
            ["A102", "Z", "Item Z", 1, "2010-01-04", 0, None, "UK"],
        ]
        second = [
            shared,
            ["A103", "X", "Item X", 1, "2010-02-01", 8, "  ", "UK"],
            ["A104", "Y", "Item Y", 1, "2010-02-02", 4, 20, "UK"],
            ["A105", "Q", "Item Q", "bad", "not a date", -2, 20, "US"],
        ]
        with pd.ExcelWriter(self.path, engine="openpyxl") as writer:
            pd.DataFrame(first, columns=LEGACY).to_excel(writer, sheet_name="First", index=False)
            pd.DataFrame(second, columns=MODERN).to_excel(writer, sheet_name="Second", index=False)

    def clean_artifacts(self, root):
        target = self.temp_path.resolve()
        if target.parent != root.resolve():
            raise RuntimeError("Unexpected test-artifact cleanup path")
        shutil.rmtree(target)

    def test_counts_lines_and_distinct_invoices_separately(self):
        # Catches counting each invoice line or cross-sheet repeat as a new order.
        report, monthly = audit_workbook(self.path)
        self.assertEqual(report.get("raw_rows"), 9)
        self.assertEqual(report["purchase_candidates"]["rows"], 6)
        self.assertEqual(report["purchase_candidates"]["distinct_invoices"], 4)
        self.assertEqual(report["purchase_candidates"]["known_customers"], 2)
        self.assertEqual(report["purchase_candidates"]["customers_with_multiple_invoices"], 1)
        self.assertEqual(int(monthly["raw_rows"].sum()), 8)

    def test_reports_missing_and_invalid_values_without_dropping_rows(self):
        # Catches losing blank IDs, conflating coercion failures with missing inputs, or ignoring C invoices.
        report, _ = audit_workbook(self.path)
        self.assertEqual(report.get("raw_rows"), 9)
        self.assertEqual(report["missing_values"]["customer_id"], 2)
        self.assertEqual(report["flags"]["invalid_quantity"], 1)
        self.assertEqual(report["flags"]["invalid_invoice_date"], 1)
        self.assertEqual(report["flags"]["cancellation_rows"], 1)
        self.assertEqual(report["flags"]["negative_quantity"], 1)
        self.assertEqual(report["flags"]["zero_unit_price"], 1)
        self.assertEqual(report["flags"]["negative_unit_price"], 1)

    def test_reports_sheet_overlap_and_duplicate_patterns(self):
        # Catches treating the two workbook sheets as disjoint or deleting overlap while auditing.
        report, _ = audit_workbook(self.path)
        self.assertEqual(report.get("raw_rows"), 9)
        self.assertEqual(report["duplicates"]["extra_exact_rows"], 1)
        self.assertEqual(report["duplicates"]["patterns_in_multiple_sheets"], 1)
        self.assertEqual(len(report["sheet_date_overlaps"]), 1)
        self.assertEqual(report["sheets"][0]["raw_rows"], 5)
        self.assertEqual(report["sheets"][1]["raw_rows"], 4)

    def test_audit_does_not_change_source_bytes(self):
        before = hashlib.sha256(self.path.read_bytes()).hexdigest()
        report, _ = audit_workbook(self.path)
        self.assertEqual(report.get("raw_rows"), 9)
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).hexdigest(), before)
        json.dumps(report, allow_nan=False)

    def test_missing_required_column_fails_with_column_name(self):
        pd.DataFrame(columns=LEGACY[:-1]).to_excel(self.path, index=False)
        with self.assertRaisesRegex(ValueError, "country"):
            audit_workbook(self.path)

    def test_empty_workbook_sheet_has_zero_counts_and_no_date_bounds(self):
        pd.DataFrame(columns=LEGACY).to_excel(self.path, index=False)
        report, monthly = audit_workbook(self.path)
        self.assertEqual(report.get("raw_rows"), 0)
        self.assertIsNone(report["date_range"]["start"])
        self.assertEqual(report["purchase_candidates"]["distinct_invoices"], 0)
        self.assertTrue(monthly.empty)

    def test_literal_na_text_is_preserved_and_does_not_collapse_raw_patterns(self):
        # Catches pandas treating literal identifiers/text such as NA as empty cells.
        rows = [
            ["A100", "X", "NA", 1, "2010-01-01", 5, "NA", "NULL"],
            ["A100", "X", None, 1, "2010-01-01", 5, "NA", "NULL"],
        ]
        pd.DataFrame(rows, columns=LEGACY).to_excel(self.path, index=False)
        report, _ = audit_workbook(self.path)
        self.assertEqual(report["missing_values"]["description"], 1)
        self.assertEqual(report["missing_values"]["customer_id"], 0)
        self.assertEqual(report["missing_values"]["country"], 0)
        self.assertEqual(report["duplicates"]["extra_exact_rows"], 0)

    def test_numeric_date_cells_are_flagged_instead_of_becoming_1970_timestamps(self):
        # Catches silently interpreting a malformed numeric date as nanoseconds.
        rows = [
            ["A100", "X", "Item", 1, 123, 5, 10, "UK"],
            ["A101", "X", "Item", 1, "2010-01-01", 5, 10, "UK"],
        ]
        pd.DataFrame(rows, columns=LEGACY).to_excel(self.path, index=False)
        report, monthly = audit_workbook(self.path)
        self.assertEqual(report["flags"]["invalid_invoice_date"], 1)
        self.assertEqual(report["date_range"]["start"], "2010-01-01T00:00:00")
        self.assertEqual(report["purchase_candidates"]["rows"], 1)
        self.assertEqual(list(monthly["month"]), ["2010-01"])

    def test_cli_writes_three_reports_with_reconciled_counts(self):
        output = self.temp_path / "reports"
        result = subprocess.run(
            [sys.executable, "audit.py", "--input", str(self.path), "--output-dir", str(output)],
            capture_output=True, text=True, cwd=Path(__file__).resolve().parents[1],
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((output / "data_audit.json").exists())
        report = json.loads((output / "data_audit.json").read_text(encoding="utf-8"))
        self.assertEqual(report["raw_rows"], 9)
        self.assertIn("Data quality audit", (output / "data_audit.md").read_text(encoding="utf-8"))
        monthly = pd.read_csv(output / "monthly_coverage.csv")
        self.assertEqual(int(monthly.raw_rows.sum()), 8)


if __name__ == "__main__":
    unittest.main()
