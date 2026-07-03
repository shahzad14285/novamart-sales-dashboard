# Executive Analytics

The Executive Analytics layer turns the same *filtered* dataset already
powering the Live KPIs section into a tabbed set of deeper views --
Executive Summary, Revenue, Products, Regions -- shown directly below
the KPI cards on the Dashboard page.

## Architecture

```
utils/analytics.py            (pure math: group-by revenue/transactions/top-group/concentration)
utils/calculations.py         (pure math: revenue totals, growth -- reused, not duplicated)
utils/filters.py              (column-availability detection -- reused, not duplicated)
        |
        v
components/analytics/
    revenue.py                 (UI: growth metric + trend chart -- always shown)
    products.py                 (UI: top product + bar chart -- shown only if 'product' column exists)
    regions.py                   (UI: top region + donut chart -- shown only if 'region' column exists)
    executive_summary.py          (UI: narrative + conditional highlight cards)
    __init__.py                    (orchestration: 4-tab layout)
        |
        v
pages/1_Dashboard.py           (wiring: filtered_df -> render_executive_analytics())
```

- **`utils/analytics.py`** is new and holds the only business logic this
  feature needed that didn't already exist: grouping revenue and
  transaction counts by an arbitrary categorical column. It is written
  once, generically (`group_col` parameter), and reused for both
  Products and Regions instead of writing two near-identical modules.
  It has no Streamlit dependency, so it's unit tested directly.
- **Revenue growth and totals are not recomputed.** `revenue.py` and
  `executive_summary.py` both call the existing
  `utils/calculations.py` functions (`calculate_total_revenue`,
  `calculate_kpi_summary`) -- the same functions the KPI cards already
  use above them on the page.
- **Column availability reuses the filter panel's own logic.**
  `products.py`, `regions.py`, and `executive_summary.py` all call
  `utils/filters.py`'s `detect_available_filters()` -- the same
  function that decides whether the Product/Region *filter* widgets
  show up. This guarantees "does this dataset support product
  analytics" is answered identically everywhere in the app, and means
  a dataset without a `product` or `region` column shows an
  informational message (never an error) instead of a blank or broken
  tab.
- **`components/analytics/__init__.py`** is a thin orchestrator: it
  lays out the four `st.tabs` and delegates each one to its module. No
  business logic lives here.
- **`pages/1_Dashboard.py`** calls `render_executive_analytics(filtered_df)`
  inside a try/except, exactly like the existing KPI section above it,
  so an analytics bug shows `st.error()` instead of crashing the page.

### Architectural decision: the standalone Revenue Trend chart moved

The Dashboard page previously showed a standalone "Revenue Trend" chart
(added during the filtering-system task) directly below the KPI cards.
That chart is now shown inside Executive Analytics' **Revenue** tab
instead, alongside a new Revenue Growth metric, rather than being
duplicated in two places on the same page. The chart component itself
(`components/charts.py`'s `render_revenue_trend_chart`) was not
touched -- it's simply called from its new location. This was a
judgment call to avoid showing the identical chart twice; let me know
if you'd prefer it restored to its own section as well.

### Instant updates on filter change

No new state management was needed. Streamlit reruns the whole page
top-to-bottom on every widget interaction, so `render_executive_analytics()`
is called fresh with the latest `filtered_df` every time a filter
changes -- the same mechanism the KPI cards already rely on.

## Files created

- `utils/analytics.py`
- `components/analytics/__init__.py`
- `components/analytics/revenue.py`
- `components/analytics/products.py`
- `components/analytics/regions.py`
- `components/analytics/executive_summary.py`
- `tests/test_analytics.py`

## Files modified

- `pages/1_Dashboard.py` -- replaced the standalone Revenue Trend chart
  call with `render_executive_analytics(filtered_df)`.

## Automated tests

`tests/test_analytics.py` covers all four `utils/analytics.py`
functions: correct sum/sort behavior, missing-column and empty/`None`
DataFrame handling, top-group selection, and revenue-concentration
percentages (top 1 and top 2 groups). All pass against real pandas.

## Manual testing checklist

- [ ] Upload a dataset with only `date`, `revenue`, `orders` (no
      `product`/`customer`/`region`). Confirm the **Products** and
      **Regions** tabs show an informational message ("doesn't include
      a usable 'product'/'region' column...") instead of an error or a
      blank chart.
- [ ] With that same minimal dataset, confirm the **Revenue** tab still
      shows a Total Revenue metric, a Revenue Growth metric, and the
      trend chart -- since `date`/`revenue` are always available.
- [ ] With that same minimal dataset, confirm the **Executive Summary**
      tab shows the narrative revenue sentence and a caption inviting
      you to upload product/region data, with no highlight cards.
- [ ] Upload a full dataset with `product` and `region` columns.
      Confirm all four tabs populate: Executive Summary shows Top
      Product and Top Region highlight cards, Products shows a bar
      chart plus a "Transaction counts by product" expander, Regions
      shows a donut chart of revenue share.
- [ ] Apply a filter (e.g. Region = a single value) via the filter
      panel above. Confirm the KPI cards, Executive Summary, Revenue,
      Products, and Regions tabs all update together without a manual
      refresh.
- [ ] Confirm the Revenue Trend chart appears **once** on the page (in
      the Executive Analytics Revenue tab) -- not duplicated elsewhere
      on the Dashboard.
- [ ] Upload a file that fails validation (e.g. missing a required
      column) and confirm the page shows a clear error instead of
      crashing, with the rest of the page (header, sidebar, upload
      widget) still usable.
