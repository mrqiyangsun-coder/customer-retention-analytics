"""Local analyst dashboard over the verified, reproducible report tables."""
import math
import json
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

from dashboard_data import REPORT_FILES, load_reports, period_metrics, select_months


ROOT = Path(__file__).resolve().parent
TEAL = '#127B78'
BLUE = '#246A98'


def money(value):
    return 'Not defined' if value is None else f'GBP {value:,.2f}'


def sales_view(reports):
    monthly = reports['monthly']
    full = monthly.loc[monthly.is_complete_month.eq(1)].sort_values('month')
    st.subheader('Sales overview')
    st.caption('Scope: selected complete calendar months. Positive recorded charges before refunds; not net revenue or profit.')
    if full.empty:
        st.info('No complete calendar months available for sales comparisons.')
        return
    months = full.month.tolist()
    left, right = st.columns(2)
    start = left.selectbox('Start month', months, key='start_month')
    end = right.selectbox('End month', months, index=len(months) - 1, key='end_month')
    if start > end:
        st.warning('Choose an end month on or after the start month.')
        return
    selected = select_months(monthly, start, end)
    metric = period_metrics(selected)
    cards = st.columns(4)
    cards[0].metric('Positive sales value', money(metric['value']), border=True)
    cards[1].metric('Orders', f"{metric['orders']:,}", border=True)
    cards[2].metric('Average order value', money(metric['aov']), border=True)
    coverage = metric['identified_value_share']
    cards[3].metric('Value linked to customers', 'Not defined' if coverage is None else f'{coverage:.1%}', border=True)
    st.caption(f'{start} to {end} · AOV = total selected value / total selected orders. Customer coverage is a value share, not a customer count.')
    chart_data = selected.assign(date=pd.to_datetime(selected.month + '-01'))
    measure = st.radio('Trend measure', ['Positive sales value', 'Orders', 'Average order value'], horizontal=True)
    field = {'Positive sales value': 'positive_sales_value', 'Orders': 'orders', 'Average order value': 'average_order_value'}[measure]
    # Minimal hand-derived report fixtures need no precomputed AOV column.
    if field == 'average_order_value':
        chart_data[field] = chart_data.positive_sales_value.div(chart_data.orders.where(chart_data.orders.ne(0)))
    trend = alt.Chart(chart_data).mark_line(point=True, color=BLUE, strokeWidth=3).encode(
        x=alt.X('date:T', title='Calendar month', axis=alt.Axis(format='%b %Y')),
        y=alt.Y(field + ':Q', title=measure + (' (GBP)' if field != 'orders' else ''), scale=alt.Scale(zero=True)),
        tooltip=[alt.Tooltip('month:N', title='Month'), alt.Tooltip(field + ':Q', title=measure, format=',.2f')],
    ).properties(height=310)
    st.altair_chart(trend, width='stretch')
    st.markdown('#### Customer contribution to sales')
    mix = chart_data.melt(id_vars=['date', 'month'], value_vars=[
        'first_observed_month_value', 'previously_observed_value', 'anonymous_value'],
        var_name='segment', value_name='value')
    mix['segment'] = mix.segment.map({'first_observed_month_value': 'First observed this month',
        'previously_observed_value': 'Observed before this month', 'anonymous_value': 'Unidentified'})
    chart = alt.Chart(mix).mark_bar().encode(
        x=alt.X('date:T', title='Calendar month', axis=alt.Axis(format='%b %Y')),
        y=alt.Y('value:Q', title='Positive recorded value (GBP)'),
        color=alt.Color('segment:N', title=None, scale=alt.Scale(domain=[
            'First observed this month', 'Observed before this month', 'Unidentified'],
            range=['#D79829', TEAL, '#A8B3BD']), legend=alt.Legend(orient='bottom')),
        tooltip=['month:N', 'segment:N', alt.Tooltip('value:Q', format=',.2f')],
    ).properties(height=280)
    st.altair_chart(chart, width='stretch')
    st.caption('First observed is not necessarily newly acquired. Every purchase in a customer’s first observed month stays in that segment.')
    summary = reports['summary'].get('matched_year_comparison')
    if summary:
        with st.expander('Reference finding: matched calendar months across years'):
            changes = {key: 'Not defined' if summary.get(key) is None else f'{summary[key]:+.1%}'
                       for key in ['value_change', 'order_change', 'aov_change']}
            st.write(f"Across shared complete months in {summary['earlier_year']} and {summary['later_year']}, "
                     f"value changed {changes['value_change']}, orders {changes['order_change']}, "
                     f"and average order value {changes['aov_change']}.")
            st.caption('Fixed reference comparison from the memo; independent of the sales filters above. This decomposition does not establish the cause.')
    with st.expander('Selected monthly data'):
        st.dataframe(selected, hide_index=True, width='stretch')
    st.download_button('Download selected monthly data', selected.to_csv(index=False),
                       file_name=f'monthly_{start}_{end}.csv', mime='text/csv')


def cohort_view(reports):
    st.subheader('Customer cohorts')
    st.caption('Scope: full observed customer histories, grouped by first observed purchase month. Sales filters do not apply. Blank cells are unobserved; zero means observed with no purchases.')
    st.info('Activity = customers purchasing in that exact calendar month / customers in the cohort. Customers can leave and return; this is not permanent churn.')
    cohorts = reports['cohorts']
    if cohorts.empty:
        st.info('No identified customer cohorts with complete observation windows are available.')
        return
    maximum = int(cohorts.month_age.max())
    horizon = st.slider('Months since first observed purchase', 0, max(1, maximum), min(12, maximum))
    shown = cohorts.loc[cohorts.month_age.le(horizon)].copy()
    grid = shown.pivot(index='cohort_month', columns='month_age', values='activity_rate').reindex(columns=range(horizon + 1))
    base = grid.rename_axis(index='cohort_month', columns='month_age').reset_index().melt(
        id_vars='cohort_month', var_name='month_age', value_name='activity_rate')
    positions = dict(x=alt.X('month_age:O', title='Months since first observed purchase'),
                     y=alt.Y('cohort_month:O', title='First observed month', sort='ascending'))
    background = alt.Chart(base).mark_rect(color='#E2E7EC').encode(**positions)
    chart = alt.Chart(shown).mark_rect(stroke='white', strokeWidth=1).encode(
        **positions,
        color=alt.Color('activity_rate:Q', title='Active share', scale=alt.Scale(domain=[0, 1], scheme='tealblues'), legend=alt.Legend(format='.0%')),
        tooltip=['cohort_month:N', 'activity_month:N', 'month_age:O', 'cohort_size:Q',
                 'active_customers:Q', alt.Tooltip('activity_rate:Q', format='.1%')],
    )
    st.altair_chart((background + chart).properties(height=max(180, len(grid) * 22)), width='stretch')
    st.caption('Gray = unobserved or partial follow-up. The initial dataset cohort has truncated prior history; first observed purchase is not acquisition.')
    month1 = reports['summary'].get('month1_activity_excluding_initial_cohort')
    if month1:
        st.metric('Next-month activity, excluding initial cohort', f"{month1['activity_rate']:.1%}")
        st.caption(f"{month1['active_customers']:,} active / {month1['customers']:,} customers across {month1['eligible_cohorts']} eligible cohorts. Fixed full-history measure, independent of the chart horizon.")
    with st.expander('Cohort rates as a table'):
        st.dataframe(grid.style.format('{:.1%}', na_rep='Not observed'), width='stretch')
    st.download_button('Download observed cohort activity', cohorts.to_csv(index=False),
                       file_name='cohort_activity.csv', mime='text/csv')


def concentration_view(reports):
    st.subheader('Customer concentration')
    st.caption('Scope: full observed histories of identified customers. Sales filters do not apply; anonymous sales are outside the value denominator.')
    customers = reports['concentration']
    if customers.empty:
        st.info('No identified customer value is available for concentration analysis.')
        return
    top_count = math.ceil(len(customers) * .10)
    share = float(customers.iloc[top_count - 1].cumulative_value_share)
    cards = st.columns(3)
    cards[0].metric('Identified customers', f'{len(customers):,}', border=True)
    cards[1].metric('Top 10% share of identified value', f'{share:.1%}', border=True)
    cards[2].metric('Customers in rounded-up top 10%', f'{top_count:,}', border=True)
    # Inline values avoid Altair's 5,000-row DataFrame limit for this small curve.
    points = customers[['customer_share', 'cumulative_value_share']].to_dict('records')
    points.insert(0, {'customer_share': 0., 'cumulative_value_share': 0.})
    chart = alt.Chart(alt.InlineData(values=points)).mark_line(color=TEAL, strokeWidth=3).encode(
        x=alt.X('customer_share:Q', title='Cumulative share of identified customers, largest first', axis=alt.Axis(format='.0%'), scale=alt.Scale(domain=[0, 1])),
        y=alt.Y('cumulative_value_share:Q', title='Cumulative share of identified positive value', axis=alt.Axis(format='.0%'), scale=alt.Scale(domain=[0, 1])),
        tooltip=[alt.Tooltip('customer_share:Q', format='.1%'), alt.Tooltip('cumulative_value_share:Q', format='.1%')],
    )
    marker = alt.Chart(pd.DataFrame({'customer_share': [top_count / len(customers)], 'cumulative_value_share': [share]})).mark_point(color='#D79829', size=120, filled=True).encode(x='customer_share:Q', y='cumulative_value_share:Q')
    st.altair_chart((chart + marker).properties(height=380), width='stretch')
    st.caption('Customers have unequal observation histories. Concentration describes historical dependence; it does not establish future customer value.')
    with st.expander('Highest observed customer values'):
        st.dataframe(customers.head(20), hide_index=True, width='stretch')
    st.download_button('Download customer concentration', customers.to_csv(index=False),
                       file_name='customer_concentration.csv', mime='text/csv')


def definitions_view(reports, report_dir):
    st.subheader('Definitions & downloads')
    st.markdown('''
**Positive sales value:** qualifying positive recorded charges under the documented cleaning policy. Refunds and adjustments are not deducted. This is not net revenue or profit; shipping and manual charges may be included.

**Orders:** distinct qualifying invoices. Invoice lines are not orders.

**Identified customers:** orders link to a usable, unambiguous customer ID. Anonymous sales remain in sales totals but do not enter customer histories.

**Complete months:** only fully observed calendar months enter sales comparisons. December 2011 is partial in this source.

**First observed:** first purchase within this dataset, not necessarily actual acquisition. The observation window starts in December 2009.

**Cohort activity:** purchasing at least once in a specific later calendar month. A blank future/partial cell is not a zero.

**Business use:** investigate order/customer mix, concentration and repeat purchasing; evaluate proposed interventions with an experiment before claiming marketing uplift.

**Source:** Chen, D. (2012), [Online Retail II, UCI](https://doi.org/10.24432/C5CG6D), CC BY 4.0. Historical UK gift retail including wholesalers; findings do not automatically generalize to other businesses.
''')
    summary = reports['summary']
    st.caption(f"Reports generated: {summary.get('generated_at_utc', 'Not recorded')} · Cleaning rules version: {summary.get('rules_version', 'Not recorded')}")
    for name in REPORT_FILES.values():
        st.download_button('Download ' + name, (report_dir / name).read_bytes(), file_name=name,
                           mime='application/json' if name.endswith('.json') else 'text/csv', key='download_' + name)
    memo = report_dir / 'business_memo.md'
    if memo.is_file():
        st.download_button('Download business memo', memo.read_bytes(), file_name=memo.name, mime='text/markdown')
    with st.expander('Dataset provenance'):
        st.json({key: summary.get(key) for key in ['source_sha256', 'database_sha256', 'rules_version', 'generated_at_utc']})


def prediction_view(report_dir):
    st.subheader('Purchase prediction')
    st.caption('Scope: identified customers with at least one qualifying purchase in the preceding 180 days. Target: purchasing within the next 60 days. Scores are purchase propensity, not campaign uplift or permanent churn.')
    supplemental = report_dir / 'release_evaluation.json'
    if supplemental.is_file():
        evaluation = json.loads(supplemental.read_text(encoding='utf-8'))
        with st.expander('Release 1.0: additional periods and probability reliability', expanded=True):
            rows = [{'Cutoff': row['cutoff'], 'Model AP': row['model_metrics']['average_precision'],
                     'Recency AP': row['recency_metrics']['average_precision'],
                     'Purchase rate': row['model_metrics']['prevalence'], '10-bin ECE': row['ece']}
                    for row in evaluation['windows']]
            st.dataframe(pd.DataFrame(rows), hide_index=True, width='stretch')
            st.caption('Frozen model; additional windows were not used for tuning. Customers recur across periods. Probability reliability changes over time: September ECE is about 0.090. Strong ranking does not guarantee calibrated probabilities.')
            figure = report_dir / 'figures/reliability.png'
            if figure.is_file():
                st.image(str(figure), caption='Ten fixed probability bins; compare mean prediction with observed purchase rate.')
            st.download_button('Download robustness and sensitivity evidence', supplemental.read_bytes(), file_name=supplemental.name, mime='application/json')
    path = report_dir / 'prediction_metrics.json'
    if not path.is_file():
        st.info('Prediction report is not available yet. Run prediction.py from the project directory to generate the study.')
        return
    try:
        report = json.loads(path.read_text(encoding='utf-8'))
    except (ValueError, OSError) as error:
        st.error(f'Cannot read prediction report: {error}')
        return
    selected = report['selected_model']
    scores = report['test'][selected]
    st.markdown(f"**Selected model:** `{selected}` · {report.get('implementation', 'See assessment')}.")
    st.caption('Model choice used validation average precision only. The later test period was reserved; neither the unselected candidate nor test-driven tuning is reported.')
    cards = st.columns(4)
    cards[0].metric('Average precision', f"{scores['average_precision']:.3f}", border=True)
    cards[1].metric('ROC AUC', 'Not defined' if scores['roc_auc'] is None else f"{scores['roc_auc']:.3f}", border=True)
    cards[2].metric('Top 10% buy rate', f"{scores['precision_at_top_decile']:.1%}", border=True)
    cards[3].metric('Overall buy rate', f"{scores['prevalence']:.1%}", border=True)
    st.caption(f"{scores['customers']:,} eligible test customers; highest-scored {scores['top_decile_customers']:,} form the rounded-up top 10%. Tied scores use customer ID only to make ranking reproducible.")
    frame = pd.DataFrame(report['test']).T.rename_axis('Estimator').reset_index()
    plot = alt.Chart(frame).mark_bar(color=TEAL).encode(
        x=alt.X('average_precision:Q', title='Reserved-test average precision', scale=alt.Scale(domain=[0, 1])),
        y=alt.Y('Estimator:N', sort='-x', title=None),
        tooltip=['Estimator:N', alt.Tooltip('average_precision:Q', format='.3f')],
    ).properties(height=190)
    st.altair_chart(plot, width='stretch')
    st.dataframe(frame, hide_index=True, width='stretch')
    st.caption('AP and AUC measure ranking; Brier measures probability error (lower is better). Lift is relative to test prevalence, not incremental purchases. Constant-baseline top-decile results reflect arbitrary tie order.')
    with st.expander('Study dates, validation and features'):
        st.dataframe(pd.DataFrame([{'Split': split, 'Cutoff': date} for split, date in report['cutoffs'].items()]), hide_index=True)
        st.write('Features: ' + ', '.join(report['features']))
        st.dataframe(pd.DataFrame(report['validation']).T.rename_axis('Estimator'), width='stretch')
    st.warning('One historical test snapshot. Customers can recur across periods; anonymous and long-inactive customers are excluded. No confidence interval, production readiness or causal marketing benefit is claimed.')
    st.download_button('Download prediction metrics', path.read_bytes(), file_name=path.name, mime='application/json')
    assessment = report_dir / 'prediction_assessment.md'
    if assessment.is_file():
        st.download_button('Download model assessment', assessment.read_bytes(), file_name=assessment.name, mime='text/markdown')


def main():
    st.set_page_config(page_title='Customer Retention | Retail Analytics', page_icon='📊', layout='wide')
    st.sidebar.markdown('### RETAIL ANALYTICS')
    st.sidebar.caption('Customer retention & recorded sales')
    view = st.sidebar.radio('Explore', ['Sales overview', 'Customer cohorts', 'Customer concentration', 'Purchase prediction', 'Definitions & downloads'], key='view')
    st.sidebar.divider()
    st.sidebar.caption('Historical UK retailer · 2009–2011\n\nDescriptive evidence. No causal impact claims.')
    st.title('Customer Retention & Sales Analytics')
    st.caption('Understand purchasing patterns, customer dependence and the limits of the evidence.')
    report_dir = Path(st.session_state.get('_report_dir', ROOT / 'reports'))
    try:
        reports = load_reports(report_dir)
    except (FileNotFoundError, ValueError, pd.errors.ParserError) as error:
        st.error(str(error))
        st.stop()
    if view == 'Sales overview':
        sales_view(reports)
    elif view == 'Customer cohorts':
        cohort_view(reports)
    elif view == 'Customer concentration':
        concentration_view(reports)
    elif view == 'Purchase prediction':
        prediction_view(report_dir)
    else:
        definitions_view(reports, report_dir)


if __name__ == '__main__':
    main()
