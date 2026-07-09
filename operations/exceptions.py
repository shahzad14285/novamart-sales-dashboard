"""Exceptions for the NovaMart Production Platform's Operations package.

Sprint 6.9 -- Production Readiness Platform, Task 6, Task 7.

Mirrors the exception-hierarchy convention already used throughout this
codebase: one base class every operations-related failure inherits
from, plus a small, specific subclass per distinct failure mode.
"""

from __future__ import annotations


class OperationsError(Exception):
    """Base class for every exception this package raises."""


class DuplicateHealthCheckError(OperationsError):
    """Raised when a health check is registered twice under the same component name."""

    def __init__(self, component: str) -> None:
        self.component = component
        super().__init__(f"A health check is already registered for component '{component}'.")


class UnknownComponentError(OperationsError):
    """Raised when a health check is requested for a component with no registered check."""

    def __init__(self, component: str, registered: tuple[str, ...]) -> None:
        self.component = component
        self.registered = registered
        known = ", ".join(registered) if registered else "none"
        super().__init__(f"No health check is registered for component '{component}'. Registered components: {known}.")


class DuplicateReadinessCheckError(OperationsError):
    """Raised when a readiness check is registered twice under the same name."""

    def __init__(self, check_name: str) -> None:
        self.check_name = check_name
        super().__init__(f"A readiness check is already registered under the name '{check_name}'.")
