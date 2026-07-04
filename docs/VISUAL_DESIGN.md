# Visual Design Refresh

A presentation-only pass over the NovaMart dashboard: modern executive
styling, consistent typography and spacing, more professional KPI
cards, tab and sidebar polish, better empty states, consistent icons,
and basic responsiveness. No calculation, filtering, or data-loading
code changed anywhere in this pass -- every edit is CSS, markup, or a
one-line text/label swap.

## Design approach

One new module, `components/theme.py`, holds the entire stylesheet as
a single `<style>` block built from `config/settings.py`'s
`THEME_COLORS` -- no new colors were introduced. It targets Streamlit's
own component markup (`stVerticalBlockBorderWrapper`, `stMetric`,
`stTabs`, `stSidebar`, `stAlertContainer`) so that existing widgets
(`st.metric` inside `st.container(border=True)`, `st.tabs`,
`st.divider`) pick up the new look automatically, with zero changes
needed in most files that use them.

A second new module, `components/empty_state.py`, gives every "nothing
to show yet" message (no file uploaded, no data for this view, a
column isn't available) one consistent, centered panel instead of each
module rolling its own `st.info`/`st.caption`.

`components/header.py`'s `inject_header_styles()` -- already called by
every single page right after `st.set_page_config()` -- now delegates
to `components.theme.inject_global_styles()`. That makes it the one
choke point for the whole design system, so no page file needed a new
import just to pick up the stylesheet.

### Judgment call: hiding the duplicate sidebar navigation

Streamlit auto-generates its own page list in the sidebar for any
multipage app, on top of this app's own custom, icon-labeled
`NAV_ITEMS` menu -- so every page was effectively listed twice. Since
`NAV_ITEMS` already covers all six pages, `components/theme.py` hides
the auto-generated list (`div[data-testid="stSidebarNav"] { display:
none; }`) so only the custom, styled menu shows. No page becomes
unreachable. If you'd rather keep both, delete that one CSS rule.

## Files modified

**New:**
- `components/theme.py` -- the app-wide stylesheet (design tokens,
  typography, KPI card hover, tabs, sidebar, empty states, footer,
  accessibility, responsiveness).
- `components/empty_state.py` -- shared `render_empty_state()` helper.

**Changed (styling/markup only):**
- `components/header.py` -- delegates its CSS injection to
  `components/theme.py` instead of its own `<style>` block.
- `components/footer.py` -- dropped its own duplicate `<style>` block
  (class now lives in `theme.py`); markup unchanged.
- `components/sidebar.py` -- replaced hard-coded inline styles
  (including a color not pulled from `THEME_COLORS`) with theme
  classes; same content, same links.
- `app.py` -- removed its now-redundant inline `<style>` block; added
  icons to its two section titles.
- `pages/1_Dashboard.py` -- section title styling; swapped the
  "upload to see KPIs" `st.info` for `render_empty_state`.
- `components/upload_center.py` -- section title/description styling;
  swapped the "no file uploaded" `st.info` for `render_empty_state`.
- `components/filter_panel.py` -- section title styling; swapped the
  "no filterable columns" `st.caption` for `render_empty_state`.
- `components/analytics/__init__.py` -- added an icon to each tab
  label and styled the section title.
- `components/analytics/executive_summary.py`, `revenue.py`,
  `products.py`, `regions.py`, `insights.py` -- swapped each module's
  "no data" / "column not available" message for `render_empty_state`
  (identical text, new container).

**Untouched:** every file in `utils/`, every file in `tests/`,
`config/settings.py`, `config/constants.py`, and all business-logic
call sites (`sales_kpi_engine.calculate_all`, `apply_filters`,
`generate_business_insights`, etc.) -- confirmed via `git status`,
which shows no changes outside `components/`, `app.py`, and
`pages/1_Dashboard.py`.

## Verification performed

- Reconstructed a clean copy of the repository and ran
  `python3 -m py_compile` across `app.py`, every `utils/*.py`,
  `config/*.py`, `components/*.py`, `components/analytics/*.py`,
  `pages/*.py`, and `tests/*.py` -- all compiled cleanly.
- Confirmed via `git status --short` that only presentation files
  changed (`components/`, `app.py`, `pages/1_Dashboard.py`, plus the
  two new modules) -- nothing in `utils/`, `tests/`, or `config/`.
- Ran a Streamlit-stub smoke test that: injects the new stylesheet and
  confirms exactly one `<style>` block is produced app-wide (no
  duplicate injections between `header.py`/`footer.py`/`theme.py`);
  renders the header, footer, and sidebar without exceptions; renders
  the full 5-tab Executive Analytics layer on a populated dataset and
  confirms the tab labels now carry icons and the total metric count
  across all tabs is unchanged at 19 (i.e., styling added zero and
  removed zero metrics); renders Executive Analytics, the Upload
  Center, and the Filter Panel against empty/minimal datasets and
  confirms each now renders exactly one `nm-empty-state` panel instead
  of the old `st.info`/`st.caption` calls, with no exceptions raised.

## Manual testing checklist

- [ ] Launch the app and confirm the sidebar shows the branded logo
      block, one navigation menu (not two), and a "Signed in as"
      line -- the native Streamlit page list should no longer appear
      above/below the custom menu.
- [ ] Open the Dashboard page before uploading anything: confirm the
      Upload Center, Filters-not-yet-available state, and "upload to
      see KPIs" message all appear as centered, muted panels with an
      icon, not plain blue info boxes.
- [ ] Upload a full dataset (with `product`/`region` columns) and
      confirm: KPI cards and Executive Analytics cards lift slightly
      with a soft shadow on mouse hover; the Executive Analytics tabs
      now show icons (🧾 💡 💰 📦 🌍) and the active tab is clearly
      highlighted; section titles ("📊 Key Performance Indicators",
      "🔍 Filters", "🧭 Executive Analytics") are visually larger and
      bolder than surrounding text.
- [ ] Upload a minimal dataset (no `product`/`region`) and confirm the
      Products/Regions tabs show the new dashed-border empty-state
      panel with an icon, not the old plain info box -- same message
      text as before.
- [ ] Resize the browser window to a narrow (mobile-ish) width and
      confirm columns stack, headings/metric values shrink slightly
      rather than overflowing, and empty-state panels keep readable
      padding.
- [ ] Tab through the page using only the keyboard and confirm a
      visible focus outline appears on links, buttons, and inputs.
- [ ] Confirm every KPI value, chart, and analytics card still shows
      the same numbers as before this change for the same uploaded
      file and filters -- this pass changed no calculations.
