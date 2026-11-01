# Customer Retention & Sales Analytics

**Portfolio release 1.0.0** · Python 3.12 · pandas · SQL/SQLite · NumPy · Streamlit

A reproducible study of retail sales, repeat purchasing and next-60-day purchase propensity. It combines a source audit, documented cleaning, SQL analysis, an interactive dashboard and temporal model evaluation. Developed with AI coding assistance; results and limitations are documented below.

![Dashboard preview](reports/figures/dashboard_preview.png)

## Business questions and findings

- **Sales composition:** January-November 2011 positive recorded value rose **1.8%** versus the same months in 2010, despite **4.6% fewer orders**; average order value rose **6.7%**. This decomposes the change but does not identify its cause.
- **Customer dependence:** the top 588 of 5,878 identified customers supply **63.8%** of identified positive value. Anonymous sales are outside that denominator.
- **Purchase ranking:** the original July temporal test has **2,724 eligible customers**, model AP **0.710**, ROC AUC **0.758**, and a **87.9%** top-decile purchase rate versus **39.7%** population prevalence. Recency-baseline AP is **0.464**.
- **Robustness:** frozen-model AP is **0.673** in April and **0.748** in September, each above its recency baseline. Reliability varies: September's ten-bin ECE is **0.090**, so ranking quality does not guarantee stable probabilities.
- **Cleaning sensitivity:** removing retained within-sheet normalized copies changes aggregate positive value by **-0.28%**. A signed-charge bookkeeping scenario is **7.91% lower** than positive value; it is not established refund-net revenue.

Read the [business memo](reports/business_memo.md), [model assessment](reports/prediction_assessment.md), and [robustness/sensitivity report](reports/release_evaluation.md). Proposed customer outreach requires a randomized experiment before claiming incremental impact.

## Quick start

Use Python **3.12**. No API key or paid service is required. Saved report files let the dashboard run before downloading raw data.

Windows PowerShell, from this repository's root:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m streamlit run streamlit_app.py --server.address 127.0.0.1
```

Open http://127.0.0.1:8501. Keep the terminal running; stop with Ctrl+C. Alternatively use `./launch_dashboard.ps1` after creating the environment.

macOS/Linux:

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements-lock.txt
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m streamlit run streamlit_app.py --server.address 127.0.0.1
```

To reproduce all source-derived artifacts (downloads the public workbook on first run):

```powershell
.\.venv\Scripts\python.exe run_pipeline.py
```

Use `.venv/bin/python run_pipeline.py` on macOS/Linux. Workbook audit and cleaning can take several minutes. Generated data/model artifacts remain ignored under `data/`; the original cached source is checksum-verified and preserved. Rebuilding reports after source/policy changes creates a new evaluation; do not silently treat changed settings as an untouched test.

## Dashboard

Five views cover sales, customer cohorts, concentration, purchase prediction, and definitions/downloads. Sales filters admit complete months only. Cohort and concentration views keep full-history scopes; model results keep fixed evaluation windows. Hover charts for values and download supporting tables.

## Method and safeguards

- Original source: 1,067,371 invoice lines in two sheets. Reconcile 22,523 cross-export occurrences while preserving maximum per-sheet multiplicity; retain the adjustment and excluded-copy evidence.
- Final purchase dataset: 40,077 qualifying orders; identified orders cover 84.89% of positive recorded value. Invoice lines and orders are separate units.
- Customers active in the prior 180 days are eligible; target is any qualifying purchase in the next 60 days. Features stop strictly before cutoff. Train 2010-07-01, validate 2011-01-01, original test 2011-07-01. Customers recur across periods; this addresses existing-customer forecasting.
- Training-only log1p transforms/standardization and logistic fitting. Fixed L2 penalties 1 and 10 selected on validation AP only, with constant-prevalence and recency baselines. Additional April/September evaluations never change model selection.
- Logistic regression uses a tested NumPy damped-Newton optimizer with an unpenalized intercept and explicit gradient convergence checks. NumPy was used after SciPy's compiled dependency was blocked in the development environment; no scikit-learn result is claimed.
- Reliability uses ten fixed probability bins. Paired 500-resample customer bootstrap intervals are conditional on the fitted model/window and are not uncertainty across training sets or seasons. No test-set recalibration or intervention-effect estimate is claimed.

## Scope and limitations

Positive recorded value excludes adjustments and does **not** equal profit or established refund-net revenue. First observed purchase does not prove acquisition; a month without purchases does not prove permanent churn. December 2011 is partial. Historical UK gift retail includes wholesalers. Anonymous/long-inactive customers are outside model eligibility; recurring customers mean time windows are not independent samples of new people. This is a portfolio study, not a production targeting system.

## Repository map

| Files | Purpose |
|---|---|
| `download_data.py`, `audit.py`, `clean.py` | Public source, provenance, classification and analytical SQLite dataset |
| `sql/`, `analysis.py`, `charts.py` | Reproducible business metrics, cohorts, concentration and static charts |
| `prediction.py`, `release_evaluation.py` | Past-only features, fixed model study, reliability and sensitivity |
| `streamlit_app.py`, `dashboard_data.py` | Five-view read-only report dashboard |
| `tests/` | Hand-derived data, leakage, numerical and app-interaction tests |
| `reports/` | Saved CSV/JSON evidence and readable assessments |
| `docs/cleaning_rules.md`, `docs/data_dictionary.md` | Definitions and coverage contracts |
| `run_pipeline.py`, `package_release.py` | Full reproduction and explicitly allowlisted release archive |
| `.github/workflows/ci.yml` | Fresh Python installation and unit/app checks on pushes/PRs |

## Attribution

Chen, D. (2012). **Online Retail II**. UCI Machine Learning Repository. [DOI: 10.24432/C5CG6D](https://doi.org/10.24432/C5CG6D). Dataset and derived reports: CC BY 4.0; project code: MIT. See [NOTICE](NOTICE) and [LICENSE](LICENSE).
