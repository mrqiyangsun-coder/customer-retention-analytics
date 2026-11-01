import unittest
from pathlib import Path
import hashlib
import shutil
import uuid
import numpy as np
import pandas as pd

from release_evaluation import calibration_table, load_frozen_model, paired_ap_interval, sensitivity


class ReleaseEvaluationTests(unittest.TestCase):
    def test_frozen_artifact_checks_checksum_and_feature_order(self):
        root = Path(__file__).resolve().parents[1] / 'data/test_artifacts' / uuid.uuid4().hex
        root.mkdir(parents=True)
        self.addCleanup(shutil.rmtree, root)
        path = root / 'model.npz'
        np.savez(path, features=np.asarray(['a', 'b']), coefficient=np.asarray([1., 2.]))
        report = {'model_file_sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'features': ['a', 'b']}
        self.assertEqual(load_frozen_model(report, path)['coefficient'].tolist(), [1., 2.])
        with self.assertRaisesRegex(ValueError, 'feature'):
            load_frozen_model({**report, 'features': ['b', 'a']}, path)
        path.write_bytes(path.read_bytes() + b'changed')
        with self.assertRaisesRegex(ValueError, 'checksum'):
            load_frozen_model(report, path)

    def test_reliability_bins_include_both_endpoints_and_preserve_empty_bins(self):
        table = calibration_table([0, 1, 0, 1], [0., .1, .99, 1.])
        self.assertEqual(len(table), 10)
        self.assertEqual(table['count'].sum(), 4)
        self.assertEqual(table.iloc[0]['count'], 1)
        self.assertEqual(table.iloc[1]['count'], 1)
        self.assertEqual(table.iloc[-1]['count'], 2)
        self.assertAlmostEqual(table.iloc[-1]['mean_probability'], .995)
        self.assertEqual(table.iloc[-1]['observed_rate'], .5)
        self.assertTrue(np.isnan(table.iloc[2]['observed_rate']))

    def test_identical_scores_have_zero_paired_ap_difference(self):
        result = paired_ap_interval([0, 1, 0, 1], [.1, .8, .2, .7], [.1, .8, .2, .7], resamples=30)
        self.assertEqual(result['difference'], 0)
        self.assertEqual(result['lower'], 0)
        self.assertEqual(result['upper'], 0)
        self.assertEqual(result, paired_ap_interval([0, 1, 0, 1], [.1, .8, .2, .7], [.1, .8, .2, .7], resamples=30))

    def test_sensitivity_does_not_deduplicate_across_distinct_source_sheets(self):
        row = dict(invoice_no='A', stock_code='X', description='item', quantity=1,
                   invoice_date='2011-01-01', unit_price=10, customer_id='1', country='UK',
                   line_type='purchase', line_value=10)
        data = pd.DataFrame([{**row, 'source_sheet': 'first'}, {**row, 'source_sheet': 'first'},
                             {**row, 'source_sheet': 'second'},
                             {**row, 'source_sheet': 'first', 'invoice_no': 'C', 'quantity': -1,
                              'line_type': 'adjustment', 'line_value': -10}])
        result = sensitivity(data)
        self.assertEqual(result['current_positive_value'], 30)
        self.assertEqual(result['within_sheet_deduplicated_positive_value'], 20)
        self.assertEqual(result['signed_valid_value'], 20)
        self.assertEqual(result['removed_purchase_occurrences'], 1)

    def test_sensitivity_excludes_invalid_lines_from_signed_scenario(self):
        data = pd.DataFrame([dict(source_sheet='first', invoice_no='X', stock_code='S', description='x',
            quantity=1, invoice_date='2011-01-01', unit_price=10, customer_id='1', country='UK',
            line_type='invalid_core', line_value=100)])
        self.assertEqual(sensitivity(data)['signed_valid_value'], 0)


if __name__ == '__main__':
    unittest.main()
