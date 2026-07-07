"""Data access layer for the NovaMart Sales Intelligence Dashboard.

This module is the single place responsible for reading data from disk
(and, in the future, a database/API) and handing it to the rest of the
app as clean pandas DataFrames. UI code should never read files
directly -- it should go through :class:`DataLoader` (or the
backward-compatible ``load_sales_data`` / ``load_sample_kpis``
functions) instead.

The centerpiece is :class:`DataLoader`, a small, reusable engine that:

- Loads Excel (``.xlsx`` / ``.xls``) and CSV files via pandas, whether
  they live on disk or were just handed to the app through Streamlit's
  ``st.file_uploader`` (see :meth:`DataLoader.load_uploaded_file`).
- Automatically caches disk-based reads using Streamlit's ``st.cache_data``.
- Validates that the file exists before attempting to read it.
- Validates that required columns are present.
- Converts configured columns to proper ``datetime`` dtype.
- Fills missing values gracefully instead of leaving ``NaN`` in the UI.
- Raises meaningful, user-friendly exceptions (see
  ``utils/exceptions.py``) instead of letting raw pandas tracebacks
  bubble up to the dashboard.

:class:`DataLoader` takes its required columns / date columns / fill
values as constructor arguments, so it is not tied to the sales
dataset -- it can be reused as-is for Products, Customers, Reports, or
any future dashboard that needs to load tabular files. The
``components/upload_center.py`` UI component, for example, reuses this
same class to validate user-uploaded files.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Final

import pandas as pd
import streamlit as st

from config.settings import SAMPLE_SALES_CSV
from tenancy.context import TenantContext, validate_tenant_context
from utils.exceptions import (
    DataFileNotFoundError,
    DataReadError,
    MissingColumnsError,
    NoFileUploadedError,
    UnsupportedFileTypeError,
)
from utils.helpers import generate_sample_dataframe

if TYPE_CHECKING:
    # Imported only for type checkers -- avoids a hard runtime dependency
    # on Streamlit's internal module layout for a module that otherwise
    # only needs the public ``streamlit`` package.
    from streamlit.runtime.uploaded_file_manager import UploadedFile

# File extensions the loader knows how to read, mapped to a short kind
# label used internally to pick the right pandas reader.
_EXCEL_EXTENSIONS: Final[tuple[str, ...]] = (".xlsx", ".xls")
_CSV_EXTENSIONS: Final[tuple[str, ...]] = (".csv",)


class DataLoader:
    """Reusable, cached data-loading engine for tabular data files.

    A single ``DataLoader`` instance is configured once with the
    columns a dataset is expected to have, then reused to load one or
    more files that should conform to that shape. This keeps
    validation rules in one place and makes the class easy to drop
    into any future NovaMart page or a different dashboard entirely.

    Example:
        >>> loader = DataLoader(
        ...     required_columns=["date", "revenue", "orders"],
        ...     date_columns=["date"],
        ... )
        >>> sales_df = loader.load_excel("data/sales_report.xlsx")

    Attributes:
        required_columns: Columns that must be present in the loaded
            file, or :class:`~utils.exceptions.MissingColumnsError` is
            raised.
        date_columns: Columns to convert to ``datetime64`` dtype.
        fill_numeric: Value used to fill missing numeric cells.
        fill_text: Value used to fill missing text cells.
    """

    def __init__(
        self,
        required_columns: list[str] | tuple[str, ...] | None = None,
        date_columns: list[str] | tuple[str, ...] | None = None,
        fill_numeric: float = 0.0,
        fill_text: str = "Unknown",
    ) -> None:
        """Configure a reusable loader for a particular dataset shape.

        Args:
            required_columns: Column names that must exist in any file
                this loader reads. Pass ``None`` to skip validation.
            date_columns: Column names that should be parsed as dates.
                Pass ``None`` if the dataset has no date columns.
            fill_numeric: Value substituted for missing numeric cells
                (defaults to ``0.0``).
            fill_text: Value substituted for missing text cells
                (defaults to ``"Unknown"``).
        """
        self.required_columns: tuple[str, ...] = tuple(required_columns or ())
        self.date_columns: tuple[str, ...] = tuple(date_columns or ())
        self.fill_numeric = fill_numeric
        self.fill_text = fill_text

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def load_excel(self, file_path: str | Path, sheet_name: int | str = 0) -> pd.DataFrame:
        """Load an Excel file into a clean, validated DataFrame.

        Args:
            file_path: Path to an ``.xlsx`` or ``.xls`` file.
            sheet_name: Sheet to read, by index or name. Defaults to
                the first sheet.

        Returns:
            A cleaned pandas DataFrame: required columns validated,
            date columns converted, missing values filled.

        Raises:
            DataFileNotFoundError: If ``file_path`` does not exist.
            UnsupportedFileTypeError: If the extension isn't ``.xlsx``/``.xls``.
            MissingColumnsError: If required columns are absent.
            DataReadError: If the file exists but pandas can't parse it.
        """
        path = self._validate_file_exists(file_path)
        if path.suffix.lower() not in _EXCEL_EXTENSIONS:
            raise UnsupportedFileTypeError(path, supported=_EXCEL_EXTENSIONS)
        return _load_and_clean(
            file_path=str(path),
            file_kind="excel",
            sheet_name=sheet_name,
            required_columns=self.required_columns,
            date_columns=self.date_columns,
            fill_numeric=self.fill_numeric,
            fill_text=self.fill_text,
        )

    def load_csv(self, file_path: str | Path) -> pd.DataFrame:
        """Load a CSV file into a clean, validated DataFrame.

        Args:
            file_path: Path to a ``.csv`` file.

        Returns:
            A cleaned pandas DataFrame: required columns validated,
            date columns converted, missing values filled.

        Raises:
            DataFileNotFoundError: If ``file_path`` does not exist.
            UnsupportedFileTypeError: If the extension isn't ``.csv``.
            MissingColumnsError: If required columns are absent.
            DataReadError: If the file exists but pandas can't parse it.
        """
        path = self._validate_file_exists(file_path)
        if path.suffix.lower() not in _CSV_EXTENSIONS:
            raise UnsupportedFileTypeError(path, supported=_CSV_EXTENSIONS)
        return _load_and_clean(
            file_path=str(path),
            file_kind="csv",
            sheet_name=0,
            required_columns=self.required_columns,
            date_columns=self.date_columns,
            fill_numeric=self.fill_numeric,
            fill_text=self.fill_text,
        )

    def load(self, file_path: str | Path, sheet_name: int | str = 0) -> pd.DataFrame:
        """Load a file, auto-detecting Excel vs. CSV from its extension.

        Convenience wrapper around :meth:`load_excel` / :meth:`load_csv`
        for callers that accept either format interchangeably.

        Args:
            file_path: Path to an ``.xlsx``, ``.xls``, or ``.csv`` file.
            sheet_name: Sheet to read if the file is an Excel workbook.
                Ignored for CSV files.

        Returns:
            A cleaned pandas DataFrame.

        Raises:
            DataFileNotFoundError: If ``file_path`` does not exist.
            UnsupportedFileTypeError: If the extension isn't supported.
            MissingColumnsError: If required columns are absent.
            DataReadError: If the file exists but pandas can't parse it.
        """
        path = self._validate_file_exists(file_path)
        suffix = path.suffix.lower()
        if suffix in _EXCEL_EXTENSIONS:
            return self.load_excel(path, sheet_name=sheet_name)
        if suffix in _CSV_EXTENSIONS:
            return self.load_csv(path)
        raise UnsupportedFileTypeError(path, supported=_EXCEL_EXTENSIONS + _CSV_EXTENSIONS)

    def load_uploaded_file(
        self,
        uploaded_file: "UploadedFile | None",
        sheet_name: int | str = 0,
        *,
        tenant_context: TenantContext | None = None,
    ) -> pd.DataFrame:
        """Load a file uploaded through Streamlit's ``st.file_uploader``.

        This is the method UI components (such as the Upload Center)
        should call. Unlike :meth:`load_excel` / :meth:`load_csv`, it
        reads directly from the in-memory buffer Streamlit provides --
        no filesystem path is involved -- so it deliberately is *not*
        wrapped in ``st.cache_data``: uploaded-file objects are
        recreated by Streamlit on every upload (even for a re-upload of
        a same-named file), so there is nothing stable to key a cache
        on, and skipping the cache avoids ever showing stale data from
        a previous upload. This also means there is no shared cache for
        tenant data to ever leak through.

        This is the entry point to the tenant-aware pipeline (Upload
        Center -> Data Loader -> ...), so ``tenant_context`` is
        validated here, before any file is read (Multi-Tenant Sprint
        6.3, Task 4): every uploaded-file load is now attributable to a
        specific, active tenant.

        Args:
            uploaded_file: The object returned by ``st.file_uploader``,
                or ``None`` if the user hasn't uploaded anything yet.
            sheet_name: Sheet to read if the upload is an Excel
                workbook. Ignored for CSV uploads.
            tenant_context: The tenant this upload belongs to. Required
                for the call to succeed; kept keyword-only and optional
                in the signature (default ``None``) so this remains
                callable exactly as before syntactically -- omitting it
                now raises :class:`~tenancy.exceptions.MissingTenantContextError`
                instead of silently proceeding.

        Returns:
            A cleaned, validated pandas DataFrame.

        Raises:
            NoFileUploadedError: If ``uploaded_file`` is ``None``.
            UnsupportedFileTypeError: If the extension isn't supported.
            MissingColumnsError: If required columns are absent.
            DataReadError: If the file can't be parsed.
            MissingTenantContextError: If no tenant context was supplied.
            InactiveTenantError: If the supplied tenant is not active.
        """
        validate_tenant_context(tenant_context, service_name="DataLoader", operation="load_uploaded_file")

        if uploaded_file is None:
            raise NoFileUploadedError()

        filename = getattr(uploaded_file, "name", "uploaded_file")
        suffix = Path(filename).suffix.lower()

        try:
            if suffix in _EXCEL_EXTENSIONS:
                df = pd.read_excel(uploaded_file, sheet_name=sheet_name)
            elif suffix in _CSV_EXTENSIONS:
                df = pd.read_csv(uploaded_file)
            else:
                raise UnsupportedFileTypeError(filename, supported=_EXCEL_EXTENSIONS + _CSV_EXTENSIONS)
        except UnsupportedFileTypeError:
            raise
        except Exception as exc:  # noqa: BLE001 - re-raised as a domain exception below
            raise DataReadError(filename, exc) from exc

        if isinstance(df, dict):
            raise DataReadError(filename, ValueError("Multiple sheets were returned; specify a single sheet_name."))

        return self._finalize(
            df,
            required_columns=self.required_columns,
            date_columns=self.date_columns,
            fill_numeric=self.fill_numeric,
            fill_text=self.fill_text,
            source=filename,
        )

    # ------------------------------------------------------------------
    # Internal helpers (shared with the module-level cached loader below)
    # ------------------------------------------------------------------
    @staticmethod
    def _validate_file_exists(file_path: str | Path) -> Path:
        """Ensure ``file_path`` exists and is a file.

        Args:
            file_path: The path to check.

        Returns:
            The path, normalized to a :class:`~pathlib.Path`.

        Raises:
            DataFileNotFoundError: If the path is missing or not a file.
        """
        path = Path(file_path)
        if not path.exists() or not path.is_file():
            raise DataFileNotFoundError(path)
        return path

    @staticmethod
    def _validate_required_columns(
        df: pd.DataFrame, required_columns: tuple[str, ...], source: str | Path
    ) -> None:
        """Ensure every column in ``required_columns`` is present.

        Args:
            df: The freshly loaded DataFrame.
            required_columns: Columns that must be present.
            source: The file path, used for the error message.

        Raises:
            MissingColumnsError: If any required column is absent.
        """
        missing = [col for col in required_columns if col not in df.columns]
        if missing:
            raise MissingColumnsError(missing, source)

    @staticmethod
    def _convert_date_columns(df: pd.DataFrame, date_columns: tuple[str, ...]) -> pd.DataFrame:
        """Convert configured columns to ``datetime64`` dtype.

        Unparseable values become ``NaT`` rather than raising, so a few
        malformed rows don't take down the whole page.

        Args:
            df: The DataFrame to convert (not mutated in place).
            date_columns: Columns to parse as dates.

        Returns:
            A new DataFrame with date columns converted.
        """
        df = df.copy()
        for column in date_columns:
            if column in df.columns:
                df[column] = pd.to_datetime(df[column], errors="coerce")
        return df

    @staticmethod
    def _handle_missing_values(df: pd.DataFrame, fill_numeric: float, fill_text: str) -> pd.DataFrame:
        """Fill missing values so downstream code never sees raw ``NaN``.

        Numeric columns are filled with ``fill_numeric`` and text
        (object-dtype) columns are filled with ``fill_text``. Text
        values are also stripped of surrounding whitespace.

        Date columns are intentionally left untouched here: a missing
        or unparseable date becomes ``NaT`` in ``_convert_date_columns``
        and is preserved as such, since fabricating a fake date would
        be misleading. Callers that need date gaps filled should do so
        explicitly with domain knowledge of what a sensible default is.

        Args:
            df: The DataFrame to clean (not mutated in place).
            fill_numeric: Fill value for numeric columns.
            fill_text: Fill value for text columns.

        Returns:
            A new DataFrame with missing values handled.
        """
        df = df.copy()

        numeric_columns = df.select_dtypes(include="number").columns
        if len(numeric_columns) > 0:
            df[numeric_columns] = df[numeric_columns].fillna(fill_numeric)

        text_columns = df.select_dtypes(include="object").columns
        for column in text_columns:
            df[column] = df[column].fillna(fill_text)
            df[column] = df[column].apply(lambda value: value.strip() if isinstance(value, str) else value)

        return df

    @staticmethod
    def _finalize(
        df: pd.DataFrame,
        required_columns: tuple[str, ...],
        date_columns: tuple[str, ...],
        fill_numeric: float,
        fill_text: str,
        source: str | Path,
    ) -> pd.DataFrame:
        """Run the shared validate-and-clean pipeline on a freshly read DataFrame.

        Shared by the disk-based cached loader below and by
        :meth:`load_uploaded_file`, so both paths apply identical
        column normalization, validation, date conversion, and
        missing-value handling.

        Args:
            df: The raw DataFrame just returned by pandas.
            required_columns: Columns that must be present.
            date_columns: Columns to convert to datetime.
            fill_numeric: Fill value for missing numeric cells.
            fill_text: Fill value for missing text cells.
            source: File path or filename, used in error messages.

        Returns:
            A clean, validated DataFrame with a reset index.

        Raises:
            MissingColumnsError: If required columns are absent.
        """
        df = df.copy()
        # Normalize column names (strip stray whitespace from headers).
        df.columns = [str(col).strip() for col in df.columns]

        DataLoader._validate_required_columns(df, required_columns, source)
        df = DataLoader._convert_date_columns(df, date_columns)
        df = DataLoader._handle_missing_values(df, fill_numeric, fill_text)

        return df.reset_index(drop=True)


# --------------------------------------------------------------------------
# Module-level cached read function
# --------------------------------------------------------------------------
# Kept as a free function (rather than a method) so every argument is a
# plain, hashable value. Streamlit's cache_data hashes all arguments to
# build its cache key; hashing an arbitrary DataLoader instance would be
# unreliable, whereas hashing str/int/tuple/float values here is fast
# and correct -- and it means two DataLoader instances configured
# differently for the same file path never collide in the cache.
@st.cache_data(show_spinner="Loading data...")
def _load_and_clean(
    file_path: str,
    file_kind: str,
    sheet_name: int | str,
    required_columns: tuple[str, ...],
    date_columns: tuple[str, ...],
    fill_numeric: float,
    fill_text: str,
) -> pd.DataFrame:
    """Read, validate, and clean a data file. Cached by Streamlit.

    Args:
        file_path: Absolute path to the file, as a string.
        file_kind: Either ``"excel"`` or ``"csv"``.
        sheet_name: Sheet index/name (Excel only).
        required_columns: Columns that must be present.
        date_columns: Columns to convert to datetime.
        fill_numeric: Fill value for missing numeric cells.
        fill_text: Fill value for missing text cells.

    Returns:
        A clean, validated pandas DataFrame.

    Raises:
        DataReadError: If pandas cannot parse the file.
        MissingColumnsError: If required columns are absent.
    """
    path = Path(file_path)

    try:
        if file_kind == "excel":
            df = pd.read_excel(path, sheet_name=sheet_name)
        else:
            df = pd.read_csv(path)
    except Exception as exc:  # noqa: BLE001 - re-raised as a domain exception below
        raise DataReadError(path, exc) from exc

    if isinstance(df, dict):
        # A dict is returned when sheet_name selects multiple sheets at
        # once (e.g. sheet_name=None). This loader guarantees a single
        # DataFrame, so surface a clear error instead of silently
        # returning the wrong shape.
        raise DataReadError(path, ValueError("Multiple sheets were returned; specify a single sheet_name."))

    return DataLoader._finalize(
        df,
        required_columns=required_columns,
        date_columns=date_columns,
        fill_numeric=fill_numeric,
        fill_text=fill_text,
        source=path,
    )


# --------------------------------------------------------------------------
# Backward-compatible functions (existing dashboard relies on these)
# --------------------------------------------------------------------------
# A shared DataLoader configured for the sales dataset shape. Reused by
# load_sales_data() below and available for any other module that needs
# to load a sales-shaped file with the same validation rules.
sales_data_loader = DataLoader(
    required_columns=["date", "revenue", "orders"],
    date_columns=["date"],
    fill_numeric=0.0,
    fill_text="Unknown",
)


@st.cache_data(show_spinner=False)
def load_sales_data() -> pd.DataFrame:
    """Load the core sales dataset used across the dashboard.

    Preserved for backward compatibility with ``app.py`` and existing
    pages. Internally this now runs through :class:`DataLoader`, so it
    gains column validation, date parsing, and missing-value handling
    "for free". If the bundled sample CSV doesn't exist yet, it falls
    back to a generated in-memory sample -- exactly as before -- so the
    app keeps running before a real dataset is added to ``data/``.

    Returns:
        A DataFrame with ``date``, ``revenue``, and ``orders`` columns.
    """
    try:
        return sales_data_loader.load_csv(SAMPLE_SALES_CSV)
    except DataFileNotFoundError:
        return generate_sample_dataframe()


@st.cache_data(show_spinner=False)
def load_sample_kpis() -> dict[str, float]:
    """Load placeholder KPI values for the home page.

    In a production build this would query a warehouse or API. For now
    it derives simple placeholder figures from the sample sales data so
    the home page has realistic-looking numbers.

    Returns:
        A dictionary of raw KPI figures keyed by metric name.
    """
    df = load_sales_data()
    return {
        "total_revenue": float(df["revenue"].sum()) if not df.empty else 0.0,
        "total_orders": int(df["orders"].sum()) if not df.empty else 0,
        "active_customers": 1240,  # Placeholder until a customers table exists.
    }
