"""Read-only report access and metric definitions for the dashboard."""
import json
from pathlib import Path

import pandas as pd


REPORT_FILES = {
    'monthly': 'monthly_analysis.csv',
    'cohorts': 'cohort_activity.csv',
    'concentration': 'customer_concentration.csv',
    'summary': 'analysis_summary.json',
}


def load_reports(report_dir: Path) -> dict:
    report_dir = Path(report_dir)
    missing = [name for name in REPORT_FILES.values() if not (report_dir / name).is_file()]
    if missing:
        raise FileNotFoundError('Missing reports: ' + ', '.join(missing) +
                                '. Run analysis.py from the project folder to generate them.')
    return {
        'monthly': pd.read_csv(report_dir / REPORT_FILES['monthly'], dtype={'month': str}),
        'cohorts': pd.read_csv(report_dir / REPORT_FILES['cohorts'],
                               dtype={'cohort_month': str, 'activity_month': str}),
        'concentration': pd.read_csv(report_dir / REPORT_FILES['concentration'],
                                     dtype={'customer_id': str}, keep_default_na=False),
        'summary': json.loads((report_dir / REPORT_FILES['summary']).read_text(encoding='utf-8')),
    }


def select_months(monthly, start, end):
    if start > end:
        raise ValueError('Start month must not follow end month')
    return monthly.loc[monthly.is_complete_month.eq(1) & monthly.month.between(start, end)].copy()


def period_metrics(monthly):
    value, orders = float(monthly.positive_sales_value.sum()), int(monthly.orders.sum())
    identified = float((monthly.first_observed_month_value + monthly.previously_observed_value).sum())
    return {'value': value, 'orders': orders, 'aov': value / orders if orders else None,
            'identified_value_share': identified / value if value else None}
