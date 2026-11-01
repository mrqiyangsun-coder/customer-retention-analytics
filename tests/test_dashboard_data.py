"""Hand-derived dashboard metric contracts; no production database required."""
from pathlib import Path
import shutil
import unittest
import uuid

import pandas as pd

from dashboard_data import load_reports, period_metrics, select_months


def months():
    return pd.DataFrame([
        dict(month='2011-01', orders=1, positive_sales_value=100, is_complete_month=1,
             first_observed_month_value=60, previously_observed_value=30, anonymous_value=10),
        dict(month='2011-02', orders=9, positive_sales_value=90, is_complete_month=1,
             first_observed_month_value=20, previously_observed_value=50, anonymous_value=20),
        dict(month='2011-03', orders=1, positive_sales_value=999, is_complete_month=0,
             first_observed_month_value=0, previously_observed_value=999, anonymous_value=0),
    ])


class DashboardDataTests(unittest.TestCase):
    def test_selected_aov_is_value_divided_by_orders_not_mean_of_monthly_aovs(self):
        result = period_metrics(select_months(months(), '2011-01', '2011-03'))
        self.assertEqual(result['orders'], 10)
        self.assertEqual(result['value'], 190)
        self.assertEqual(result['aov'], 19)
        self.assertAlmostEqual(result['identified_value_share'], 160 / 190)

    def test_range_inclusive_partial_excluded_original_unchanged(self):
        original = months()
        selected = select_months(original, '2011-02', '2011-03')
        self.assertEqual(selected.month.tolist(), ['2011-02'])
        self.assertEqual(len(original), 3)
        self.assertEqual(period_metrics(selected)['aov'], 10)

    def test_reversed_range_rejected_and_empty_range_has_no_invented_average(self):
        with self.assertRaises(ValueError):
            select_months(months(), '2011-02', '2011-01')
        result = period_metrics(select_months(months(), '2012-01', '2012-02'))
        self.assertEqual(result['orders'], 0)
        self.assertEqual(result['value'], 0)
        self.assertIsNone(result['aov'])
        self.assertIsNone(result['identified_value_share'])

    def test_missing_reports_name_regeneration_command(self):
        with self.assertRaisesRegex(FileNotFoundError, 'analysis.py'):
            load_reports(Path(__file__).parent / 'absent_report_directory')

    def test_reports_preserve_literal_customer_ids_and_do_not_require_database(self):
        root = Path(__file__).resolve().parents[1] / 'data' / 'test_artifacts'
        root.mkdir(parents=True, exist_ok=True)
        target = root / uuid.uuid4().hex
        target.mkdir()
        self.addCleanup(shutil.rmtree, target)
        months().to_csv(target / 'monthly_analysis.csv', index=False)
        (target / 'cohort_activity.csv').write_text('cohort_month,activity_month,month_age,cohort_size,active_customers,activity_rate\n')
        (target / 'customer_concentration.csv').write_text('customer_id,customer_value,customer_rank,total_customers,customer_share,cumulative_value_share\nNA,10,1,2,0.5,0.5\n001,10,2,2,1,1\n')
        (target / 'analysis_summary.json').write_text('{}')
        reports = load_reports(target)
        self.assertEqual(reports['concentration'].customer_id.tolist(), ['NA', '001'])
        self.assertEqual(reports['monthly'].month.tolist(), ['2011-01', '2011-02', '2011-03'])
        self.assertTrue(reports['cohorts'].empty)


if __name__ == '__main__':
    unittest.main()
