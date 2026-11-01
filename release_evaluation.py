"""Frozen-model temporal robustness, probability reliability and value sensitivity."""
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3

import numpy as np
import pandas as pd

from audit import COLUMNS
from prediction import FEATURES, TARGET, build_snapshot, evaluate, predict_probability


ROOT = Path(__file__).resolve().parent
EXTRA_CUTOFFS = {'retrospective_april': '2011-04-01', 'additional_september': '2011-09-01'}


def load_frozen_model(report, path):
    if hashlib.sha256(Path(path).read_bytes()).hexdigest() != report.get('model_file_sha256'):
        raise ValueError('Model checksum differs from frozen prediction report')
    with np.load(path, allow_pickle=False) as arrays:
        model = dict(arrays)
    if model['features'].tolist() != report['features']:
        raise ValueError('Model feature order differs from frozen report')
    return model


def calibration_table(y, probability):
    y, probability = np.asarray(y, dtype=int), np.asarray(probability, dtype=float)
    if not len(y) or len(y) != len(probability) or not np.isfinite(probability).all() or not ((probability >= 0) & (probability <= 1)).all():
        raise ValueError('Reliability requires nonempty matching labels and finite probabilities in [0,1]')
    bins = np.minimum((probability * 10).astype(int), 9)
    return pd.DataFrame([{'bin': i, 'lower': i / 10, 'upper': (i + 1) / 10,
        'count': int((bins == i).sum()),
        'mean_probability': float(probability[bins == i].mean()) if (bins == i).any() else np.nan,
        'observed_rate': float(y[bins == i].mean()) if (bins == i).any() else np.nan}
        for i in range(10)])


def _ap(y, score):
    order = np.argsort(-score, kind='stable')
    labels, scores = y[order], score[order]
    ends = np.r_[np.flatnonzero(scores[1:] != scores[:-1]), len(scores) - 1]
    true_positive = np.cumsum(labels)[ends]
    recall_increments = np.diff(np.r_[0, true_positive])
    return float(np.sum(recall_increments * true_positive / (ends + 1)) / labels.sum()) if labels.sum() else 0.


def paired_ap_interval(y, probability, baseline, resamples=500, seed=20261031):
    y, probability, baseline = (np.asarray(values) for values in [y, probability, baseline])
    if not len(y) or len(y) != len(probability) or len(y) != len(baseline) or resamples < 1:
        raise ValueError('Paired bootstrap requires matching nonempty arrays and positive resamples')
    generator = np.random.default_rng(seed)
    differences = []
    for _ in range(resamples):
        index = generator.integers(0, len(y), len(y))
        differences.append(_ap(y[index], probability[index]) - _ap(y[index], baseline[index]))
    low, high = np.quantile(differences, [.025, .975])
    return {'difference': _ap(y, probability) - _ap(y, baseline), 'lower': float(low),
            'upper': float(high), 'resamples': resamples, 'seed': seed,
            'scope': 'Paired customer percentile bootstrap conditional on fitted model and this window; not across-season or training-set uncertainty'}


def sensitivity(transactions):
    purchases = transactions.loc[transactions.line_type.eq('purchase')]
    unique = purchases.drop_duplicates(['source_sheet'] + COLUMNS)
    current = float(purchases.line_value.sum())
    deduplicated = float(unique.line_value.sum())
    signed = float(transactions.loc[transactions.line_type.ne('invalid_core'), 'line_value'].sum())
    return {'current_positive_value': current,
            'within_sheet_deduplicated_positive_value': deduplicated,
            'removed_purchase_occurrences': len(purchases) - len(unique),
            'deduplicated_value_change': deduplicated / current - 1 if current else None,
            'signed_valid_value': signed, 'signed_value_change': signed / current - 1 if current else None}


def render_report(report):
    lines = ['# Release 1.0 robustness and sensitivity', '',
        '## Frozen evaluation protocol', '',
        'The original July test was already observed before this finalization. Model settings, features, preprocessing, baselines and eligibility are unchanged. April and September windows were fixed in the finalization plan before calculating their results. April is retrospective robustness; September is additional later evidence, not a replacement for the original test. No result here was used to tune or select a model.', '',
        '| Window cutoff | Eligible customers | Purchase rate | Model AP | Recency AP | Model AUC | Brier | ECE (10 bins) |',
        '|---|---:|---:|---:|---:|---:|---:|---:|']
    for row in report['windows']:
        m, b = row['model_metrics'], row['recency_metrics']
        lines.append(f"| {row['cutoff']} | {m['customers']:,} | {m['prevalence']:.1%} | {m['average_precision']:.3f} | {b['average_precision']:.3f} | {m['roc_auc']:.3f} | {m['brier_score']:.3f} | {row['ece']:.3f} |")
    lines += ['', '## Conditional uncertainty and reliability', '',
        'Fixed 500-resample paired customer bootstraps compare AP with the recency baseline separately in each window. Customers recur across windows; do not pool snapshots as independent observations. These percentile intervals condition on the fitted model and do not measure seasonal or training-set uncertainty.', '']
    for row in report['windows']:
        interval = row['paired_ap_difference']
        lines.append(f"- {row['cutoff']}: AP difference {interval['difference']:+.3f}; conditional 95% percentile interval [{interval['lower']:+.3f}, {interval['upper']:+.3f}].")
    lines += ['', 'Reliability uses ten fixed equal-width bins. Compare mean probability with observed rate and inspect counts; empty bins stay empty. ECE is sample/bin dependent, not proof that probabilities are calibrated. No calibration correction was fitted or selected from these outcomes.', '',
        '![Reliability by evaluation window](figures/reliability.png)', '', '## Cleaning sensitivity', '']
    s = report['value_sensitivity']
    lines += [f"- Current positive recorded value: GBP {s['current_positive_value']:,.2f}.",
        f"- Removing retained copies with identical normalized source fields within each sheet: GBP {s['within_sheet_deduplicated_positive_value']:,.2f} ({s['deduplicated_value_change']:+.2%}); removes {s['removed_purchase_occurrences']:,} purchase occurrences.",
        f"- Summing signed valid charges/credits as a bookkeeping scenario: GBP {s['signed_valid_value']:,.2f} ({s['signed_value_change']:+.2%} versus the positive-only metric).", '',
        'Neither scenario is a corrected ground truth. Repeated invoice lines may be legitimate; normalized-field identity can collapse text formatting differences. Signed entries are not matched refunds, merchandise-only revenue or profit. The original cleaning policy and primary model target remain unchanged; this checks aggregate value sensitivity, not a refitted model under alternative cleaning.', '',
        '## Decision', '',
        'Use the project as reproducible historical analytics and a purchase-ranking study. Inspect reliability before treating scores as purchase probabilities; conduct a randomized outreach experiment before claiming incremental value. More retailers, time periods and operational validation are needed for production use.', '',
        'Reproduce with `python release_evaluation.py` after `prediction.py`. Inputs are checksum-checked against the frozen model reports. No model training occurs in this step.', '']
    return '\n'.join(lines)


def main():
    original = json.loads((ROOT / 'reports/prediction_metrics.json').read_text())
    database = ROOT / 'data/processed/retail.sqlite'
    checksum = hashlib.sha256(database.read_bytes()).hexdigest()
    if checksum != original['database_sha256']:
        raise ValueError('Database differs from frozen prediction report; reproduce the pipeline before finalization')
    with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)) as db:
        orders = pd.read_sql_query('SELECT invoice_no, customer_id, order_date, order_value FROM customer_orders', db)
        metadata = {key: json.loads(value) for key, value in db.execute('SELECT key, value FROM pipeline_metadata')}
        columns = ','.join(['source_sheet'] + COLUMNS + ['line_type', 'line_value'])
        transactions = pd.read_sql_query(f'SELECT {columns} FROM transactions', db)
    model = load_frozen_model(original, ROOT / 'data/model/repeat_purchase_model.npz')
    windows, bins = [], []
    cutoffs = {'original_july': original['cutoffs']['test'], **EXTRA_CUTOFFS}
    for name, cutoff in cutoffs.items():
        span = metadata['source_date_range']
        snapshot = build_snapshot(orders, cutoff, span['start'], span['end'])
        probability = predict_probability(model, snapshot[FEATURES])
        rates = original['recency_baseline_training_rates']
        baseline = np.where(snapshot.recency_days.le(30), rates['recent_30d'], rates['older'])
        table = calibration_table(snapshot[TARGET], probability)
        table['window'] = name
        bins.append(table)
        ece = float((table['count'] * (table.mean_probability - table.observed_rate).abs()).sum() / len(snapshot))
        windows.append({'name': name, 'cutoff': cutoff,
            'model_metrics': evaluate(snapshot[TARGET], probability, snapshot.customer_id),
            'recency_metrics': evaluate(snapshot[TARGET], baseline, snapshot.customer_id),
            'ece': ece, 'mean_predicted_probability': float(probability.mean()),
            'paired_ap_difference': paired_ap_interval(snapshot[TARGET], probability, baseline)})
        if name == 'original_july':
            expected = original['test'][original['selected_model']]
            for key in ['average_precision', 'roc_auc', 'brier_score', 'precision_at_top_decile']:
                if not np.isclose(windows[-1]['model_metrics'][key], expected[key], rtol=0, atol=1e-12):
                    raise ValueError('Frozen model does not reproduce original July metrics')
    report = {'protocol_version': 1, 'windows': windows, 'value_sensitivity': sensitivity(transactions),
              'model_file_sha256': hashlib.sha256((ROOT / 'data/model/repeat_purchase_model.npz').read_bytes()).hexdigest(),
              'database_sha256': checksum, 'source_sha256': original['source_sha256'],
              'generated_at_utc': datetime.now(timezone.utc).isoformat()}
    reliability = pd.concat(bins, ignore_index=True)
    reliability.to_csv(ROOT / 'reports/reliability_bins.csv', index=False)
    # Import project chart module first to configure a local Matplotlib cache.
    import charts
    import matplotlib.pyplot as plt
    fig, axis = plt.subplots(figsize=(8, 5))
    axis.plot([0, 1], [0, 1], '--', color='gray', label='Perfect reliability reference')
    for name, table in reliability.groupby('window', sort=False):
        observed = table.loc[table['count'].gt(0)]
        axis.plot(observed.mean_probability, observed.observed_rate, marker='o', label=name)
    axis.set(xlim=(0, 1), ylim=(0, 1), xlabel='Mean predicted probability in bin',
             ylabel='Observed purchase fraction', title='Frozen-model reliability across time')
    axis.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(ROOT / 'reports/figures/reliability.png', dpi=160)
    plt.close(fig)
    if hashlib.sha256(database.read_bytes()).hexdigest() != checksum:
        raise AssertionError('Database changed during finalization evaluation')
    (ROOT / 'reports/release_evaluation.json').write_text(json.dumps(report, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    (ROOT / 'reports/release_evaluation.md').write_text(render_report(report), encoding='utf-8')
    print('Frozen model evaluated on three windows; database unchanged.')
    for window in windows:
        print(window['cutoff'], 'AP', round(window['model_metrics']['average_precision'], 4), 'ECE', round(window['ece'], 4))


if __name__ == '__main__':
    main()
