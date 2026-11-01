from contextlib import closing
import json
import sqlite3
import unittest

import pandas as pd

from analysis import build_summary, read_analysis


def fixture_database():
    db = sqlite3.connect(":memory:")
    db.executescript("""
        CREATE TABLE orders(invoice_no TEXT, order_date TEXT, order_value REAL, customer_id TEXT, customer_id_conflict INTEGER);
        CREATE TABLE customers(customer_id TEXT, first_observed_order TEXT, last_observed_order TEXT, observed_orders INTEGER, positive_order_value REAL);
        CREATE TABLE pipeline_metadata(key TEXT, value TEXT);
        CREATE VIEW customer_orders AS SELECT * FROM orders WHERE customer_id IS NOT NULL AND customer_id_conflict=0;
        INSERT INTO orders VALUES
        ('1','2010-01-05',10,'A',0),('2','2010-01-10',20,'B',0),('3','2010-01-20',5,'A',0),
        ('4','2010-03-02',30,'A',0),('5','2010-03-08',40,'C',0),('6','2010-03-09',50,NULL,0),
        ('7','2010-04-05',60,'A',0);
        INSERT INTO customers VALUES
        ('A','2010-01-05','2010-04-05',4,105),('B','2010-01-10','2010-01-10',1,20),
        ('C','2010-03-08','2010-03-08',1,40);
    """)
    db.execute("INSERT INTO pipeline_metadata VALUES (?,?)", (
        "source_date_range", json.dumps({"start": "2010-01-01", "end": "2010-04-10"})))
    return db


class AnalysisTests(unittest.TestCase):
    def test_summary_uses_identified_concentration_and_complete_month_denominators(self):
        with closing(fixture_database()) as db:
            summary = build_summary(read_analysis(db))
        self.assertEqual(summary.get("observed_orders"), 7)
        self.assertEqual(summary["observed_positive_value"], 215)
        self.assertEqual(summary["latest_complete_month"]["month"], "2010-03")
        self.assertAlmostEqual(summary["latest_complete_month"]["previously_observed_value_share_identified"], 30 / 70)
        self.assertEqual(summary["top_decile"]["customer_count"], 1)
        self.assertAlmostEqual(summary["top_decile"]["identified_value_share"], 105 / 165)
        self.assertIsNone(summary["matched_year_comparison"])
        self.assertIsNone(summary["month1_activity_excluding_initial_cohort"])

    def test_calendar_spine_keeps_zero_month_and_undefined_growth(self):
        with closing(fixture_database()) as db:
            tables = read_analysis(db)
        self.assertIn("monthly", tables)
        monthly = tables["monthly"].set_index("month")
        self.assertEqual(monthly.index.tolist(), ["2010-01", "2010-02", "2010-03", "2010-04"])
        self.assertEqual(monthly.loc["2010-02", "orders"], 0)
        self.assertEqual(monthly.loc["2010-02", "positive_sales_value"], 0)
        self.assertEqual(monthly.loc["2010-02", "mom_sales_change"], -1)
        self.assertTrue(pd.isna(monthly.loc["2010-03", "mom_sales_change"]))
        self.assertTrue(pd.isna(monthly.loc["2010-04", "mom_sales_change"]))
        self.assertEqual(monthly.loc["2010-04", "is_complete_month"], 0)

    def test_monthly_customer_segments_count_customers_once_and_reconcile_value(self):
        with closing(fixture_database()) as db:
            tables = read_analysis(db)
        self.assertIn("monthly", tables)
        monthly = tables["monthly"].set_index("month")
        self.assertEqual(monthly.loc["2010-01", "first_observed_customers"], 2)
        self.assertEqual(monthly.loc["2010-01", "first_observed_month_value"], 35)
        self.assertEqual(monthly.loc["2010-03", "previously_observed_customers"], 1)
        self.assertEqual(monthly.loc["2010-03", "previously_observed_value"], 30)
        self.assertEqual(monthly.loc["2010-03", "first_observed_month_value"], 40)
        self.assertEqual(monthly.loc["2010-03", "anonymous_value"], 50)
        self.assertEqual(monthly.loc["2010-03", "positive_sales_value"], 120)

    def test_cohorts_count_distinct_people_and_mask_partial_future_windows(self):
        with closing(fixture_database()) as db:
            tables = read_analysis(db)
        self.assertIn("cohorts", tables)
        cohort = tables["cohorts"].set_index(["cohort_month", "month_age"])
        self.assertEqual(cohort.loc[("2010-01", 0), "cohort_size"], 2)
        self.assertEqual(cohort.loc[("2010-01", 0), "active_customers"], 2)
        self.assertEqual(cohort.loc[("2010-01", 1), "activity_rate"], 0)
        self.assertEqual(cohort.loc[("2010-01", 2), "activity_rate"], .5)
        self.assertNotIn(("2010-01", 3), cohort.index)
        self.assertNotIn(("2010-03", 1), cohort.index)

    def test_concentration_uses_identified_value_and_deterministic_rank(self):
        with closing(fixture_database()) as db:
            tables = read_analysis(db)
        self.assertIn("concentration", tables)
        ranked = tables["concentration"]
        self.assertEqual(ranked.iloc[0]["customer_id"], "A")
        self.assertAlmostEqual(ranked.iloc[0]["cumulative_value_share"], 105 / 165)
        self.assertAlmostEqual(ranked.iloc[-1]["cumulative_value_share"], 1)
        self.assertEqual(ranked.iloc[-1]["customer_rank"], 3)

    def test_yoy_growth_uses_same_complete_calendar_month(self):
        with closing(fixture_database()) as db:
            db.execute("UPDATE pipeline_metadata SET value=? WHERE key='source_date_range'", (
                json.dumps({"start": "2010-01-01", "end": "2011-01-31"}),))
            db.execute("INSERT INTO orders VALUES ('8','2011-01-05',70,'A',0)")
            db.execute("UPDATE customers SET last_observed_order='2011-01-05', observed_orders=5, positive_order_value=175 WHERE customer_id='A'")
            tables = read_analysis(db)
        self.assertIn("monthly", tables)
        january = tables["monthly"].set_index("month").loc["2011-01"]
        self.assertAlmostEqual(january["yoy_sales_change"], 1)

    def test_matched_year_summary_decomposes_value_orders_and_average_order_value(self):
        with closing(fixture_database()) as db:
            db.execute("UPDATE pipeline_metadata SET value=? WHERE key='source_date_range'", (
                json.dumps({"start": "2010-01-01", "end": "2011-01-31"}),))
            db.execute("INSERT INTO orders VALUES ('8','2011-01-05',70,'A',0)")
            db.execute("UPDATE customers SET last_observed_order='2011-01-05', observed_orders=5, positive_order_value=175 WHERE customer_id='A'")
            comparison = build_summary(read_analysis(db))["matched_year_comparison"]
        self.assertIn("aov_change", comparison)
        self.assertEqual(comparison["matched_month_numbers"], ["01"])
        self.assertAlmostEqual(comparison["earlier_aov"], 35 / 3)
        self.assertAlmostEqual(comparison["later_aov"], 70)
        self.assertAlmostEqual(comparison["aov_change"], 5)

    def test_empty_customer_population_has_no_fabricated_cohorts_or_concentration(self):
        with closing(fixture_database()) as db:
            db.execute("DELETE FROM customers")
            db.execute("DELETE FROM orders")
            tables = read_analysis(db)
        self.assertIn("cohorts", tables)
        self.assertTrue(tables["cohorts"].empty)
        self.assertTrue(tables["concentration"].empty)
        self.assertEqual(int(tables["monthly"].orders.sum()), 0)


if __name__ == "__main__":
    unittest.main()
