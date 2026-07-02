# KPI Engine

The KPI Engine turns a validated sales DataFrame into a set of
ready-to-display Key Performance Indicators, and powers the Dashboard
page's "Live KPIs" section: whatever file a user uploads through the
Upload Center, the KPI cards below it recalculate automatically.

## KPI Architecture

```
utils/calculations.py     (pure math: sums, averages, day-level aggregation)
        |
        v
utils/kpi_engine.py        (orchestration: KPIResult, KPIEngine registry)
        |
        v
components/kpi_cards.py    (UI only: renders KPIResult objects as st.metric cards)
        |
        v
pages/1_Dashboard.py       (wiring: uploaded df -> engine -> cards)
```

- **`utils/calculations.py`** owns every numeric formula. Nothing in
  `kpi_engine.py` computes a sum, average, or aggregation itself --
  it always calls into this module. This is what "don't duplicate
  business logic" means in practice: the formula for "total revenue"
  is defined exactly once, whether it's shown on the Home page's
  placeholder KPIs or the Dashboard's live KPIs.
- **`utils/kpi_engine.py`** defines `KPIResult` (a small, frozen
  dataclass holding a KPI's key, label, raw value, formatted string,
  icon, and help text) and `KPIEngine`, a registry-based class that
  maps KPI keys to calculation functions. It has **no Streamlit
  dependency** -- it can be imported and tested (or reused in a
  notebook, a script, another app) without Streamlit installed.
- **`components/kpi_cards.py`** is UI-only. `render_kpi_cards()` takes
  the dict of `KPIResult` objects `KPIEngine.calculate_all()` returns
  and lays them out as bordered `st.metric` cards, 3 per row by
  default -- the same card styling already used on the Home page and
  in the Upload Center's data preview.
- **`pages/1_Dashboard.py`** does the wiring: it calls
  `render_upload_center()` (unchanged from the previous Upload Center
  work), and if a file was uploaded and passed validation, feeds the
  returned DataFrame into `sales_kpi_engine.calculate_all()` and renders
  the result with `render_kpi_cards()`.

### Why this "automatically refreshes"

`render_upload_center()` already returns the *current* validated
DataFrame (or `None`) on every call -- it isn't cached across uploads.
Streamlit re-runs the entire page script top-to-bottom whenever a
widget's value changes, including the file uploader. So every time a
user uploads a new file, the script re-executes, `render_upload_center()`
returns the new DataFrame, and the KPI section recomputes from it. There
is no session-state flag to manage and no cache to invalidate.

## Formula Used for Each KPI

| KPI | Key | Formula | Defined in |
|---|---|---|---|
| Total Revenue | `total_revenue` | `sum(revenue)` | `calculate_total_revenue()` |
| Total Orders | `total_orders` | `sum(orders)` | `calculate_total_orders()` |
| Avg. Revenue / Order | `avg_revenue_per_order` | `sum(revenue) / sum(orders)` (0 if no orders) | `calculate_average_order_value()` |
| Total Transactions | `total_transactions` | `count(rows)` in the dataset | inline in `_kpi_total_transactions()` |
| Highest Revenue Day | `highest_revenue_day` | `date` with `max(sum(revenue) grouped by date)` | `find_highest_revenue_day()` |
| Lowest Revenue Day | `lowest_revenue_day` | `date` with `min(sum(revenue) grouped by date)` | `find_lowest_revenue_day()` |

Notes:

- **Total Orders vs. Total Transactions** are intentionally different
  metrics: *Total Orders* sums the `orders` column (which may itself
  represent multiple orders per row, e.g. a daily rollup), while *Total
  Transactions* counts dataset rows/records. For a raw, one-row-per-order
  file the two will be equal; for an aggregated daily file they won't be.
- **Highest/Lowest Revenue Day** group by date first (summing revenue
  for rows that share a date) before finding the max/min, so the result
  is correct whether the dataset has one row per day or many.
- Rows with a missing/unparseable date are excluded from the
  highest/lowest-day calculation (pandas `groupby` drops `NaT` keys),
  so a bad date never wins "highest revenue day" by accident.
- If the uploaded file is empty or a required column is somehow
  missing, every KPI degrades gracefully (`0`, `0.0`, or `"N/A"` for
  the day KPIs) instead of raising.

## Future Extension Ideas

Adding a new KPI never requires modifying `KPIEngine` itself -- just
register a new function:

```python
from utils.kpi_engine import KPIEngine, KPIResult

def _kpi_median_order_value(df, date_col, revenue_col, orders_col):
    median = df[revenue_col].median() if not df.empty else 0.0
    return KPIResult(
        key="median_order_value",
        label="Median Order Value",
        value=median,
        formatted=f"${median:,.2f}",
        icon="📐",
    )

engine = KPIEngine()
engine.register("median_order_value", _kpi_median_order_value)
```

Ideas worth adding as the dashboard matures:

- **Period-over-period growth**: reuse the existing
  `calculate_growth_rate()` and `split_period_in_half()` from
  `calculations.py` (already used by the Home page) to add revenue/order
  growth deltas to the live KPI cards, shown via `st.metric`'s `delta`.
- **Revenue by category/region**: once an uploaded file includes a
  category or region column, add a KPI (or a small chart component)
  showing the top-performing segment.
- **Moving averages**: a 7-day or 30-day rolling revenue average,
  useful for smoothing out daily volatility.
- **Median / percentile order value**: complements the mean-based
  "Avg. Revenue / Order" KPI with a distribution-aware view.
- **Top N days/products**: extend the highest/lowest-day pattern into
  a ranked top-5 list rather than a single extreme value.
- **Configurable thresholds**: let a KPI's `help_text` or an additional
  `status` field flag when a value crosses a user-defined threshold
  (e.g. revenue below target), surfaced as a warning-colored card.
- **Caching for large files**: `KPIEngine.calculate_all()` is cheap
  pure-Python/pandas today; if datasets grow large, wrap it with
  `st.cache_data` the same way `utils/data_loader.py` caches disk reads
  (keying on a hash of the DataFrame or the uploaded file's bytes).
