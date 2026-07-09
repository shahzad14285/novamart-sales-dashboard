"""Configuration Provider abstraction for the NovaMart Production Platform.

Sprint 6.9 -- Production Readiness Platform, Task 3.

A **configuration provider** is a thin backend adapter that supplies
raw string values for configuration keys -- a structural ``Protocol``,
mirroring every other provider interface in this platform
(``identity.provider.AuthenticationProvider``,
``monitoring.provider.MonitoringProvider``,
``notification.provider.NotificationProvider``,
``integration.provider.IntegrationProvider``). :class:`~configuration.service.ConfigurationService`
depends only on this interface, never on a concrete backend, which is
what "Configuration Service must remain provider-independent" (Task 3)
means concretely: swapping which provider is active is one
:meth:`~configuration.registry.ConfigurationProviderRegistry.set_active`
call, never a code change to :class:`~configuration.service.ConfigurationService`.

This sprint ships two providers:

- :class:`InMemoryConfigurationProvider` -- a plain, mutable dict of
  key/value pairs. Sufficient for local development, tests, and to
  seed sensible defaults every deployment starts from.
- :class:`EnvironmentVariableConfigurationProvider` -- reads from
  ``os.environ``, the standard way a containerized/cloud deployment
  injects configuration and secrets without ever committing them to
  source control ("Avoid ... Secrets inside source code").

Future providers -- Azure Key Vault, AWS Secrets Manager, Google Secret
Manager, HashiCorp Vault, or a database-backed configuration store --
are added by writing one new class that satisfies
:class:`ConfigurationProvider` and registering it via
:meth:`~configuration.registry.ConfigurationProviderRegistry.register`.
Nothing in :class:`~configuration.service.ConfigurationService` needs
to change.
"""

from __future__ import annotations

import os
import threading
from typing import Mapping, Protocol, runtime_checkable


@runtime_checkable
class ConfigurationProvider(Protocol):
    """Interface every configuration backend must satisfy.

    A structural ``Protocol``, so a class satisfies this interface
    simply by having a compatible ``name`` property and ``get``/
    ``as_dict`` methods -- no inheritance required.
    """

    @property
    def name(self) -> str:
        """A short, human-readable name for this provider (for traceability)."""
        ...

    def get(self, key: str) -> str | None:
        """Return the raw string value for ``key``, or ``None`` if this provider doesn't have it.

        Args:
            key: The configuration key to look up.

        Returns:
            The raw value as a string, or ``None``. Providers never
            raise for a missing key -- "not found" is a normal,
            expected outcome the caller (``ConfigurationService``)
            handles by trying the next provider or falling back to a
            default.
        """
        ...

    def as_dict(self) -> Mapping[str, str]:
        """Return every key/value pair this provider currently holds.

        Used by the Operations Dashboard's "Configuration summary"
        section. A future secrets-manager-backed provider should
        redact or omit sensitive values here rather than exposing them
        verbatim -- see ``docs/PRODUCTION_ARCHITECTURE.md``'s Secrets
        Strategy section.
        """
        ...


class InMemoryConfigurationProvider:
    """A plain, mutable, in-process configuration store.

    Sufficient for local development, tests, and for seeding the
    sensible defaults every deployment starts from before any
    environment-specific override is applied. Thread-safe (guarded by
    a simple lock), mirroring every other in-memory provider in this
    platform.

    Example:
        >>> provider = InMemoryConfigurationProvider({"APP_NAME": "NovaMart"})
        >>> provider.get("APP_NAME")
        'NovaMart'
        >>> provider.get("MISSING_KEY") is None
        True
    """

    def __init__(self, initial: Mapping[str, str] | None = None, *, name: str = "in-memory") -> None:
        """Create an in-memory configuration provider.

        Args:
            initial: Starting key/value pairs, if any.
            name: A short, human-readable name for this provider
                instance (useful when more than one in-memory provider
                is registered, e.g. one for test fixtures and one for
                application defaults).
        """
        self._name = name
        self._values: dict[str, str] = dict(initial) if initial else {}
        self._lock = threading.Lock()

    @property
    def name(self) -> str:
        """This provider's name."""
        return self._name

    def get(self, key: str) -> str | None:
        """Return the value for ``key``, or ``None`` if not set."""
        with self._lock:
            return self._values.get(key)

    def set(self, key: str, value: str) -> None:
        """Set (or replace) the value for ``key``.

        Args:
            key: The configuration key to set.
            value: The value to store.
        """
        with self._lock:
            self._values[key] = value

    def set_many(self, values: Mapping[str, str]) -> None:
        """Set (or replace) every key/value pair in ``values``."""
        with self._lock:
            self._values.update(values)

    def as_dict(self) -> Mapping[str, str]:
        """Return every key/value pair currently stored."""
        with self._lock:
            return dict(self._values)

    def clear(self) -> None:
        """Remove every stored key/value pair.

        Primarily useful for tests that need a clean provider rather
        than one accumulating values across an entire test run.
        """
        with self._lock:
            self._values.clear()


class EnvironmentVariableConfigurationProvider:
    """Reads configuration values from ``os.environ`` (Task 3).

    The standard way a containerized or cloud deployment injects
    configuration and secrets at runtime without ever committing them
    to source control. An optional ``prefix`` scopes which environment
    variables this provider considers "its own" (e.g. only
    ``NOVAMART_*`` variables), so a shared hosting environment's
    unrelated environment variables never leak into NovaMart's
    configuration surface.

    Example:
        >>> import os
        >>> os.environ["NOVAMART_APP_NAME"] = "NovaMart Prod"
        >>> provider = EnvironmentVariableConfigurationProvider(prefix="NOVAMART_")
        >>> provider.get("APP_NAME")
        'NovaMart Prod'
    """

    def __init__(self, *, prefix: str = "", name: str = "environment") -> None:
        """Create an environment-variable-backed configuration provider.

        Args:
            prefix: If given, only environment variables starting with
                this prefix are considered, and the prefix is stripped
                from the key when looked up (e.g. with
                ``prefix="NOVAMART_"``, ``get("APP_NAME")`` reads
                ``os.environ["NOVAMART_APP_NAME"]``).
            name: A short, human-readable name for this provider
                instance.
        """
        self._prefix = prefix
        self._name = name

    @property
    def name(self) -> str:
        """This provider's name."""
        return self._name

    def get(self, key: str) -> str | None:
        """Return the environment variable value for ``key`` (with ``prefix`` applied), or ``None``."""
        return os.environ.get(f"{self._prefix}{key}")

    def as_dict(self) -> Mapping[str, str]:
        """Return every environment variable matching ``prefix``, with the prefix stripped from each key."""
        if not self._prefix:
            return dict(os.environ)
        return {key[len(self._prefix):]: value for key, value in os.environ.items() if key.startswith(self._prefix)}
