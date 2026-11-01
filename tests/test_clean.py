from pathlib import Path
from contextlib import closing
import hashlib
import json
import shutil
import sqlite3
import subprocess
import sys
import unittest
import uuid

import pandas as pd

from audit import COLUMNS
from clean import build_tables, save_database


def fixture():
    # A100 has two legitimate identical lines in First and one exported copy
    # in Second. Keep two occurrences, not three and not one.
    shared = ["A100", "X", "Item X", 2, "2010-01-01", 5, 10, "UK"]
    rows = [
        shared, shared,
        ["A101", "Y", "Item Y", 1, "2010-01-02", 4, "", "UK"],
        ["C100", "X", "Item X", -1, "2010-01-03", 5, 10, "UK"],
        ["A102", "Z", "Item Z", 1, "2010-01-04", 0, 20, "UK"],
        ["A103", "Q", "Item Q", "bad", "broken date", 1, 20, "UK"],
        shared,
        ["A104", "Y", "Item Y", 1, "2010-02-02", 6, 20, "UK"],
    ]
    raw = pd.DataFrame(rows, columns=COLUMNS)
    raw["source_sheet"] = ["First"] * 6 + ["Second"] * 2
    raw["source_row"] = [2, 3, 4, 5, 6, 7, 2, 3]
    return raw


class CleaningTests(unittest.TestCase):
    def test_cross_sheet_copies_removed_but_within_sheet_multiplicity_preserved(self):
        result = build_tables(fixture())
        self.assertIn("transactions", result)
        self.assertEqual(len(result["transactions"]), 7)
        self.assertEqual(len(result["export_exclusions"]), 1)
        self.assertEqual(len(result["transactions"].query("invoice_no == 'A100'")), 2)
        self.assertIn("Second", result["transactions"].query("invoice_no == 'A100'")["source_sheet"].tolist())

    def test_anonymous_sales_remain_but_no_fictional_customer_is_created(self):
        result = build_tables(fixture())
        self.assertIn("orders", result)
        self.assertEqual(len(result["orders"]), 3)
        self.assertAlmostEqual(result["orders"]["order_value"].sum(), 30)
        anonymous = result["orders"].query("invoice_no == 'A101'").iloc[0]
        self.assertTrue(pd.isna(anonymous["customer_id"]))
        self.assertEqual(set(result["customers"]["customer_id"]), {"10", "20"})
        self.assertEqual(result["summary"]["identified_orders"], 2)
        self.assertAlmostEqual(result["summary"]["identified_order_value"], 26)

    def test_invalid_adjustment_and_zero_price_lines_are_retained_and_classified(self):
        result = build_tables(fixture())
        self.assertIn("transactions", result)
        counts = result["transactions"]["line_type"].value_counts().to_dict()
        self.assertEqual(counts, {"purchase": 4, "adjustment": 1, "non_purchase": 1, "invalid_core": 1})
        self.assertEqual(set(result["orders"]["invoice_no"]), {"A100", "A101", "A104"})

    def test_large_integer_inputs_cannot_overflow_into_negative_purchase_value(self):
        raw = fixture().iloc[[0]].copy()
        raw.loc[:, "quantity"] = 4_000_000_000
        raw.loc[:, "unit_price"] = 4_000_000_000
        result = build_tables(raw)
        self.assertGreater(result["summary"]["positive_recorded_sales_value"], 0)
        self.assertEqual(result["summary"]["positive_recorded_sales_value"], 1.6e19)

    def test_conflicting_ids_keep_sales_but_exclude_order_from_customer_history(self):
        raw = fixture().iloc[[0, 1]].copy()
        raw.loc[raw.index[1], "customer_id"] = 99
        result = build_tables(raw)
        self.assertIn("orders", result)
        self.assertEqual(len(result["orders"]), 1)
        self.assertAlmostEqual(result["orders"].iloc[0]["order_value"], 20)
        self.assertTrue(pd.isna(result["orders"].iloc[0]["customer_id"]))
        self.assertEqual(result["orders"].iloc[0]["customer_id_conflict"], 1)
        self.assertTrue(result["customers"].empty)

    def test_empty_purchase_population_has_no_orders_and_undefined_average(self):
        result = build_tables(fixture().iloc[[3, 4, 5]].copy())
        self.assertIn("orders", result)
        self.assertTrue(result["orders"].empty)
        self.assertTrue(result["customers"].empty)
        self.assertIsNone(result["summary"]["average_order_value"])

    def test_boundary_month_is_marked_partial_and_raw_input_is_unchanged(self):
        raw = fixture()
        original = raw.copy(deep=True)
        result = build_tables(raw)
        self.assertIn("monthly", result)
        monthly = result["monthly"].set_index("month")
        self.assertTrue(bool(monthly.loc["2010-01", "is_complete_month"]))
        self.assertFalse(bool(monthly.loc["2010-02", "is_complete_month"]))
        pd.testing.assert_frame_equal(raw, original)

    def test_empty_source_has_zero_counts_and_no_invented_dates(self):
        result = build_tables(fixture().iloc[0:0].copy())
        self.assertEqual(result["summary"]["raw_lines"], 0)
        self.assertEqual(result["summary"]["orders"], 0)
        self.assertIsNone(result["summary"]["source_date_range"]["start"])
        self.assertIsNone(result["summary"]["identified_value_share"])
        self.assertTrue(result["monthly"].empty)

    def test_cli_preserves_workbook_and_writes_reconciled_reports(self):
        root = Path(__file__).resolve().parents[1] / "data" / "test_artifacts"
        folder = root / uuid.uuid4().hex
        folder.mkdir(parents=True)
        try:
            workbook = folder / "source.xlsx"
            with pd.ExcelWriter(workbook, engine="openpyxl") as writer:
                for name, frame in fixture().groupby("source_sheet", sort=False):
                    frame[COLUMNS].to_excel(writer, sheet_name=name, index=False)
            checksum = hashlib.sha256(workbook.read_bytes()).hexdigest()
            output = folder / "reports"
            result = subprocess.run(
                [sys.executable, "clean.py", "--input", str(workbook),
                 "--database", str(folder / "retail.sqlite"), "--output-dir", str(output)],
                capture_output=True, text=True, cwd=Path(__file__).resolve().parents[1],
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            summary = json.loads((output / "cleaning_summary.json").read_text(encoding="utf-8"))
            self.assertEqual((summary["raw_lines"], summary["retained_lines"], summary["export_copies_excluded"]), (8, 7, 1))
            self.assertEqual(summary["positive_recorded_sales_value"], 30)
            self.assertEqual(hashlib.sha256(workbook.read_bytes()).hexdigest(), checksum)
            self.assertTrue((output / "cleaning_report.md").exists())
            self.assertAlmostEqual(pd.read_csv(output / "monthly_sales.csv").positive_sales_value.sum(), 30)
        finally:
            if folder.resolve().parent != root.resolve():
                raise RuntimeError("Unexpected cleanup path")
            shutil.rmtree(folder)

    def test_database_exposes_reconciled_purchase_and_customer_views(self):
        result = build_tables(fixture())
        self.assertIn("orders", result)
        root = Path(__file__).resolve().parents[1] / "data" / "test_artifacts"
        folder = root / uuid.uuid4().hex
        folder.mkdir(parents=True)
        try:
            path = folder / "retail.sqlite"
            save_database(result, path)
            with closing(sqlite3.connect(path)) as db:
                self.assertEqual(db.execute("SELECT COUNT(*), SUM(order_value) FROM orders").fetchone(), (3, 30))
                self.assertEqual(db.execute("SELECT COUNT(*) FROM purchase_lines").fetchone(), (4,))
                self.assertEqual(db.execute("SELECT COUNT(*) FROM customer_orders").fetchone(), (2,))
                self.assertEqual(db.execute("SELECT COUNT(*) FROM export_exclusions").fetchone(), (1,))
                self.assertEqual(db.execute("SELECT COUNT(*) FROM transactions").fetchone(), (7,))
        finally:
            if folder.resolve().parent != root.resolve():
                raise RuntimeError("Unexpected cleanup path")
            shutil.rmtree(folder)


if __name__ == "__main__":
    unittest.main()
