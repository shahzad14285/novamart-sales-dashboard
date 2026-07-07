"""Reusable Upload Center component for the NovaMart Dashboard.

Lets a user drag-and-drop (or browse for) a CSV or Excel file, runs it
through the existing :class:`~utils.data_loader.DataLoader` validation
and cleaning pipeline, and previews the result.

Following the app's layered architecture, this module is UI-only: it
renders Streamlit widgets and translates domain exceptions into
friendly on-screen messages. All reading, validating, and cleaning
logic lives in ``utils/data_loader.py`` -- this component never touches
pandas parsing directly.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from components.empty_state import render_empty_state
from tenancy.context import TenantContext
from tenancy.exceptions import TenantContextError
from utils.data_loader import DataLoader, sales_data_loader
from utils.exceptions import DataLoaderError
from utils.formatting import format_file_size, format_integer

# File extensions accepted by the uploader widget (without the leading dot,
# matching the format st.file_uploader's `type` argument expects).
_ACCEPTED_TYPES: tuple[str, ...] = ("csv", "xlsx")

_DEFAULT_TITLE = "Upload Center"
_DEFAULT_DESCRIPTION = (
    "Drag and drop a CSV or Excel file below to validate it against "
    "NovaMart's expected data format and preview it instantly."
)


def render_upload_center(
    loader: DataLoader | None = None,
    title: str = _DEFAULT_TITLE,
    description: str = _DEFAULT_DESCRIPTION,
    key: str = "upload_center",
    tenant_context: TenantContext | None = None,
) -> pd.DataFrame | None:
    """Render a full upload section: file picker, validation, preview.

    Args:
        loader: A pre-configured :class:`DataLoader` used to validate
            and clean the uploaded file. Defaults to the shared
            ``sales_data_loader`` (expects ``date``, ``revenue``,
            ``orders`` columns), but any ``DataLoader`` can be passed
            in so this component can be reused for a differently
            shaped dataset on a future page.
        title: Section heading shown above the uploader.
        description: Short explanatory text shown under the heading.
        key: Unique Streamlit widget key. Pass a distinct value if
            more than one Upload Center is rendered on the same page.
        tenant_context: The active tenant this upload belongs to
            (Multi-Tenant Sprint 6.3). Required for a file to actually
            be loaded -- if missing, inactive, or unresolved, a
            business-friendly message is shown and ``None`` is
            returned instead of the exception propagating, consistent
            with how this component already handles
            :class:`~utils.exceptions.DataLoaderError`.

    Returns:
        The cleaned, validated DataFrame if a file was uploaded and
        passed validation; otherwise ``None``.
    """
    loader = loader or sales_data_loader

    _render_header(title, description)
    uploaded_file = _render_file_picker(key)

    if uploaded_file is None:
        render_empty_state("No file uploaded yet. Accepted formats: CSV, XLSX.", icon="📄")
        return None

    st.success(f"File received: **{uploaded_file.name}**", icon="✅")

    dataframe = _load_and_validate(loader, uploaded_file, tenant_context=tenant_context)
    if dataframe is None:
        return None

    _render_data_preview(dataframe)
    return dataframe


def _render_header(title: str, description: str) -> None:
    """Render the Upload Center's title and description.

    Args:
        title: Section heading text.
        description: Supporting description text.
    """
    st.markdown(f'<p class="nm-section-title">📤 {title}</p>', unsafe_allow_html=True)
    st.markdown(f'<p class="nm-section-subtitle">{description}</p>', unsafe_allow_html=True)


def _render_file_picker(key: str) -> object | None:
    """Render the drag-and-drop file uploader widget.

    Args:
        key: Unique Streamlit widget key.

    Returns:
        The object Streamlit returns from ``st.file_uploader``: an
        uploaded-file-like object, or ``None`` if nothing is uploaded.
    """
    return st.file_uploader(
        label="Drag and drop a CSV or Excel file here, or click to browse",
        type=list(_ACCEPTED_TYPES),
        key=key,
        help="Accepted formats: .csv, .xlsx. The file must include the "
        "columns required by the selected data loader.",
    )


def _load_and_validate(
    loader: DataLoader, uploaded_file: object, tenant_context: TenantContext | None = None
) -> pd.DataFrame | None:
    """Run the uploaded file through the DataLoader, handling failures.

    Any :class:`~utils.exceptions.DataLoaderError` (missing file,
    unsupported type, missing columns, unreadable file) is caught here
    and shown as a friendly ``st.error`` message instead of crashing
    the page with a raw traceback. A
    :class:`~tenancy.exceptions.TenantContextError` (missing/inactive
    tenant) is handled the same way -- its message is already written
    to be shown as-is, with no technical detail to strip.

    Args:
        loader: The configured DataLoader to validate/clean with.
        uploaded_file: The object returned by ``st.file_uploader``.
        tenant_context: The active tenant this upload belongs to.

    Returns:
        The cleaned DataFrame, or ``None`` if validation failed.
    """
    try:
        return loader.load_uploaded_file(uploaded_file, tenant_context=tenant_context)
    except TenantContextError as exc:
        st.error(str(exc), icon="🔒")
        return None
    except DataLoaderError as exc:
        st.error(str(exc), icon="⚠️")
        return None


def _render_data_preview(df: pd.DataFrame) -> None:
    """Render summary statistics and a first-10-rows preview of ``df``.

    Args:
        df: The cleaned DataFrame to summarize and preview.
    """
    st.markdown("#### Data Preview")

    missing_values = int(df.isna().sum().sum())
    memory_bytes = int(df.memory_usage(deep=True).sum())

    stat_col1, stat_col2, stat_col3, stat_col4 = st.columns(4)
    with stat_col1:
        with st.container(border=True):
            st.metric("Total Rows", format_integer(len(df)))
    with stat_col2:
        with st.container(border=True):
            st.metric("Total Columns", format_integer(df.shape[1]))
    with stat_col3:
        with st.container(border=True):
            st.metric("Missing Values", format_integer(missing_values))
    with stat_col4:
        with st.container(border=True):
            st.metric("Memory Usage", format_file_size(memory_bytes))

    st.dataframe(df.head(10), use_container_width=True)
    st.caption(
        "Showing the first 10 rows. Missing numeric and text values are "
        "automatically filled by the DataLoader; missing dates are kept "
        "blank rather than guessed."
    )
