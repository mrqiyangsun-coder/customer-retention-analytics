"""Static analysis figures; masked cells are unobserved rather than zero."""

import math
import os
from pathlib import Path

import pandas as pd


def create_charts(tables, output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    cache = Path(__file__).resolve().parent / "data" / "matplotlib_cache"
    cache.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("MPLCONFIGDIR", str(cache))
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt
    from matplotlib.ticker import PercentFormatter
    plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False,
                         "axes.titleweight": "bold", "figure.facecolor": "white"})
    monthly = tables["monthly"].loc[tables["monthly"].is_complete_month.eq(1)].copy()
    dates = pd.to_datetime(monthly["month"])

    def format_month_axis(ax):
        if dates.empty:
            ax.text(.5, .5, "No complete calendar months", ha="center", va="center", transform=ax.transAxes)
            ax.set_axis_off()
            return
        indices = list(range(0, len(dates), 3 if len(dates) > 9 else 1))
        if indices[-1] != len(dates) - 1:
            indices.append(len(dates) - 1)
        ax.set_xticks(dates.iloc[indices])
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%b\n%Y"))
        ax.set_xlim(dates.min() - pd.Timedelta(days=15), dates.max() + pd.Timedelta(days=15))

    fig, ax = plt.subplots(figsize=(11, 5), layout="constrained")
    ax.plot(dates, monthly["positive_sales_value"] / 1_000_000, color="#146c94", marker="o", markersize=4, linewidth=2)
    ax.set(title="Monthly positive recorded sales value", ylabel="GBP millions", xlabel="Complete calendar months only")
    format_month_axis(ax)
    ax.grid(axis="y", alpha=.2)
    fig.savefig(output / "monthly_sales.png", dpi=160)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(11, 5.5), layout="constrained")
    previous = monthly["previously_observed_value"] / 1_000_000
    first = monthly["first_observed_month_value"] / 1_000_000
    anonymous = monthly["anonymous_value"] / 1_000_000
    ax.bar(dates, first, width=22, label="First observed this month", color="#d49328")
    ax.bar(dates, previous, bottom=first, width=22, label="Observed before this month", color="#147d73")
    ax.bar(dates, anonymous, bottom=first + previous, width=22, label="Unidentified", color="#b5bec7")
    ax.set(title="Who contributed each month's recorded positive value?", ylabel="GBP millions", xlabel="Customer-month categories; first observed is not necessarily newly acquired")
    format_month_axis(ax)
    ax.legend(loc="upper left", fontsize=9)
    ax.grid(axis="y", alpha=.15)
    fig.savefig(output / "customer_mix.png", dpi=160)
    plt.close(fig)

    cohorts = tables["cohorts"]
    if cohorts.empty:
        fig, ax = plt.subplots(figsize=(10, 4))
        ax.text(.5, .5, "No fully observable identified-customer cohorts", ha="center", va="center")
        ax.set_axis_off()
    else:
        matrix = cohorts.pivot(index="cohort_month", columns="month_age", values="activity_rate").reindex(columns=range(13))
        sizes = cohorts.drop_duplicates("cohort_month").set_index("cohort_month")["cohort_size"]
        fig, ax = plt.subplots(figsize=(12, max(4, .36 * len(matrix) + 2)), layout="constrained")
        colors = matplotlib.colormaps["Blues"].copy()
        colors.set_bad("#e5e7eb")
        heat = ax.imshow(matrix.to_numpy(dtype=float), vmin=0, vmax=1, cmap=colors, aspect="auto")
        ax.set_xticks(range(13), [str(age) for age in range(13)])
        ax.set_yticks(range(len(matrix)), [f"{month}  (n={int(sizes.loc[month]):,})" for month in matrix.index])
        ax.tick_params(axis="y", labelsize=8)
        ax.set(title="Share of each cohort purchasing in that exact calendar month", xlabel="Months after first observed purchase month; gray = not fully observed", ylabel="First observed cohort (not proven acquisition)")
        for row in range(len(matrix)):
            for col in range(13):
                value = matrix.iloc[row, col]
                if pd.notna(value):
                    ax.text(col, row, f"{value:.0%}", ha="center", va="center", fontsize=7.5,
                            color="white" if value > .65 else "#18334b")
        bar = fig.colorbar(heat, ax=ax, fraction=.035, pad=.02)
        bar.ax.yaxis.set_major_formatter(PercentFormatter(1))
    fig.savefig(output / "cohort_activity.png", dpi=160, bbox_inches="tight")
    plt.close(fig)

    concentration = tables["concentration"]
    fig, ax = plt.subplots(figsize=(10, 5), layout="constrained")
    if not concentration.empty:
        ax.plot([0] + concentration.customer_share.tolist(), [0] + concentration.cumulative_value_share.tolist(), color="#146c94", linewidth=2)
        count = math.ceil(len(concentration) * .1)
        row = concentration.iloc[count - 1]
        ax.scatter([row.customer_share], [row.cumulative_value_share], color="#b75a28", s=35, zorder=3)
        ax.text(.34, .16, f"Top {count:,} of {len(concentration):,} identified customers\n{row.cumulative_value_share:.1%} of identified positive value", transform=ax.transAxes)
    ax.plot([0, 1], [0, 1], color="#aab1b8", linestyle="--", label="Equal-value reference")
    ax.set(xlim=(0, 1), ylim=(0, 1.02), title="Recorded value is concentrated among identified customers",
           xlabel="Share of identified customers, ranked highest value first", ylabel="Cumulative share of identified positive value")
    ax.xaxis.set_major_formatter(PercentFormatter(1))
    ax.yaxis.set_major_formatter(PercentFormatter(1))
    ax.grid(alpha=.15)
    ax.legend(loc="lower right")
    fig.savefig(output / "customer_concentration.png", dpi=160)
    plt.close(fig)
