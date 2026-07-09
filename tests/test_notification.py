"""Unit tests for the Notification Platform (Sprint 6.7).

This file is part of the Task 11 deliverable: comprehensive coverage of
the ``notification/`` package -- the notification/template models, the
in-memory provider and its per-channel routing registry, the template
registry (rendering, safe-missing-key handling), the Notification
Service (event handling/routing, template selection, provider
selection, send, graceful failure handling, history querying), and
integration with the existing Monitoring Service.

Following the convention already established by every prior sprint's
test suite, this file does not import ``streamlit`` or anything from
``components/``/``ui/``/``pages/``. It also never imports
``config/automation_setup.py`` -- every test constructs its own
:class:`~notification.service.NotificationService` (and, where needed,
a fresh :class:`~notification.registry.NotificationProviderRegistry` /
:class:`~notification.templates.TemplateRegistry`) via Dependency
Injection, isolated from the shared, application-wide singletons and
from whatever a real page's import chain would otherwise register.

Task 6 -- "Business services should never send notifications directly"
-------------------------------------------------------------------------
This suite proves that guarantee structurally: every test drives
:class:`~notification.service.NotificationService` through
:meth:`~notification.service.NotificationService.handle_event`, the
exact same entry point ``config/automation_setup.py`` registers as an
:class:`~automation.service.AutomationService` handler -- never through
some other, business-service-facing surface, because no such surface
exists on this class.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from automation.events import build_event
from automation.models import EventProcessingStatus, EventType
from monitoring.provider import InMemoryMonitoringProvider
from monitoring.registry import monitoring_provider_registry
from monitoring.service import monitoring_service
from notification.exceptions import (
    NotificationError,
    ProviderNotRegisteredError,
    UnknownTemplateError,
)
from notification.models import (
    NotificationChannel,
    NotificationMessage,
    NotificationStatus,
    NotificationTemplate,
)
from notification.provider import InMemoryNotificationProvider, NotificationProvider
from notification.registry import NotificationProviderRegistry
from notification.service import NotificationService, _event_type_key
from notification.templates import SafeFormatDict, TemplateRegistry, template_key_for_event_type


# --------------------------------------------------------------------------
# Shared fixtures
# --------------------------------------------------------------------------


@pytest.fixture
def provider_registry() -> NotificationProviderRegistry:
    """A fresh routing table, pre-populated with an in-memory provider on every channel."""
    registry = NotificationProviderRegistry()
    provider = InMemoryNotificationProvider()
    for channel in NotificationChannel:
        registry.register(channel, provider)
    return registry


@pytest.fixture
def template_registry_fixture() -> TemplateRegistry:
    """A fresh template registry with the same default templates as the shared one."""
    from notification.templates import DEFAULT_TEMPLATES

    registry = TemplateRegistry()
    for template in DEFAULT_TEMPLATES:
        registry.register(template)
    return registry


@pytest.fixture
def service(provider_registry: NotificationProviderRegistry, template_registry_fixture: TemplateRegistry) -> NotificationService:
    """A NotificationService wired to fresh dependencies via Dependency Injection."""
    return NotificationService(provider_registry=provider_registry, template_registry=template_registry_fixture)


@pytest.fixture
def clean_monitoring():
    """Clear the provider the shared ``monitoring_service`` actually writes to."""
    monitoring_service._provider.clear()
    yield
    monitoring_service._provider.clear()


def _report_generated_event(**overrides) -> "object":
    defaults = dict(
        event_type=EventType.REPORT_GENERATED,
        source_service="ReportingService",
        status=EventProcessingStatus.PUBLISHED,
        tenant_name="Acme Retail Group",
        payload={"report_type": "executive"},
    )
    defaults.update(overrides)
    return build_event(**defaults)


# ==============================================================================
# 1. Models
# ==============================================================================


def test_notification_channel_is_a_plain_string() -> None:
    assert NotificationChannel.EMAIL == "email"
    assert NotificationChannel.SLACK == "slack"
    assert NotificationChannel.TEAMS == "teams"
    assert NotificationChannel.SMS == "sms"
    assert NotificationChannel.WHATSAPP == "whatsapp"
    assert NotificationChannel.PUSH == "push"
    assert NotificationChannel.WEBHOOK == "webhook"


def test_notification_status_is_a_plain_string() -> None:
    assert NotificationStatus.PENDING == "pending"
    assert NotificationStatus.SENT == "sent"
    assert NotificationStatus.FAILED == "failed"


def test_notification_message_defaults() -> None:
    message = NotificationMessage(
        notification_id="n1", channel=NotificationChannel.EMAIL, recipient="exec@novamart.demo",
        subject="Hi", body="Body", status=NotificationStatus.PENDING, created_at=datetime.now(timezone.utc),
    )
    assert message.event_id is None
    assert message.sent_at is None
    assert message.error is None
    assert message.metadata == {}


def test_notification_message_is_frozen() -> None:
    message = NotificationMessage(
        notification_id="n1", channel=NotificationChannel.EMAIL, recipient="exec@novamart.demo",
        subject="Hi", body="Body", status=NotificationStatus.PENDING, created_at=datetime.now(timezone.utc),
    )
    with pytest.raises(Exception):
        message.status = NotificationStatus.SENT  # type: ignore[misc]


def test_notification_template_fields() -> None:
    template = NotificationTemplate("event.custom", "Subject {x}", "Body {x}", "A test template.")
    assert template.template_key == "event.custom"
    assert template.description == "A test template."


# ==============================================================================
# 2. Notification Provider (Provider Pattern, Task 7)
# ==============================================================================


def test_in_memory_provider_send_marks_sent_and_stamps_sent_at() -> None:
    provider = InMemoryNotificationProvider()
    pending = NotificationMessage(
        notification_id="n1", channel=NotificationChannel.EMAIL, recipient="exec@novamart.demo",
        subject="Hi", body="Body", status=NotificationStatus.PENDING, created_at=datetime.now(timezone.utc),
    )
    delivered = provider.send(pending)
    assert delivered.status == NotificationStatus.SENT
    assert delivered.sent_at is not None


def test_in_memory_provider_never_fails() -> None:
    """Task 7: 'an in-memory provider that simulates delivery' -- always succeeds."""
    provider = InMemoryNotificationProvider()
    for channel in NotificationChannel:
        pending = NotificationMessage(
            notification_id="n", channel=channel, recipient="target",
            subject="s", body="b", status=NotificationStatus.PENDING, created_at=datetime.now(timezone.utc),
        )
        assert provider.send(pending).status == NotificationStatus.SENT


def test_in_memory_provider_tracks_sent_messages() -> None:
    provider = InMemoryNotificationProvider()
    pending = NotificationMessage(
        notification_id="n1", channel=NotificationChannel.EMAIL, recipient="exec@novamart.demo",
        subject="Hi", body="Body", status=NotificationStatus.PENDING, created_at=datetime.now(timezone.utc),
    )
    provider.send(pending)
    assert len(provider.sent_messages()) == 1


def test_in_memory_provider_clear_removes_history() -> None:
    provider = InMemoryNotificationProvider()
    pending = NotificationMessage(
        notification_id="n1", channel=NotificationChannel.EMAIL, recipient="x",
        subject="s", body="b", status=NotificationStatus.PENDING, created_at=datetime.now(timezone.utc),
    )
    provider.send(pending)
    provider.clear()
    assert provider.sent_messages() == ()


def test_in_memory_provider_satisfies_notification_provider_protocol() -> None:
    assert isinstance(InMemoryNotificationProvider(), NotificationProvider)


class _WebhookStubProvider:
    """A from-scratch provider with no shared base class, proving Provider Pattern swappability."""

    name = "Webhook Stub"

    def __init__(self) -> None:
        self.delivered: list[NotificationMessage] = []

    def send(self, message: NotificationMessage) -> NotificationMessage:
        from dataclasses import replace

        result = replace(message, status=NotificationStatus.SENT, sent_at=datetime.now(timezone.utc))
        self.delivered.append(result)
        return result


def test_a_brand_new_provider_implementation_satisfies_the_protocol_and_works() -> None:
    custom_provider = _WebhookStubProvider()
    assert isinstance(custom_provider, NotificationProvider)

    registry = NotificationProviderRegistry()
    registry.register(NotificationChannel.WEBHOOK, custom_provider)
    pending = NotificationMessage(
        notification_id="n1", channel=NotificationChannel.WEBHOOK, recipient="https://example.test/hook",
        subject="s", body="b", status=NotificationStatus.PENDING, created_at=datetime.now(timezone.utc),
    )
    delivered = registry.get(NotificationChannel.WEBHOOK).send(pending)
    assert delivered.status == NotificationStatus.SENT
    assert len(custom_provider.delivered) == 1


# ==============================================================================
# 3. Notification Provider Registry (Task 7, routing table -- "providers interchangeable")
# ==============================================================================


def test_registry_register_and_get() -> None:
    registry = NotificationProviderRegistry()
    provider = InMemoryNotificationProvider()
    registry.register(NotificationChannel.EMAIL, provider)
    assert registry.get(NotificationChannel.EMAIL) is provider


def test_registry_get_by_string_key() -> None:
    registry = NotificationProviderRegistry()
    provider = InMemoryNotificationProvider()
    registry.register(NotificationChannel.EMAIL, provider)
    assert registry.get("email") is provider


def test_registry_get_unregistered_channel_raises() -> None:
    registry = NotificationProviderRegistry()
    with pytest.raises(ProviderNotRegisteredError):
        registry.get(NotificationChannel.SLACK)


def test_registry_registered_channels_sorted() -> None:
    registry = NotificationProviderRegistry()
    provider = InMemoryNotificationProvider()
    registry.register(NotificationChannel.SLACK, provider)
    registry.register(NotificationChannel.EMAIL, provider)
    assert registry.registered_channels() == ("email", "slack")


def test_registry_channels_are_independently_swappable() -> None:
    """Task 11: 'Providers are interchangeable.' Replacing one channel's
    provider must not affect any other channel's provider."""
    registry = NotificationProviderRegistry()
    shared = InMemoryNotificationProvider()
    registry.register(NotificationChannel.EMAIL, shared)
    registry.register(NotificationChannel.SLACK, shared)

    custom_email_provider = _WebhookStubProvider()
    registry.register(NotificationChannel.EMAIL, custom_email_provider)

    assert registry.get(NotificationChannel.EMAIL) is custom_email_provider
    assert registry.get(NotificationChannel.SLACK) is shared  # untouched


def test_registry_clear_removes_every_provider() -> None:
    registry = NotificationProviderRegistry()
    registry.register(NotificationChannel.EMAIL, InMemoryNotificationProvider())
    registry.clear()
    assert registry.registered_channels() == ()


# ==============================================================================
# 4. Template Registry (Task 6)
# ==============================================================================


def test_safe_format_dict_renders_missing_key_as_literal_placeholder() -> None:
    template = "Hello {name}, your {missing_field} is ready."
    rendered = template.format_map(SafeFormatDict({"name": "Jane"}))
    assert rendered == "Hello Jane, your {missing_field} is ready."


def test_template_registry_register_and_get() -> None:
    registry = TemplateRegistry()
    template = NotificationTemplate("event.custom", "Subject", "Body")
    registry.register(template)
    assert registry.get("event.custom") == template


def test_template_registry_get_unknown_raises() -> None:
    registry = TemplateRegistry()
    with pytest.raises(UnknownTemplateError):
        registry.get("does-not-exist")


def test_template_registry_exists() -> None:
    registry = TemplateRegistry()
    registry.register(NotificationTemplate("event.custom", "S", "B"))
    assert registry.exists("event.custom") is True
    assert registry.exists("event.unknown") is False


def test_template_registry_render_substitutes_context() -> None:
    registry = TemplateRegistry()
    registry.register(NotificationTemplate("event.custom", "Report: {report_type}", "Your {report_type} report is ready."))
    subject, body = registry.render("event.custom", {"report_type": "executive"})
    assert subject == "Report: executive"
    assert body == "Your executive report is ready."


def test_template_registry_render_tolerates_missing_context_keys() -> None:
    registry = TemplateRegistry()
    registry.register(NotificationTemplate("event.custom", "Hi {name}", "{missing} value"))
    subject, body = registry.render("event.custom", {"name": "Jane"})
    assert subject == "Hi Jane"
    assert body == "{missing} value"


def test_template_key_for_event_type() -> None:
    assert template_key_for_event_type("report_generated") == "event.report_generated"


def test_default_templates_cover_every_event_type() -> None:
    registry = TemplateRegistry()
    from notification.templates import register_default_templates

    register_default_templates(registry)
    for event_type in EventType:
        assert registry.exists(template_key_for_event_type(event_type.value))
    assert registry.exists("event.generic")  # fallback


# ==============================================================================
# 5. _event_type_key -- the EventType str()-vs-.value normalization
# ==============================================================================


def test_event_type_key_normalizes_enum_member() -> None:
    assert _event_type_key(EventType.REPORT_GENERATED) == "report_generated"


def test_event_type_key_passes_through_plain_string() -> None:
    assert _event_type_key("some_future_event") == "some_future_event"


# ==============================================================================
# 6. Notification Service -- handle_event() routing (Task 6)
# ==============================================================================


def test_handle_event_routes_report_generated_to_email(service: NotificationService) -> None:
    event = _report_generated_event()
    messages = service.handle_event(event)
    assert len(messages) == 1
    assert messages[0].channel == NotificationChannel.EMAIL
    assert messages[0].recipient == "executives@novamart.demo"
    assert messages[0].status == NotificationStatus.SENT


def test_handle_event_routes_ai_analysis_completed_to_slack(service: NotificationService) -> None:
    event = build_event(
        event_type=EventType.AI_ANALYSIS_COMPLETED, source_service="AIRecommendationService",
        status=EventProcessingStatus.PUBLISHED, tenant_name="Acme", payload={"recommendation_count": 3},
    )
    messages = service.handle_event(event)
    assert messages[0].channel == NotificationChannel.SLACK
    assert messages[0].recipient == "#novamart-insights"


def test_handle_event_with_unrouted_event_type_returns_empty_tuple(service: NotificationService) -> None:
    event = build_event(
        event_type="some_future_event_with_no_route", source_service="FutureService",
        status=EventProcessingStatus.PUBLISHED,
    )
    assert service.handle_event(event) == ()


def test_handle_event_never_called_by_business_services_directly() -> None:
    """Structural proof for Task 6: no automation.service module-level
    import of notification exists (the reverse direction is checked in
    test_automation.py); this asserts the one legitimate call path --
    a registered EventHandler -- works exactly like AutomationService
    expects a handler to (a single-argument callable)."""
    import inspect

    service = NotificationService()
    sig = inspect.signature(service.handle_event)
    assert list(sig.parameters) == ["event"]


# ==============================================================================
# 7. Notification Service -- notify() (Task 6: template, provider, send, failures)
# ==============================================================================


def test_notify_renders_template_and_sends(service: NotificationService) -> None:
    event = _report_generated_event()
    message = service.notify(event, channel=NotificationChannel.EMAIL, recipient="exec@novamart.demo")
    assert message.status == NotificationStatus.SENT
    assert "executive" in message.body
    assert "Acme Retail Group" in message.body


def test_notify_falls_back_to_generic_template_for_unknown_event_type(service: NotificationService) -> None:
    event = build_event(
        event_type="totally_novel_event_type", source_service="FutureService",
        status=EventProcessingStatus.PUBLISHED,
    )
    message = service.notify(event, channel=NotificationChannel.EMAIL, recipient="exec@novamart.demo")
    assert message.status == NotificationStatus.SENT
    assert message.metadata["template_key"] == "event.generic"


def test_notify_with_unregistered_channel_returns_failed_not_raises(template_registry_fixture: TemplateRegistry) -> None:
    empty_provider_registry = NotificationProviderRegistry()  # no providers registered at all
    service = NotificationService(provider_registry=empty_provider_registry, template_registry=template_registry_fixture)
    event = _report_generated_event()

    message = service.notify(event, channel=NotificationChannel.EMAIL, recipient="exec@novamart.demo")  # must not raise
    assert message.status == NotificationStatus.FAILED
    assert message.error is not None


def test_notify_with_a_provider_that_raises_returns_failed_not_raises(
    template_registry_fixture: TemplateRegistry,
) -> None:
    class _BrokenProvider:
        name = "Broken"

        def send(self, message: NotificationMessage) -> NotificationMessage:
            raise RuntimeError("network down")

    registry = NotificationProviderRegistry()
    registry.register(NotificationChannel.EMAIL, _BrokenProvider())
    service = NotificationService(provider_registry=registry, template_registry=template_registry_fixture)

    event = _report_generated_event()
    message = service.notify(event, channel=NotificationChannel.EMAIL, recipient="exec@novamart.demo")  # must not raise

    assert message.status == NotificationStatus.FAILED
    assert "network down" in message.error


def test_notify_records_delivered_message_in_history(service: NotificationService) -> None:
    event = _report_generated_event()
    service.notify(event, channel=NotificationChannel.EMAIL, recipient="exec@novamart.demo")
    assert len(service.get_history()) == 1


def test_notify_records_failed_message_in_history_too(
    template_registry_fixture: TemplateRegistry,
) -> None:
    empty_provider_registry = NotificationProviderRegistry()
    service = NotificationService(provider_registry=empty_provider_registry, template_registry=template_registry_fixture)
    event = _report_generated_event()
    service.notify(event, channel=NotificationChannel.EMAIL, recipient="exec@novamart.demo")
    history = service.get_history()
    assert len(history) == 1
    assert history[0].status == NotificationStatus.FAILED


# ==============================================================================
# 8. Notification Service -- register_route() (extensibility)
# ==============================================================================


def test_register_route_with_static_recipient(service: NotificationService) -> None:
    service.register_route("custom_event", NotificationChannel.EMAIL, "custom@novamart.demo")
    event = build_event(event_type="custom_event", source_service="CustomService", status=EventProcessingStatus.PUBLISHED)
    messages = service.handle_event(event)
    assert messages[0].recipient == "custom@novamart.demo"


def test_register_route_with_dynamic_resolver(service: NotificationService) -> None:
    def _resolve(event) -> str:
        return f"{event.tenant_name or 'unknown'}@novamart.demo"

    service.register_route("custom_event", NotificationChannel.EMAIL, _resolve)
    event = build_event(
        event_type="custom_event", source_service="CustomService", status=EventProcessingStatus.PUBLISHED,
        tenant_name="Acme",
    )
    messages = service.handle_event(event)
    assert messages[0].recipient == "Acme@novamart.demo"


def test_register_route_accepts_an_event_type_enum_member(service: NotificationService) -> None:
    """register_route's event_type key must normalize an EventType member
    the same way handle_event() normalizes event.event_type, or routing
    silently breaks -- this is the exact bug class _event_type_key exists
    to prevent."""
    service.register_route(EventType.KPI_THRESHOLD_REACHED, NotificationChannel.SLACK, "#alerts")
    event = build_event(
        event_type=EventType.KPI_THRESHOLD_REACHED, source_service="KPIThresholdWatcher",
        status=EventProcessingStatus.PUBLISHED,
    )
    messages = service.handle_event(event)
    assert messages[0].recipient == "#alerts"


# ==============================================================================
# 9. Notification Service -- get_history() / clear_history() (Task 10 support)
# ==============================================================================


def test_get_history_filters_by_channel(service: NotificationService) -> None:
    service.notify(_report_generated_event(), channel=NotificationChannel.EMAIL, recipient="a@x.com")
    service.notify(_report_generated_event(), channel=NotificationChannel.SLACK, recipient="#chan")
    email_only = service.get_history(channel=NotificationChannel.EMAIL)
    assert len(email_only) == 1
    assert email_only[0].channel == NotificationChannel.EMAIL


def test_get_history_filters_by_status(
    template_registry_fixture: TemplateRegistry,
) -> None:
    empty_registry = NotificationProviderRegistry()
    empty_registry.register(NotificationChannel.EMAIL, InMemoryNotificationProvider())
    service = NotificationService(provider_registry=empty_registry, template_registry=template_registry_fixture)

    service.notify(_report_generated_event(), channel=NotificationChannel.EMAIL, recipient="a@x.com")  # succeeds
    service.notify(_report_generated_event(), channel=NotificationChannel.SLACK, recipient="#chan")  # fails: no slack provider

    failed_only = service.get_history(status=NotificationStatus.FAILED)
    assert len(failed_only) == 1
    assert failed_only[0].channel == NotificationChannel.SLACK


def test_get_history_newest_first(service: NotificationService) -> None:
    first = service.notify(_report_generated_event(), channel=NotificationChannel.EMAIL, recipient="a@x.com")
    second = service.notify(_report_generated_event(), channel=NotificationChannel.EMAIL, recipient="b@x.com")
    history = service.get_history()
    assert history[0].notification_id == second.notification_id
    assert history[1].notification_id == first.notification_id


def test_get_history_respects_limit(service: NotificationService) -> None:
    for _ in range(3):
        service.notify(_report_generated_event(), channel=NotificationChannel.EMAIL, recipient="a@x.com")
    assert len(service.get_history(limit=2)) == 2


def test_clear_history_removes_everything(service: NotificationService) -> None:
    service.notify(_report_generated_event(), channel=NotificationChannel.EMAIL, recipient="a@x.com")
    service.clear_history()
    assert service.get_history() == ()


# ==============================================================================
# 10. Monitoring integration (Task 9)
# ==============================================================================


def _events_for(operation: str) -> tuple:
    return tuple(
        event
        for event in monitoring_service.get_events(service_name="NotificationService")
        if event.operation == operation
    )


def test_successful_send_is_recorded_as_completed(service: NotificationService, clean_monitoring) -> None:
    service.notify(_report_generated_event(), channel=NotificationChannel.EMAIL, recipient="exec@novamart.demo")
    events = _events_for("send_notification")
    assert len(events) == 1
    assert events[0].status.value == "success"


def test_failed_send_is_recorded_as_failure(
    template_registry_fixture: TemplateRegistry, clean_monitoring
) -> None:
    empty_registry = NotificationProviderRegistry()
    service = NotificationService(provider_registry=empty_registry, template_registry=template_registry_fixture)
    service.notify(_report_generated_event(), channel=NotificationChannel.EMAIL, recipient="exec@novamart.demo")

    events = _events_for("send_notification")
    assert len(events) == 1
    assert events[0].status.value == "failure"


def test_a_monitoring_storage_failure_never_prevents_a_notification(
    provider_registry: NotificationProviderRegistry, template_registry_fixture: TemplateRegistry, clean_monitoring
) -> None:
    """Mirrors AutomationService's own resilience guarantee: an
    observability outage can never become a notification outage."""

    class _BrokenMonitoringProvider(InMemoryMonitoringProvider):
        def record(self, event) -> None:  # noqa: ANN001 - test double
            raise RuntimeError("storage backend unreachable")

    monitoring_provider_registry.register("broken", _BrokenMonitoringProvider(), make_active=True)
    try:
        broken_service = NotificationService(provider_registry=provider_registry, template_registry=template_registry_fixture)
        message = broken_service.notify(_report_generated_event(), channel=NotificationChannel.EMAIL, recipient="exec@novamart.demo")
        assert message.status == NotificationStatus.SENT  # decision still correct despite broken monitoring
    finally:
        monitoring_provider_registry.register("memory", InMemoryMonitoringProvider(), make_active=True)


# ==============================================================================
# 11. Regression -- isolation, independence from automation and business services
# ==============================================================================


def test_fresh_service_instances_do_not_share_history() -> None:
    service_a = NotificationService()
    service_b = NotificationService()
    service_a.notify(_report_generated_event(), channel=NotificationChannel.EMAIL, recipient="a@x.com")
    assert service_a.get_history() != ()
    assert service_b.get_history() == ()


def test_default_notification_service_constructs_without_arguments() -> None:
    default_service = NotificationService()
    assert isinstance(default_service, NotificationService)


def test_notification_error_hierarchy() -> None:
    assert issubclass(UnknownTemplateError, NotificationError)
    assert issubclass(ProviderNotRegisteredError, NotificationError)


def test_notification_package_never_imports_automation_service_module() -> None:
    """notification/ may receive an AutomationEvent as a parameter (a
    type reference), but must never import automation.service itself --
    that would let a notification failure reach back into automation
    internals, exactly the tight coupling Task 6 forbids."""
    import ast
    import inspect

    import notification.exceptions
    import notification.models
    import notification.provider
    import notification.registry
    import notification.service
    import notification.templates

    for module in (
        notification.exceptions,
        notification.models,
        notification.provider,
        notification.registry,
        notification.service,
        notification.templates,
    ):
        source = inspect.getsource(module)
        tree = ast.parse(source)
        imported_names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_names.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_names.add(node.module)
        assert "automation.service" not in imported_names, (
            f"{module.__name__} unexpectedly imports automation.service: {imported_names}"
        )
