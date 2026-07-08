"""Demo identity/credential configuration for the NovaMart Identity &
Authentication Framework.

Sprint 6.6 -- Identity & Authentication Framework, Task 4.

This is the *only* file in the codebase that imports from both
``authorization`` and ``identity``. That is deliberate, not an
oversight: "Authentication must remain completely separated from
Authorization" (this sprint's explicit requirement) means
``identity/`` itself must never import ``authorization`` (and it
doesn't -- see ``identity/models.py``'s docstring). But Task 4 also
asks the demo authentication provider to reuse "the existing demo
users" from Sprint 6.5, rather than maintaining a second, disconnected
directory of names/emails/tenants. Reconciling both requirements means
exactly one config-layer module is allowed to know about both
packages' shapes, project ``authorization.models.User`` records into
``identity.models.UserIdentity`` records, and hand the result to the
identity package as plain data -- ``identity/service.py`` and
``identity/provider.py`` never see an ``authorization.models.User``,
only the ``UserIdentity`` this module builds from one.

This mirrors exactly how ``config/users.py`` is already the one place
that knows both ``authorization.models`` and ``tenancy``'s tenant ids
(a ``User.tenant_id`` is a plain string reference, not an import of
``tenancy.models.Tenant``) -- ``config/`` is this codebase's
composition root for demo data, not ``authorization/`` or
``identity/`` themselves.

Demo passwords, not production ones
----------------------------------------
Every demo identity shares the same password below. There is no
password hashing, no per-user complexity requirement, and no password
reset flow -- exactly what the ticket's Task 7 asks for ("Do not
implement password encryption... Use demo users only. The objective is
architecture, not production security."). A future
``DatabaseAuthenticationProvider`` (see ``identity/provider.py``) is
where real, salted password hashing would be introduced, entirely
behind the existing :class:`~identity.provider.AuthenticationProvider`
interface.
"""

from __future__ import annotations

import logging

from authorization.models import User
from config.users import USER_DEFINITIONS
from identity.models import IdentityStatus, UserIdentity
from identity.registry import authentication_provider_registry

# --------------------------------------------------------------------------
# The shared demo password for every seeded identity. Displayed directly on
# the login screen (components/auth.py) since there is no other way for
# someone running the demo to discover it -- this is a showcase app, not a
# production deployment; see the module docstring.
# --------------------------------------------------------------------------
DEMO_PASSWORD = "novamart123"


def _to_identity(user: User) -> UserIdentity:
    """Project one ``authorization.models.User`` into an ``identity.models.UserIdentity``.

    A pure, one-directional data projection -- identical field values,
    different (unrelated) types and a separate status enum, per
    ``identity/models.py``'s "Deliberately independent of
    authorization.models" section.

    Args:
        user: The Sprint 6.5 demo user record to project.

    Returns:
        The equivalent :class:`~identity.models.UserIdentity`.
    """
    status = IdentityStatus.ACTIVE if user.is_active else IdentityStatus.INACTIVE
    return UserIdentity(
        user_id=user.user_id,
        username=user.username,
        display_name=user.display_name,
        email=user.email,
        tenant_id=user.tenant_id,
        status=status,
        metadata=dict(user.metadata),
    )


# --------------------------------------------------------------------------
# Every demo user from config/users.py, projected into an identity + given
# the shared demo password. Add/edit a user in config/users.py to onboard,
# re-role, or deactivate someone for *both* authentication and
# authorization -- never add a second, separate declaration here.
# --------------------------------------------------------------------------
CREDENTIAL_DEFINITIONS: tuple[tuple[UserIdentity, str], ...] = tuple(
    (_to_identity(user), DEMO_PASSWORD) for user in USER_DEFINITIONS
)


def register_default_credentials() -> None:
    """Register every identity/password pair declared in :data:`CREDENTIAL_DEFINITIONS`.

    Registers into whichever :class:`~identity.provider.AuthenticationProvider`
    is currently active in
    :data:`~identity.registry.authentication_provider_registry` -- the
    default in-memory provider for this release. Called once, below,
    at import time -- mirroring ``config.users.register_default_users()``.
    Any module that needs the identity directory populated should
    ``import config.credentials`` (even if only for its side effect)
    before authenticating a user.

    Like ``config.users.register_default_users()``, this is a no-op
    (with a log line, not a crash) against any active provider that
    doesn't expose a ``register_many`` method, since a future *external*
    identity provider (LDAP, OAuth, OpenID Connect, Entra ID, Google
    Identity, Okta, Auth0) manages its own credential store and would
    never be seeded this way.
    """
    provider = authentication_provider_registry.get_active()
    register_many = getattr(provider, "register_many", None)
    if register_many is None:
        logging.getLogger("novamart.identity").info(
            "Active authentication provider does not support local seeding; "
            "config/credentials.py's CREDENTIAL_DEFINITIONS were not registered."
        )
        return
    register_many(CREDENTIAL_DEFINITIONS)


register_default_credentials()
