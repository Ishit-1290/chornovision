"""Deterministic event messages (Phase 5).

Public API:
- :data:`TEMPLATES` — fixed templates keyed by canonical ``event_type``.
- :func:`render_event_message` — render from validated metadata.
- :func:`render_event` — render from a structured event snapshot.
"""

from app.event_messages.renderer import (
    EventMessageContext,
    MessageRenderError,
    format_event_time,
    message_context_from_event,
    render_event,
    render_event_message,
    sanitize_display_text,
)
from app.event_messages.templates import TEMPLATES, MessageTemplate, template_for

__all__ = [
    "TEMPLATES",
    "EventMessageContext",
    "MessageRenderError",
    "MessageTemplate",
    "format_event_time",
    "message_context_from_event",
    "render_event",
    "render_event_message",
    "sanitize_display_text",
    "template_for",
]
