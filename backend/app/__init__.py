"""ChronoVision backend package.

Phase 4 adds the worker→backend internal channel that the vision runtime uses to report
per-camera lifecycle state and to fetch the requested runtime plan. Video inference still runs
in the separate vision worker process, never in an HTTP handler.

Module boundaries:
    api/            HTTP routers and error handling (Phase 2+)
    auth/           authentication, sessions, CSRF, rate limiting, internal token (Phase 2+)
    models/         SQLAlchemy ORM models (Phase 2+)
    schemas/        Pydantic request/response schemas (Phase 2+)
    repositories/   persistence access helpers (Phase 2+)
    services/       business logic (Phase 2+); stream_validation, lifecycle,
                    monitoring_service, camera_service (Phase 3); worker_registry (Phase 4);
                    event_service, evidence_service (Phase 6)
    db.py           engine/session lifecycle (Phase 2)
    event_messages/ deterministic message templates (Phase 5)
"""

__version__ = "0.7.0"

__all__ = ["__version__"]
