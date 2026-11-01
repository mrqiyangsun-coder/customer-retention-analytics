# Repeat-purchase prediction assessment

## Question and population

Among identified customers purchasing in the prior 180 days, predict at least one qualifying order in the next 60 days. This is a retrospective purchase-propensity study, not permanent churn or the causal effect of contacting a customer.

## Evaluation design

- Training cutoff: 2010-07-01; validation: 2011-01-01; reserved test: 2011-07-01.
- Features use only orders strictly before each cutoff; labels use [cutoff, cutoff + 60 days). All lookback and label windows fit source coverage.
- Fit NumPy logistic regressions with fixed L2 penalties 1 and 10 on training only. Select using validation average precision. Training-standardized log1p features, unpenalized intercept, damped Newton optimization with gradient tolerance 1e-7. Do not refit on validation or change settings after inspecting the reserved test.
- Customers can recur across snapshots. Customer ID is excluded from features. The study addresses future purchasing by existing customers, not unseen-customer generalization.

## Results

Selected model: **logistic_l2_10**.

| Split | Customers | Purchased within 60 days | Positive rate |
|---|---:|---:|---:|
| train | 2,757 | 1,092 | 39.6% |
| validation | 3,415 | 990 | 29.0% |
| test | 2,724 | 1,081 | 39.7% |

| Test estimator | Average precision | ROC AUC | Brier (lower is better) | Top 10% precision | Lift over test prevalence |
|---|---:|---:|---:|---:|---:|
| constant_prevalence | 0.397 | 0.500 | 0.239 | 38.8% | 0.98x |
| recency_baseline | 0.464 | 0.605 | 0.229 | 52.4% | 1.32x |
| logistic_l2_10 | 0.710 | 0.758 | 0.188 | 87.9% | 2.22x |

Selected-model test AP minus recency-baseline test AP: +0.245. This is a descriptive difference on one temporal test snapshot, not an established statistically significant improvement.

AP summarizes precision across recall thresholds; ROC AUC measures ranking across classes; Brier measures probability error. No operating classification threshold is tuned. Top-decile metrics rank ceil(10% of eligible customers), breaking equal scores by customer ID. A constant baseline’s top-decile result can therefore reflect arbitrary tie order, not useful ranking.

## Interpretation and business use

- Purchase propensity can support a hypothesis about which customers are likely to buy, but likely buyers are not necessarily the customers most affected by an offer.
- A randomized outreach experiment is needed before claiming incremental purchases, revenue, ROI or treatment uplift. This project contains no such treatment data.
- Probability error is reported, but detailed calibration validation and operational thresholds remain future work. Avoid treating the score as a production guarantee.

## Limits

- Only one training, validation and test cutoff. Seasonality, prior-history length and customer mix change across dates. No repeated-window robustness or confidence interval is claimed.
- Customers recur across periods; observations are not independent unseen people. No customer-level random split is used.
- Anonymous orders are excluded. Eligibility excludes customers with no prior-180-day purchase, so performance does not cover all historical customers.
- First observed dates are left-truncated by dataset start. Source cleaning retains within-sheet multiplicity and excludes adjustments/nonpositive records from purchase targets.
- Historical gift retail includes wholesalers. Dataset results do not establish modern-market behavior or production readiness.

## Reproduce

Run `.\.venv\Scripts\python.exe prediction.py` from the project directory. Snapshot cutoffs, features, settings, versions and dataset checksums are recorded in `prediction_metrics.json`. Generated snapshots, predictions and numeric NPZ model are local ignored artifacts under `data/model/`. SciPy application-control restrictions led to the NumPy implementation; no scikit-learn benchmark result is claimed.
