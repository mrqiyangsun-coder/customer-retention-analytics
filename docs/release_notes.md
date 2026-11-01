# v1.0.0 — Customer Retention & Purchase Prediction

Retail customer analytics connecting transaction data, business insights and 60-day purchase predictions.

## Start here

- Explore the [project overview](https://github.com/mrqiyangsun-coder/customer-retention-analytics#readme) for the findings and dashboard preview.
- Read the [business brief](https://github.com/mrqiyangsun-coder/customer-retention-analytics/blob/main/reports/business_memo.md) or the [model evaluation](https://github.com/mrqiyangsun-coder/customer-retention-analytics/blob/main/reports/prediction_assessment.md).
- Download the attached archive to run the dashboard locally. Saved reports are included; no API key is needed.

## Included in this release

- A reproducible pipeline covering 1.07M invoice lines and 40,077 qualifying orders.
- SQL analysis of sales trends, customer cohorts and customer concentration.
- A five-view Streamlit dashboard with interactive charts and downloadable evidence.
- Purchase prediction using past-only features, chronological validation and baseline comparisons.
- Additional time-window checks, probability reliability, uncertainty and cleaning sensitivity.
- 54 automated tests, pinned dependencies and documented source attribution.

On the July 2011 test snapshot, the model achieved **0.710 average precision** versus **0.464** for the recency baseline across **2,724 eligible customers**. The results describe historical purchase propensity, not the causal effect of customer outreach.

## Download and scope

The attached standalone archive contains code, reports and tests. The pipeline retrieves the attributed public source workbook when needed. Local environments, credentials and generated model/data artifacts are excluded.

This is an analytical portfolio release. See the README and assessments for population coverage, reliability and interpretation limits.
