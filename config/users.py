"""User directory configuration for the NovaMart Permission-Based
Authorization Framework.

Sprint 6.5 -- Permission-Based Authorization Framework.

This is the *only* place a demo user is declared. Onboarding a new
user -- or changing an existing one's roles or status -- means adding
or editing one :class:`~authorization.models.User` entry in
:data:`USER_DEFINITIONS` below. No other file in the codebase branches
on a user id (no ``if user_id == "jane.doe":`` anywhere), mirroring
exactly how ``config/tenants.py`` is the single configuration surface
for onboarding a tenant.

There is no real authentication in this release -- the Target
Architecture in ``docs/AUTHORIZATION_ARCHITECTURE.md`` explicitly marks
"Authentication" as a future integration point. Until then, this file
seeds a small demo directory covering all four default roles (System
Administrator, Tenant Administrator, Business Analyst, Executive
Viewer) across the tenants already declared in ``config/tenants.py``,
and ``components/authorization.py`` lets the person running the demo
pick "who they currently are" from this directory via a sidebar
switcher -- the same stand-in role ``components/tenant_selector.py``
already plays for "which organization is active" in the absence of
real multi-tenant request routing.

In a future iteration, :data:`USER_DEFINITIONS` could just as easily be
replaced by a database-, LDAP-, or OAuth/OIDC/Azure AD/Okta/Auth0-backed
:class:`~authorization.provider.AuthorizationProvider` instead of a
Python literal -- nothing outside this module needs to change either
way, since every consumer only ever calls
``authorization.service.authorization_service.resolve_user(...)`` /
``.build_context(...)``, never reads this list directly.
"""

from __future__ import annotations

from authorization.models import User, UserStatus
from authorization.registry import authorization_provider_registry
from authorization.roles import BUSINESS_ANALYST, EXECUTIVE_VIEWER, SYSTEM_ADMINISTRATOR, TENANT_ADMINISTRATOR

# --------------------------------------------------------------------------
# User declarations -- add/edit an entry here to onboard, re-role, or
# deactivate a demo user. Never add conditional logic elsewhere.
# --------------------------------------------------------------------------
USER_DEFINITIONS: tuple[User, ...] = (
    User(
        user_id="system.admin",
        username="system.admin",
        display_name="Sam Carter (System Administrator)",
        email="system.admin@novamart.example",
        tenant_id="novamart-hq",
        roles=(SYSTEM_ADMINISTRATOR,),
        status=UserStatus.ACTIVE,
        metadata={"title": "Platform Administrator"},
    ),
    User(
        user_id="tenant.admin",
        username="tenant.admin",
        display_name="Priya Nair (Tenant Administrator)",
        email="tenant.admin@acme-retail.example",
        tenant_id="acme-retail",
        roles=(TENANT_ADMINISTRATOR,),
        status=UserStatus.ACTIVE,
        metadata={"title": "IT Administrator"},
    ),
    User(
        user_id="business.analyst",
        username="business.analyst",
        display_name="Marcus Lee (Business Analyst)",
        email="business.analyst@acme-retail.example",
        tenant_id="acme-retail",
        roles=(BUSINESS_ANALYST,),
        status=UserStatus.ACTIVE,
        metadata={"title": "Senior Business Analyst"},
    ),
    User(
        user_id="executive.viewer",
        username="executive.viewer",
        display_name="Dana Whitfield (Executive Viewer)",
        email="executive.viewer@acme-retail.example",
        tenant_id="acme-retail",
        roles=(EXECUTIVE_VIEWER,),
        status=UserStatus.ACTIVE,
        metadata={"title": "Chief Operating Officer"},
    ),
    User(
        user_id="inactive.user",
        username="inactive.user",
        display_name="Former Employee (Inactive)",
        email="inactive.user@acme-retail.example",
        tenant_id="acme-retail",
        roles=(BUSINESS_ANALYST,),
        status=UserStatus.INACTIVE,
        metadata={"title": "Former Business Analyst"},
    ),
)


def register_default_users() -> None:
    """Register every user declared in :data:`USER_DEFINITIONS`.

    Registers into whichever :class:`~authorization.provider.AuthorizationProvider`
    is currently active in
    :data:`~authorization.registry.authorization_provider_registry` --
    the default in-memory provider for this release. Called once,
    below, at import time -- mirroring
    ``config.tenants.register_default_tenants()``. Any module that
    needs the user directory populated should ``import config.users``
    (even if only for its side effect) before resolving a user.

    Local, config-driven seeding like this is meaningful only for a
    provider that stores users itself (e.g.
    :class:`~authorization.provider.InMemoryAuthorizationProvider`,
    or a future database-backed provider with an admin-facing
    "register" operation). A future *external* identity provider (LDAP,
    OAuth, OpenID Connect, Azure AD, Okta, Auth0) manages its own user
    directory and would never be seeded this way -- ``get_user``/
    ``list_users`` alone are enough for
    :class:`~authorization.service.AuthorizationService` to work
    against it. This function is therefore a no-op (with a log line,
    not a crash) against any active provider that doesn't expose a
    ``register_many``, since that simply means "this provider's users
    come from elsewhere."
    """
    import logging

    provider = authorization_provider_registry.get_active()
    register_many = getattr(provider, "register_many", None)
    if register_many is None:
        logging.getLogger("novamart.authorization").info(
            "Active authorization provider does not support local seeding; "
            "config/users.py's USER_DEFINITIONS were not registered."
        )
        return
    register_many(USER_DEFINITIONS)


register_default_users()
