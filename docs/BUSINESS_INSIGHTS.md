# Business Insights

The Business Insights panel turns the same filtered dataset already
powering the KPI cards and Executive Analytics tabs into a set of
executive-level observation cards -- revenue/order pacing, the single
best and worst sales day, and (when available) the best/worst product
or region and how concentrated revenue is among the top products. It
lives in its own **Business Insights** tab inside Executive Analytics.

## Architecture

```
utils/calculations.py     (existing: total revenue/orders, highest/lowest revenue day)
utils/analytics.py        (existing: revenue-by-group, revenue concentration)
utils/filters.py          (existing: detect_available_filters -- column availability)
        |
        v
utils/insights.py          (new: daily pacing, active-day counting, best/worst-of-group,
                             BusinessInsights value object, generate_business_insights())
        |
        v
components/analytics/insights.py   (new: UI-only -- renders BusinessInsights as metric cards)
        |
        v
components/analytics/__init__.py   (updated: 5th tab, "Business Insights")
        |
        v
pages/1_Dashboard.py       (unchanged -- already calls render_executive_analytics())
```

- **`utils/insights.py`** adds only the calculations that didn't
  already exist: active sales day counting, revenue/orders per active
  day, total transaction count, and picking the best/worst end of an
  already-computed group-by series. Total revenue, total orders,
  highest/lowest revenue day, best/worst product or region, and top-3
  revenue concentration are **not recomputed** -- they call straight
  into the existing `utils/calculations.py` and `utils/analytics.py`
  functions used elsewhere in the app (Revenue tab, Products tab,
  Regions tab, KPI cards). This is the same "define once, reuse
  everywhere" pattern the Executive Analytics package already
  established.
- **`generate_business_insights()`** is the single orchestration
  function. It returns a frozen `BusinessInsights` dataclass -- a
  value object, mirroring the existing `KPIResult`/`FilterField`
  pattern -- so the UI layer never recomputes anything, it only
  decides layout and which optional cards to show.
- **Optional-column detection is reused, not reimplemented.**
  `generate_business_insights()` calls `utils.filters.detect_available_filters()`
  -- the exact function that decides whether the Product/Region filter
  widgets, and the Products/Regions analytics tabs, are shown. This
  keeps "does this dataset support product/region insights" answered
  identically everywhere in the app.
- **`components/analytics/insights.py`** is UI-only: it lays out
  `st.metric` cards inside `st.container(border=True)`, the same
  bordered-card styling used by `components/kpi_cards.py` and every
  other analytics module. It computes nothing -- if a value looks
  wrong, the bug is in `utils/insights.py`, never here.
- **`components/analytics/__init__.py`** now lays out five tabs
  instead of four: Executive Summary, **Business Insights**, Revenue,
  Products, Regions. No other module changed.

### Cards shown

Always shown (require only the validated `date`/`revenue`/`orders`
columns): Total Revenue, Average Daily Revenue, Total Orders, Average
Orders / Day, Highest Revenue Day, Lowest Revenue Day, Total
Transactions, Active Sales Days.

Shown only when a usable `product` column exists: Best Product, Worst
Product, Revenue Concentration (Top 3).

Shown only when a usable `region` column exists: Best Region, Worst
Region.

If neither `product` nor `region` is available, a caption invites the
user to upload a dataset with those columns -- never an error.

### Instant updates on filter change

No new state management was needed, for the same reason as the rest of
Executive Analytics: Streamlit reruns the page top-to-bottom on every
widget interaction, so `render_business_insights()` runs fresh against
the latest filtered DataFrame every time a filter changes.

## Files created

- `utils/insights.py`
- `components/analytics/insights.py`
- `tests/test_insights.py`

## Files modified

- `components/analytics/__init__.py` -- added the Business Insights tab
  and its import.

No unrelated modules were touched; `pages/1_Dashboard.py` did not need
changes since it already calls `render_executive_analytics()`, which
now includes the new tab automatically.

## Automated tests

`tests/test_insights.py` covers every new function in `utils/insights.py`:
active sales day counting (including duplicate dates and missing
dates), average daily revenue/orders (including the zero-active-days
case), total transaction counts, best/worst-group selection (including
a single-group tie case), and the full `generate_business_insights()`
orchestrator across a full dataset, a minimal dataset (no
product/region), an empty DataFrame, a `None` DataFrame, and a
5-product concentration case. All pass against real pandas.

## Manual testing checklist

- [ ] Upload a dataset with only `date`, `revenue`, `orders`. Open the
      **Business Insights** tab and confirm the 8 core cards (Total
      Revenue, Average Daily Revenue, Total Orders, Average Orders /
      Day, Highest/Lowest Revenue Day, Total Transactions, Active
      Sales Days) all show real numbers, and a caption invites you to
      upload product/region data -- no Best/Worst Product or Region
      cards appear.
- [ ] Upload a full dataset with `product` and `region` columns.
      Confirm Best Product, Worst Product, and Revenue Concentration
      (Top 3) appear, and Best Region / Worst Region appear, with no
      caption.
- [ ] Confirm the values shown match the Products/Regions tabs' "Top
      Product"/"Top Region" cards for the same dataset (both derive
      from the same `utils/analytics.py` group-by).
- [ ] Apply a filter (e.g. a single Region) via the filter panel and
      confirm every Business Insights card recalculates immediately,
      alongside the KPI cards and the other Executive Analytics tabs.
- [ ] Upload a dataset where all rows share one product (or one
      region) and confirm Best and Worst show the same value instead
      of erroring.
- [ ] Confirm the Business Insights tab shows no charts -- only metric
      cards, per its "insight cards" scope -- and that its bordered
      card styling matches the KPI cards and other analytics tabs.
