"""Fixed-cutoff, past-only repeat-purchase study; no paid APIs."""
import argparse
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import sqlite3

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parent
FEATURES = ['recency_days', 'orders_180d', 'value_180d', 'aov_180d',
            'orders_30d', 'orders_60d', 'tenure_days']
CUTOFFS = {'train': '2010-07-01', 'validation': '2011-01-01', 'test': '2011-07-01'}
TARGET = 'purchase_next_60d'


def build_snapshot(orders, cutoff, source_start, source_end):
    cutoff = pd.Timestamp(cutoff)
    history_start, label_end = cutoff - pd.Timedelta(days=180), cutoff + pd.Timedelta(days=60)
    if history_start < pd.Timestamp(source_start) or label_end > pd.Timestamp(source_end):
        raise ValueError('Snapshot lookback and future label windows require complete source coverage')
    data = orders.loc[orders.customer_id.notna()].copy()
    data['order_date'] = pd.to_datetime(data.order_date)
    prior = data.loc[data.order_date.lt(cutoff)]
    window = prior.loc[prior.order_date.ge(history_start)]
    snapshot = window.groupby('customer_id').agg(
        last_order=('order_date', 'max'), orders_180d=('invoice_no', 'nunique'),
        value_180d=('order_value', 'sum')).reset_index()
    snapshot['recency_days'] = (cutoff - snapshot.last_order).dt.total_seconds() / 86400
    snapshot['aov_180d'] = snapshot.value_180d / snapshot.orders_180d
    first = prior.groupby('customer_id').order_date.min()
    snapshot['tenure_days'] = (cutoff - snapshot.customer_id.map(first)).dt.total_seconds() / 86400
    for days in [30, 60]:
        counts = window.loc[window.order_date.ge(cutoff - pd.Timedelta(days=days))].groupby('customer_id').invoice_no.nunique()
        snapshot[f'orders_{days}d'] = snapshot.customer_id.map(counts).fillna(0).astype(int)
    buyers = set(data.loc[data.order_date.ge(cutoff) & data.order_date.lt(label_end), 'customer_id'])
    snapshot[TARGET] = snapshot.customer_id.isin(buyers).astype(int)
    snapshot['cutoff'] = cutoff.isoformat()
    return snapshot[['customer_id', 'cutoff'] + FEATURES + [TARGET]].sort_values('customer_id').reset_index(drop=True)


def evaluate(y, probability, customer_ids):
    y, probability = np.asarray(y, dtype=int), np.asarray(probability, dtype=float)
    if not len(y) or len(y) != len(probability) or len(y) != len(customer_ids):
        raise ValueError('Evaluation requires matching nonempty labels, scores and customer IDs')
    if not np.isfinite(probability).all() or not ((probability >= 0) & (probability <= 1)).all():
        raise ValueError('Probabilities must be finite and within [0, 1]')
    prevalence = float(y.mean())
    ranking = pd.DataFrame({'probability': probability, 'id': [str(x) for x in customer_ids], 'y': y}).sort_values(
        ['probability', 'id'], ascending=[False, True], kind='stable')
    count = math.ceil(len(y) * .1)
    precision = float(ranking.head(count).y.mean())
    grouped = ranking.groupby('probability', sort=False).y.agg(['sum', 'count'])
    ap = float(((grouped['sum'].cumsum() / grouped['count'].cumsum()) * grouped['sum']).sum() / y.sum()) if y.sum() else 0.
    positives, negatives = int(y.sum()), int(len(y) - y.sum())
    ranks = pd.Series(probability).rank(method='average').to_numpy()
    auc = float((ranks[y == 1].sum() - positives * (positives + 1) / 2) / (positives * negatives)) if positives and negatives else None
    return {'customers': len(y), 'positives': positives, 'prevalence': prevalence,
            'average_precision': ap, 'roc_auc': auc,
            'brier_score': float(np.mean((y - probability) ** 2)),
            'top_decile_customers': count, 'precision_at_top_decile': precision,
            'lift_at_top_decile': precision / prevalence if prevalence else None}


def select_model(validation):
    return max(['logistic_l2_1', 'logistic_l2_10'],
               key=lambda name: validation[name]['average_precision'])


def predict_probability(model, x):
    z = (np.log1p(np.asarray(x, dtype=float)) - model['mean']) / model['scale']
    logits = z @ model['coefficient'] + model['intercept']
    return np.exp(-np.logaddexp(0., -logits))


def fit_logistic(x, y, penalty):
    """Minimize summed logistic loss + penalty/2 * squared non-intercept weights."""
    transformed = np.log1p(np.asarray(x, dtype=float))
    mean, scale = transformed.mean(axis=0), transformed.std(axis=0)
    scale = np.where(scale == 0, 1., scale)
    design = np.column_stack([np.ones(len(x)), (transformed - mean) / scale])
    y = np.asarray(y, dtype=float)
    if len(np.unique(y)) != 2:
        raise ValueError('Logistic fitting requires both target classes')
    regularization = np.diag([0.] + [float(penalty)] * (design.shape[1] - 1))
    weights = np.zeros(design.shape[1])

    def objective(w):
        logits = design @ w
        return float(np.sum(np.logaddexp(0., logits) - y * logits) + .5 * w @ regularization @ w)

    converged = False
    for iteration in range(100):
        logits = design @ weights
        probability = np.exp(-np.logaddexp(0., -logits))
        gradient = design.T @ (probability - y) + regularization @ weights
        if np.max(np.abs(gradient)) < 1e-7:
            converged = True
            break
        curvature = probability * (1 - probability)
        hessian = design.T @ (design * curvature[:, None]) + regularization
        direction = np.linalg.solve(hessian, gradient)
        current, step = objective(weights), 1.
        for _ in range(40):
            if objective(weights - step * direction) <= current - 1e-4 * step * (gradient @ direction):
                break
            step *= .5
        else:
            raise RuntimeError('Logistic line search did not converge')
        weights -= step * direction
    if not converged:
        raise RuntimeError('Logistic optimization did not meet the gradient tolerance')
    return {'mean': mean, 'scale': scale, 'intercept': weights[0], 'coefficient': weights[1:],
            'penalty': float(penalty), 'converged': converged, 'iterations': iteration,
            'gradient_max': float(np.max(np.abs(gradient)))}


def train_study(snapshots):
    train, validation, test = [snapshots[name] for name in ['train', 'validation', 'test']]
    if train[TARGET].nunique() != 2 or any(frame.empty for frame in snapshots.values()):
        raise ValueError('Training requires both classes, and every split must contain customers')
    penalties = {'logistic_l2_1': 1., 'logistic_l2_10': 10.}
    candidates = {}
    prevalence = float(train[TARGET].mean())
    recency_rates = {}
    for recent in [False, True]:
        group = train.loc[train.recency_days.le(30).eq(recent), TARGET]
        recency_rates[recent] = (float(group.sum()) + 1) / (len(group) + 2)

    def baseline_scores(frame):
        return {'constant_prevalence': np.full(len(frame), prevalence),
                'recency_baseline': frame.recency_days.le(30).map(recency_rates).to_numpy()}

    validation_metrics = {}
    for name, penalty in penalties.items():
        candidates[name] = fit_logistic(train[FEATURES], train[TARGET], penalty)
        probabilities = predict_probability(candidates[name], validation[FEATURES])
        validation_metrics[name] = evaluate(validation[TARGET], probabilities, validation.customer_id)
    for name, scores in baseline_scores(validation).items():
        validation_metrics[name] = evaluate(validation[TARGET], scores, validation.customer_id)
    selected = select_model(validation_metrics)
    test_probabilities = predict_probability(candidates[selected], test[FEATURES])
    test_scores = {**baseline_scores(test), selected: test_probabilities}
    test_metrics = {name: evaluate(test[TARGET], scores, test.customer_id) for name, scores in test_scores.items()}
    result = {'selected_model': selected, 'selection_rule': 'Highest validation average precision; ties favor L2 penalty 1',
              'validation': validation_metrics, 'test': test_metrics,
              'solver_diagnostics': {name: {key: model[key] for key in ['penalty', 'converged', 'iterations', 'gradient_max']} for name, model in candidates.items()},
              'baseline_training_prevalence': prevalence,
              'recency_baseline_training_rates': {'recent_30d': recency_rates[True], 'older': recency_rates[False]},
              'split_populations': {name: {'customers': len(frame), 'positives': int(frame[TARGET].sum()),
                  'prevalence': float(frame[TARGET].mean())} for name, frame in snapshots.items()}}
    return result, candidates[selected], test_probabilities


def render_assessment(result):
    selected = result['selected_model']
    metric = result['test'][selected]
    baseline = result['test']['recency_baseline']
    lines = ['# Repeat-purchase prediction assessment', '',
        '## Question and population', '',
        'Among identified customers purchasing in the prior 180 days, predict at least one qualifying order in the next 60 days. This is a retrospective purchase-propensity study, not permanent churn or the causal effect of contacting a customer.', '',
        '## Evaluation design', '',
        '- Training cutoff: 2010-07-01; validation: 2011-01-01; reserved test: 2011-07-01.',
        '- Features use only orders strictly before each cutoff; labels use [cutoff, cutoff + 60 days). All lookback and label windows fit source coverage.',
        '- Fit NumPy logistic regressions with fixed L2 penalties 1 and 10 on training only. Select using validation average precision. Training-standardized log1p features, unpenalized intercept, damped Newton optimization with gradient tolerance 1e-7. Do not refit on validation or change settings after inspecting the reserved test.',
        '- Customers can recur across snapshots. Customer ID is excluded from features. The study addresses future purchasing by existing customers, not unseen-customer generalization.', '',
        '## Results', '', f'Selected model: **{selected}**.', '',
        '| Split | Customers | Purchased within 60 days | Positive rate |', '|---|---:|---:|---:|']
    for name, split in result['split_populations'].items():
        lines.append(f"| {name} | {split['customers']:,} | {split['positives']:,} | {split['prevalence']:.1%} |")
    lines += ['', '| Test estimator | Average precision | ROC AUC | Brier (lower is better) | Top 10% precision | Lift over test prevalence |',
              '|---|---:|---:|---:|---:|---:|']
    for name, scores in result['test'].items():
        auc = 'undefined' if scores['roc_auc'] is None else f"{scores['roc_auc']:.3f}"
        lift = 'undefined' if scores['lift_at_top_decile'] is None else f"{scores['lift_at_top_decile']:.2f}x"
        lines.append(f"| {name} | {scores['average_precision']:.3f} | {auc} | {scores['brier_score']:.3f} | {scores['precision_at_top_decile']:.1%} | {lift} |")
    lines += ['', f"Selected-model test AP minus recency-baseline test AP: {metric['average_precision'] - baseline['average_precision']:+.3f}. This is a descriptive difference on one temporal test snapshot, not an established statistically significant improvement.",
        '', 'AP summarizes precision across recall thresholds; ROC AUC measures ranking across classes; Brier measures probability error. No operating classification threshold is tuned. Top-decile metrics rank ceil(10% of eligible customers), breaking equal scores by customer ID. A constant baseline’s top-decile result can therefore reflect arbitrary tie order, not useful ranking.', '',
        '## Interpretation and business use', '',
        '- Purchase propensity can support a hypothesis about which customers are likely to buy, but likely buyers are not necessarily the customers most affected by an offer.',
        '- A randomized outreach experiment is needed before claiming incremental purchases, revenue, ROI or treatment uplift. This project contains no such treatment data.',
        '- Probability error is reported, but detailed calibration validation and operational thresholds remain future work. Avoid treating the score as a production guarantee.', '',
        '## Limits', '',
        '- Only one training, validation and test cutoff. Seasonality, prior-history length and customer mix change across dates. No repeated-window robustness or confidence interval is claimed.',
        '- Customers recur across periods; observations are not independent unseen people. No customer-level random split is used.',
        '- Anonymous orders are excluded. Eligibility excludes customers with no prior-180-day purchase, so performance does not cover all historical customers.',
        '- First observed dates are left-truncated by dataset start. Source cleaning retains within-sheet multiplicity and excludes adjustments/nonpositive records from purchase targets.',
        '- Historical gift retail includes wholesalers. Dataset results do not establish modern-market behavior or production readiness.', '',
        '## Reproduce', '', 'Run `.\\.venv\\Scripts\\python.exe prediction.py` from the project directory. Snapshot cutoffs, features, settings, versions and dataset checksums are recorded in `prediction_metrics.json`. Generated snapshots, predictions and numeric NPZ model are local ignored artifacts under `data/model/`. SciPy application-control restrictions led to the NumPy implementation; no scikit-learn benchmark result is claimed.', '']
    return '\n'.join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, default=ROOT / 'data/processed/retail.sqlite')
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'reports')
    args = parser.parse_args(argv)
    database = args.database.resolve()
    if not database.is_file():
        parser.error('Database missing; run clean.py first')
    checksum = hashlib.sha256(database.read_bytes()).hexdigest()
    with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)) as db:
        metadata = {key: json.loads(value) for key, value in db.execute('SELECT key, value FROM pipeline_metadata')}
        orders = pd.read_sql_query('SELECT invoice_no, customer_id, order_date, order_value FROM customer_orders', db)
    span = metadata['source_date_range']
    snapshots = {name: build_snapshot(orders, cutoff, span['start'], span['end']) for name, cutoff in CUTOFFS.items()}
    result, model, probabilities = train_study(snapshots)
    result.update({'cutoffs': CUTOFFS, 'features': FEATURES, 'lookback_days': 180, 'target_days': 60,
        'source_sha256': metadata['source_sha256'], 'database_sha256': checksum,
        'rules_version': metadata['rules_version'], 'implementation': 'NumPy damped-Newton logistic regression',
        'pandas_version': pd.__version__, 'numpy_version': np.__version__,
        'model_parameters': {'penalty': model['penalty'], 'max_iterations': 100, 'gradient_tolerance': 1e-7,
                             'standardization': 'training mean/std of log1p features', 'intercept_penalized': False},
        'generated_at_utc': datetime.now(timezone.utc).isoformat()})
    artifact_dir = ROOT / 'data/model'
    artifact_dir.mkdir(parents=True, exist_ok=True)
    for name, frame in snapshots.items():
        frame.to_csv(artifact_dir / f'{name}_snapshot.csv', index=False)
    snapshots['test'][['customer_id', TARGET]].assign(probability=probabilities).to_csv(artifact_dir / 'test_predictions.csv', index=False)
    np.savez(artifact_dir / 'repeat_purchase_model.npz', **model, features=np.asarray(FEATURES))
    result['model_file_sha256'] = hashlib.sha256((artifact_dir / 'repeat_purchase_model.npz').read_bytes()).hexdigest()
    if hashlib.sha256(database.read_bytes()).hexdigest() != checksum:
        raise AssertionError('Source database changed during prediction study')
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / 'prediction_metrics.json').write_text(json.dumps(result, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    (args.output_dir / 'prediction_assessment.md').write_text(render_assessment(result), encoding='utf-8')
    print('Selected:', result['selected_model'])
    print('Reserved-test metrics:', json.dumps(result['test'][result['selected_model']]))
    print('Database unchanged. Assessment:', args.output_dir / 'prediction_assessment.md')


if __name__ == '__main__':
    main()
