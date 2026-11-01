"""Hand-derived time boundaries and held-out evaluation contracts."""
import unittest

import pandas as pd

from prediction import FEATURES, build_snapshot, evaluate, fit_logistic, predict_probability, select_model, train_study


def orders():
    return pd.DataFrame([
        ['old', 'A', '2009-12-01', 5],
        ['start', 'A', '2010-01-02', 10],  # exactly 180 days before July 1
        ['last', 'A', '2010-06-30', 20],
        ['other', 'B', '2010-06-01', 30],
        ['cutoff', 'A', '2010-07-01', 40],
        ['label_end', 'B', '2010-08-30', 50],  # excluded upper endpoint
        ['future_only', 'C', '2010-07-03', 60],
        ['anonymous', None, '2010-06-29', 999],
    ], columns=['invoice_no', 'customer_id', 'order_date', 'order_value'])


class PredictionTests(unittest.TestCase):
    def test_snapshot_uses_half_open_windows_and_known_past_customers(self):
        snap = build_snapshot(orders(), '2010-07-01', '2009-12-01', '2011-01-01').set_index('customer_id')
        self.assertEqual(set(snap.index), {'A', 'B'})
        self.assertEqual(snap.loc['A', 'orders_180d'], 2)
        self.assertEqual(snap.loc['A', 'value_180d'], 30)
        self.assertEqual(snap.loc['A', 'aov_180d'], 15)
        self.assertEqual(snap.loc['A', 'recency_days'], 1)
        self.assertEqual(snap.loc['A', 'orders_30d'], 1)
        self.assertEqual(snap.loc['A', 'tenure_days'], 212)
        self.assertEqual(snap.loc['A', 'purchase_next_60d'], 1)
        self.assertEqual(snap.loc['B', 'purchase_next_60d'], 0)

    def test_future_changes_cannot_change_features_or_eligibility(self):
        original = orders()
        changed = original.copy()
        mask = changed.order_date.ge('2010-07-01')
        changed.loc[mask, 'order_value'] = 1000000
        changed.loc[mask, 'customer_id'] = 'Z'
        before = build_snapshot(original, '2010-07-01', '2009-12-01', '2011-01-01')
        after = build_snapshot(changed, '2010-07-01', '2009-12-01', '2011-01-01')
        pd.testing.assert_frame_equal(before[['customer_id'] + FEATURES], after[['customer_id'] + FEATURES])

    def test_incomplete_history_or_future_window_rejected(self):
        for start, end in [('2010-02-01', '2011-01-01'), ('2009-12-01', '2010-08-29')]:
            with self.assertRaisesRegex(ValueError, 'coverage'):
                build_snapshot(orders(), '2010-07-01', start, end)

    def test_metrics_use_ceil_top_decile_and_deterministic_id_ties(self):
        metrics = evaluate([1, 0, 0], [.5, .5, .2], ['B', 'A', 'C'])
        self.assertEqual(metrics['top_decile_customers'], 1)
        self.assertEqual(metrics['precision_at_top_decile'], 0)
        self.assertAlmostEqual(metrics['brier_score'], (.25 + .25 + .04) / 3)
        self.assertEqual(metrics['prevalence'], 1 / 3)
        self.assertIsNone(evaluate([0, 0], [.1, .2], ['A', 'B'])['roc_auc'])
        self.assertIsNone(evaluate([0, 0], [.1, .2], ['A', 'B'])['lift_at_top_decile'])

    def test_model_selection_ties_favor_logistic_and_only_uses_validation_ap(self):
        self.assertEqual(select_model({'logistic_l2_1': {'average_precision': .5},
                                       'logistic_l2_10': {'average_precision': .6}}), 'logistic_l2_10')
        self.assertEqual(select_model({'logistic_l2_10': {'average_precision': .6},
                                       'logistic_l2_1': {'average_precision': .6}}), 'logistic_l2_1')

    def test_tied_score_ap_and_auc_use_threshold_groups_and_average_ranks(self):
        metric = evaluate([1, 0, 1, 0], [.8, .8, .4, .1], ['A', 'B', 'C', 'D'])
        self.assertAlmostEqual(metric['average_precision'], .5 * .5 + .5 * (2 / 3))
        self.assertAlmostEqual(metric['roc_auc'], .625)

    def test_newton_solver_converges_and_uses_training_scaling(self):
        import numpy as np
        x = pd.DataFrame({'a': [0., 1., 2., 3., 4., 5.], 'constant': [1.] * 6})
        model = fit_logistic(x, [0, 0, 0, 1, 1, 1], penalty=1)
        score = predict_probability(model, x)
        self.assertTrue(np.all(np.diff(score) > 0))
        self.assertTrue(model['converged'])
        self.assertLess(model['gradient_max'], 1e-6)
        self.assertAlmostEqual(predict_probability(model, x.iloc[[0]])[0], score[0])

    def test_real_estimators_produce_bounded_probabilities_and_test_only_selected_model(self):
        snapshots = {}
        for number, name in enumerate(['train', 'validation', 'test']):
            records = []
            for i in range(40):
                row = {feature: float((i + offset + number) % 20 + 1) for offset, feature in enumerate(FEATURES)}
                row.update(customer_id=str(i), purchase_next_60d=i % 2)
                records.append(row)
            snapshots[name] = pd.DataFrame(records)
        result, model, probabilities = train_study(snapshots)
        self.assertEqual(set(result['test']), {'constant_prevalence', 'recency_baseline', result['selected_model']})
        self.assertEqual(len(probabilities), 40)
        self.assertTrue(all(0 <= p <= 1 for p in probabilities))
        self.assertEqual(len(model['mean']), len(FEATURES))


if __name__ == '__main__':
    unittest.main()
