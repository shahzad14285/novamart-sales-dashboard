"""Exceptions for the NovaMart Production Platform's Configuration package.

Sprint 6.9 -- Production Readiness Platform, Task 1.

Mirrors the exception-hierarchy convention already used throughout this
codebase (``integration.exceptions``, ``automation.exceptions``,
``identity.exceptions``): one base class every configuration-related
failure inherits from, plus a small, specific subclass per distinct
failure mode -- callers can catch broadly (``except ConfigurationError``)
or narrowly, and every message is business-friendly by construction.
"""

from __future__ import annotations


class ConfigurationError(Exception):
    """Base class for every exception this package raises."""


class ProviderNotRegisteredError(ConfigurationError):
    """Raised when a configuration provider name has no registered provider."""

    def __init__(self, name: str, registered: tuple[str, ...]) -> None:
        self.name = name
        self.registered = registered
        known = ", ".join(registered) if registered else "none"
        super().__init__(f"No configuration provider is registered under '{name}'. Registered providers: {known}.")


class NoActiveProviderError(ConfigurationError):
    """Raised when a configuration lookup is attempted before any provider has been registered."""

    def __init__(self) -> None:
        super().__init__("No configuration provider is currently active. Register at least one provider first.")


class UnknownEnvironmentError(ConfigurationError):
    """Raised when a string doesn't match any known :class:`~configuration.models.Environment` member."""

    def __init__(self, value: str, known: tuple[str, ...]) -> None:
        self.value = value
        self.known = known
        super().__init__(f"'{value}' is not a known environment. Known environments: {', '.join(known)}.")


class MissingConfigurationKeyError(ConfigurationError):
    """Raised when a required configuration key has no resolvable value (used by Readiness checks)."""

    def __init__(self, key: str) -> None:
        self.key = key
        super().__init__(f"Required configuration key '{key}' is not set.")


class UnknownFeatureFlagError(ConfigurationError):
    """Raised when a feature flag key isn't registered in the Feature Flag Registry."""

    def __init__(self, key: str, known: tuple[str, ...]) -> None:
        self.key = key
        self.known = known
        known_str = ", ".join(known) if known else "none"
        super().__init__(f"'{key}' is not a registered feature flag. Registered flags: {known_str}.")
