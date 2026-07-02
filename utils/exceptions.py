"""Custom exception hierarchy for NovaMart's data-loading engine.

Centralizing exceptions here -- rather than raising generic
``ValueError`` / ``FileNotFoundError`` all over the codebase -- lets
calling code catch a single, predictable base type
(:class:`DataLoaderError`) and lets the UI layer show clear,
user-friendly messages instead of raw Python tracebacks.

This module has no Streamlit or pandas dependency, so it can be reused
by any future data-loading code (not just ``utils/data_loader.py``).
"""

from __future__ import annotations

from pathlib import Path


class DataLoaderError(Exception):
    """Base class for every error raised by the data-loading engine.

    Catch this type in UI code to handle *any* data-loading failure
    (missing file, unsupported type, bad columns, unreadable file)
    with a single ``except`` clause, e.g.::

        try:
            df = loader.load_excel("sales.xlsx")
        except DataLoaderError as exc:
            st.error(str(exc))
    """


class DataFileNotFoundError(DataLoaderError):
    """Raised when a requested data file does not exist on disk."""

    def __init__(self, file_path: Path | str) -> None:
        """Build a user-friendly "file not found" message.

        Args:
            file_path: The path that was expected to exist.
        """
        self.file_path = Path(file_path)
        message = (
            f"We couldn't find the data file '{self.file_path.name}'. "
            f"Expected it at: {self.file_path}. "
            "Please check that the file exists and the path is correct."
        )
        super().__init__(message)


class UnsupportedFileTypeError(DataLoaderError):
    """Raised when a file's extension isn't supported by the loader."""

    def __init__(self, file_path: Path | str, supported: tuple[str, ...] = (".xlsx", ".xls", ".csv")) -> None:
        """Build a user-friendly "unsupported file type" message.

        Args:
            file_path: The path whose extension is unsupported.
            supported: The file extensions the loader does support.
        """
        self.file_path = Path(file_path)
        supported_list = ", ".join(supported)
        message = (
            f"'{self.file_path.name}' has an unsupported file type "
            f"('{self.file_path.suffix or 'unknown'}'). "
            f"Supported types are: {supported_list}."
        )
        super().__init__(message)


class MissingColumnsError(DataLoaderError):
    """Raised when one or more required columns are missing."""

    def __init__(self, missing_columns: list[str], file_path: Path | str) -> None:
        """Build a user-friendly "missing columns" message.

        Args:
            missing_columns: The required columns that were not found.
            file_path: The file that was loaded.
        """
        self.missing_columns = list(missing_columns)
        self.file_path = Path(file_path)
        columns_list = ", ".join(f"'{c}'" for c in self.missing_columns)
        message = (
            f"'{self.file_path.name}' is missing required column(s): {columns_list}. "
            "Please check that the file matches the expected format."
        )
        super().__init__(message)


class NoFileUploadedError(DataLoaderError):
    """Raised by upload-driven workflows when no file has been provided.

    Kept distinct from :class:`DataFileNotFoundError`, which is about a
    filesystem path that should exist but doesn't. This one covers the
    "the user hasn't uploaded anything yet" case for components like
    the Upload Center.
    """

    def __init__(self, message: str = "Please upload a CSV or Excel file to continue.") -> None:
        """Build a friendly "nothing uploaded yet" message.

        Args:
            message: Override the default user-facing message.
        """
        super().__init__(message)


class DataReadError(DataLoaderError):
    """Raised when a file exists but pandas is unable to parse it."""

    def __init__(self, file_path: Path | str, original_error: Exception) -> None:
        """Build a user-friendly "couldn't read file" message.

        Args:
            file_path: The file that failed to parse.
            original_error: The underlying exception raised by pandas.
        """
        self.file_path = Path(file_path)
        self.original_error = original_error
        message = (
            f"We found '{self.file_path.name}' but couldn't read it "
            f"({original_error.__class__.__name__}: {original_error}). "
            "The file may be corrupted, password-protected, or in an "
            "unexpected format."
        )
        super().__init__(message)
