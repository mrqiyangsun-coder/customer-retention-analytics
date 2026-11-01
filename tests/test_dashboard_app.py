"""Exercise real Streamlit render and filter behavior against hand-derived reports."""
from pathlib import Path
import json
import shutil
import unittest
import uuid
from unittest.mock import patch

import pandas as pd

from test_dashboard_data import months


ROOT = Path(__file__).resolve().parents[1]


def framework_tempdir(suffix=None, prefix=None, dir=None):
    """Give Streamlit's import-time test scratch directory inherited Windows ACLs."""
    parent = Path(dir) if dir else ROOT / 'data' / 'test_artifacts'
    parent.mkdir(parents=True, exist_ok=True)
    path = parent / ((prefix or 'tmp') + uuid.uuid4().hex + (suffix or ''))
    path.mkdir()
    return str(path)


# Streamlit creates TMP_DIR at import. Python's mode-0700 temp directory cannot
# be cleaned under this Windows sandbox; only this allocation is substituted.
# TemporaryDirectory still owns cleanup; production app code is unaffected.
with patch('tempfile.mkdtemp', side_effect=framework_tempdir):
    from streamlit.testing.v1 import AppTest


class DashboardAppTests(unittest.TestCase):
    def setUp(self):
        self.directory = ROOT / 'data' / 'test_artifacts' / uuid.uuid4().hex
        self.directory.mkdir(parents=True)
        self.addCleanup(shutil.rmtree, self.directory)
        months().to_csv(self.directory / 'monthly_analysis.csv', index=False)
        pd.DataFrame([
            ['2011-01', '2011-01', 0, 2, 2, 1.0],
            ['2011-01', '2011-02', 1, 2, 0, 0.0],
            ['2011-02', '2011-02', 0, 1, 1, 1.0],
        ], columns=['cohort_month', 'activity_month', 'month_age', 'cohort_size', 'active_customers', 'activity_rate']).to_csv(self.directory / 'cohort_activity.csv', index=False)
        pd.DataFrame([
            ['001', 120, 1, 2, .5, .75], ['NA', 40, 2, 2, 1, 1],
        ], columns=['customer_id', 'customer_value', 'customer_rank', 'total_customers', 'customer_share', 'cumulative_value_share']).to_csv(self.directory / 'customer_concentration.csv', index=False)
        (self.directory / 'analysis_summary.json').write_text(json.dumps({'generated_at_utc': 'test fixture', 'source_sha256': 'fixture', 'rules_version': 1}))

    def app(self):
        app = AppTest.from_file(str(ROOT / 'streamlit_app.py'), default_timeout=20)
        app.session_state['_report_dir'] = str(self.directory)
        return app.run()

    def test_initial_metrics_and_filtered_single_month_are_correct(self):
        app = self.app()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(app.metric[0].value, 'GBP 190.00')
        self.assertEqual(app.metric[1].value, '10')
        self.assertEqual(app.metric[2].value, 'GBP 19.00')
        self.assertNotIn('2011-03', app.selectbox(key='start_month').options)
        app.selectbox(key='start_month').select('2011-02').run()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(app.metric[0].value, 'GBP 90.00')
        self.assertEqual(app.metric[2].value, 'GBP 10.00')

    def test_cohorts_and_concentration_render_with_explicit_scope(self):
        app = self.app()
        app.radio(key='view').set_value('Customer cohorts').run()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(len(app.selectbox), 0)
        self.assertTrue(any('unobserved' in text.value.lower() for text in app.caption))
        self.assertTrue(any(frame.value.isna().any().any() for frame in app.dataframe))
        app.radio(key='view').set_value('Customer concentration').run()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(app.metric[1].value, '75.0%')
        self.assertTrue(any('full observed' in text.value.lower() for text in app.caption))
        app.radio(key='view').set_value('Definitions & downloads').run()
        self.assertEqual(len(app.exception), 0)
        self.assertTrue(any('profit' in text.value.lower() for text in app.markdown))

    def test_missing_reports_shows_actionable_error_without_stack_trace(self):
        (self.directory / 'monthly_analysis.csv').unlink()
        app = self.app()
        self.assertEqual(len(app.exception), 0)
        self.assertIn('analysis.py', app.error[0].value)

    def test_undefined_matched_period_changes_render_without_crashing(self):
        summary = {'matched_year_comparison': {'earlier_year': '2010', 'later_year': '2011',
                   'value_change': None, 'order_change': None, 'aov_change': None}}
        (self.directory / 'analysis_summary.json').write_text(json.dumps(summary))
        app = self.app()
        self.assertEqual(len(app.exception), 0)
        self.assertTrue(any('Not defined' in text.value for text in app.markdown))

    def test_reversed_dates_and_no_complete_months_show_explanations(self):
        app = self.app()
        app.selectbox(key='start_month').select('2011-02').run()
        app.selectbox(key='end_month').select('2011-01').run()
        self.assertEqual(len(app.exception), 0)
        self.assertTrue(app.warning)
        data = months()
        data['is_complete_month'] = 0
        data.to_csv(self.directory / 'monthly_analysis.csv', index=False)
        app = self.app()
        self.assertEqual(len(app.exception), 0)
        self.assertTrue(app.info)

    def test_empty_cohort_and_customer_views_are_usable(self):
        for name in ['cohort_activity.csv', 'customer_concentration.csv']:
            df = pd.read_csv(self.directory / name)
            df.iloc[:0].to_csv(self.directory / name, index=False)
        app = self.app()
        for view in ['Customer cohorts', 'Customer concentration']:
            app.radio(key='view').set_value(view).run()
            self.assertEqual(len(app.exception), 0)
            self.assertTrue(app.info)

    def test_prediction_view_missing_and_completed_reports(self):
        app = self.app()
        app.radio(key='view').set_value('Purchase prediction').run()
        self.assertEqual(len(app.exception), 0)
        self.assertTrue(app.info)
        metric = {'average_precision': .71, 'roc_auc': .76, 'precision_at_top_decile': .88,
                  'prevalence': .40, 'brier_score': .19, 'lift_at_top_decile': 2.2,
                  'customers': 100, 'positives': 40, 'top_decile_customers': 10}
        report = {'selected_model': 'logistic_l2_10', 'cutoffs': {'train': '2010-07-01', 'validation': '2011-01-01', 'test': '2011-07-01'},
                  'features': ['recency_days'], 'validation': {'logistic_l2_10': metric},
                  'test': {'logistic_l2_10': metric}, 'implementation': 'NumPy logistic regression'}
        (self.directory / 'prediction_metrics.json').write_text(json.dumps(report))
        app = self.app()
        app.radio(key='view').set_value('Purchase prediction').run()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(app.metric[0].value, '0.710')
        self.assertEqual(app.metric[2].value, '88.0%')
        self.assertTrue(any('uplift' in text.value.lower() for text in app.caption))

    def test_supplemental_robustness_view_renders_window_and_probability_caveat(self):
        rows = [{'cutoff': '2011-09-01', 'name': 'additional_september', 'ece': .09,
                 'model_metrics': {'average_precision': .75, 'prevalence': .49, 'brier_score': .22},
                 'recency_metrics': {'average_precision': .55}}]
        (self.directory / 'release_evaluation.json').write_text(json.dumps({'windows': rows}))
        app = self.app()
        app.radio(key='view').set_value('Purchase prediction').run()
        self.assertEqual(len(app.exception), 0)
        self.assertTrue(any('2011-09-01' in frame.value.to_string() for frame in app.dataframe))
        self.assertTrue(any('probabilit' in text.value.lower() for text in app.caption))


if __name__ == '__main__':
    unittest.main()
