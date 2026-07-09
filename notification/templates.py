"""Template Registry for the NovaMart Automation & Notification Platform.

Sprint 6.7 -- Automation & Notification Platform, Task 6.

A :class:`~notification.models.NotificationTemplate` is a named,
reusable subject/body pair with ``{placeholder}`` slots, rendered
against a plain ``dict`` context at send time. Templates are registered
into a :class:`TemplateRegistry` (mirroring
``authorization.permissions.PermissionRegistry`` and
``authorization.roles.RoleRegistry``) rather than hard-coded inside
:class:`~notification.service.NotificationService`, so a brand-new
event type gets its own notification wording via one
:meth:`TemplateRegistry.register` call, never a change to the service
itself.
"""

from __future__ import annotations

from notification.exceptions import UnknownTemplateError
from notification.models import NotificationTemplate

# Template keys mirror automation.models.EventType values exactly
# (``"event.<event_type>"``), which is what lets
# NotificationService.handle_event() pick a template automatically --
# see notification/service.py.
_TEMPLATE_KEY_PREFIX = "event."


def template_key_for_event_type(event_type: str) -> str:
    """Build the default template key for a given automation event type.

    Args:
        event_type: An ``automation.models.EventType`` value (or any
            other event type string).

    Returns:
        The corresponding template key, e.g.
        ``"event.report_generated"``.
    """
    return f"{_TEMPLATE_KEY_PREFIX}{event_type}"


class SafeFormatDict(dict):
    """A ``dict`` that renders a missing placeholder as ``{key}`` instead of raising.

    Used with ``str.format_map`` so a template referencing a context
    key a particular event's payload didn't happen to include degrades
    gracefully (the literal placeholder text shows up instead of the
    whole render raising ``KeyError``) rather than turning a
    notification failure into a delivery failure.
    """

    def __missing__(self, key: str) -> str:
        return f"{{{key}}}"


class TemplateRegistry:
    """A registry of every notification template known to the platform.

    Example:
        >>> registry = TemplateRegistry()
        >>> registry.register(NotificationTemplate("event.report_generated", "Report ready", "Your {report_type} report is ready."))
        >>> subject, body = registry.render("event.report_generated", {"report_type": "executive"})
        >>> body
        'Your executive report is ready.'
    """

    def __init__(self) -> None:
        """Create an empty template registry."""
        self._templates: dict[str, NotificationTemplate] = {}

    def register(self, template: NotificationTemplate) -> None:
        """Register (or replace) a template under its ``template_key``.

        Args:
            template: The template to register.
        """
        self._templates[template.template_key] = template

    def get(self, template_key: str) -> NotificationTemplate:
        """Look up a template by key.

        Args:
            template_key: The template key to look up.

        Returns:
            The matching :class:`~notification.models.NotificationTemplate`.

        Raises:
            UnknownTemplateError: If no template is registered under
                ``template_key``.
        """
        template = self._templates.get(template_key)
        if template is None:
            raise UnknownTemplateError(template_key, tuple(self._templates.keys()))
        return template

    def exists(self, template_key: str) -> bool:
        """Return ``True`` if ``template_key`` matches a registered template."""
        return template_key in self._templates

    def render(self, template_key: str, context: dict) -> tuple[str, str]:
        """Render a template's subject and body against ``context``.

        Args:
            template_key: The template to render.
            context: Values to substitute into the template's
                ``{placeholder}`` slots. A key the template references
                but ``context`` doesn't have renders as the literal
                placeholder text rather than raising -- see
                :class:`SafeFormatDict`.

        Returns:
            A ``(subject, body)`` tuple of rendered strings.

        Raises:
            UnknownTemplateError: If no template is registered under
                ``template_key``.
        """
        template = self.get(template_key)
        safe_context = SafeFormatDict(context)
        subject = template.subject_template.format_map(safe_context)
        body = template.body_template.format_map(safe_context)
        return subject, body

    def all_keys(self) -> tuple[str, ...]:
        """Return every registered template key, sorted."""
        return tuple(sorted(self._templates.keys()))

    def clear(self) -> None:
        """Remove every registered template.

        Primarily useful for tests that need a clean registry rather
        than the shared, application-wide instance.
        """
        self._templates.clear()


# The eight default templates matching every EventType this sprint's
# ticket names (Task 3), plus a generic fallback. Adding a ninth for a
# future event type is one more NotificationTemplate(...) entry here --
# never a change to NotificationService.
DEFAULT_TEMPLATES: tuple[NotificationTemplate, ...] = (
    NotificationTemplate(
        "event.data_uploaded",
        "NovaMart: New dataset uploaded",
        "A new dataset was uploaded to {tenant_name}, triggered by {source_service}. "
        "{row_count} row(s) were processed.",
        "Sent when a business service announces DATA_UPLOADED.",
    ),
    NotificationTemplate(
        "event.report_generated",
        "NovaMart: Report generated",
        "A {report_type} report was generated for {tenant_name} by {source_service}.",
        "Sent when a business service announces REPORT_GENERATED.",
    ),
    NotificationTemplate(
        "event.pdf_generated",
        "NovaMart: PDF report ready",
        "A PDF report ({page_count} page(s)) is ready for {tenant_name}, generated by {source_service}.",
        "Sent when a business service announces PDF_GENERATED.",
    ),
    NotificationTemplate(
        "event.export_completed",
        "NovaMart: Data export completed",
        "A {export_format} data export completed for {tenant_name}, generated by {source_service}.",
        "Sent when a business service announces EXPORT_COMPLETED.",
    ),
    NotificationTemplate(
        "event.ai_analysis_completed",
        "NovaMart: AI recommendations ready",
        "{recommendation_count} AI-generated recommendation(s) are ready for {tenant_name}.",
        "Sent when a business service announces AI_ANALYSIS_COMPLETED.",
    ),
    NotificationTemplate(
        "event.kpi_threshold_reached",
        "NovaMart: KPI threshold alert -- {kpi_label}",
        "{kpi_label} for {tenant_name} is {value}, which is below the configured threshold of {threshold}. "
        "Executive attention may be needed.",
        "Sent when a KPI falls below its configured threshold (KPI_THRESHOLD_REACHED).",
    ),
    NotificationTemplate(
        "event.login_success",
        "NovaMart: Sign-in successful",
        "A successful sign-in was recorded for user {user_id}.",
        "Sent when a user signs in successfully (LOGIN_SUCCESS).",
    ),
    NotificationTemplate(
        "event.login_failed",
        "NovaMart: Failed sign-in attempt",
        "A failed sign-in attempt was recorded ({reason}).",
        "Sent when a sign-in attempt fails (LOGIN_FAILED).",
    ),
    NotificationTemplate(
        "event.user_logout",
        "NovaMart: Sign-out recorded",
        "User {user_id} signed out.",
        "Sent when a user signs out (USER_LOGOUT).",
    ),
    NotificationTemplate(
        "event.generic",
        "NovaMart: Platform notification",
        "A {event_type} event was recorded by {source_service}.",
        "Fallback template used for any event type without a dedicated template.",
    ),
)


def register_default_templates(registry: "TemplateRegistry") -> None:
    """Register every template in :data:`DEFAULT_TEMPLATES` into ``registry``.

    Called once, below, at import time against the shared
    :data:`template_registry` -- mirroring
    ``authorization.permissions.register_default_permissions``.

    Args:
        registry: The registry to populate.
    """
    for template in DEFAULT_TEMPLATES:
        registry.register(template)


# A shared, ready-to-use registry -- mirrors
# ``authorization.permissions.permission_registry``.
template_registry = TemplateRegistry()
register_default_templates(template_registry)
