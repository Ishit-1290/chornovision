"""Unit tests for the worker-health registry and staleness projection (Phase 4)."""

from __future__ import annotations

from datetime import timedelta

from app.models.camera import Camera
from app.services import monitoring_service
from app.services import worker_registry as registry_module
from app.services.worker_registry import WorkerHealthRegistry, get_worker_registry
from app.utils import utcnow


def _camera(*, status: str, updated_at=None) -> Camera:
    return Camera(
        id=1,
        name="front-door",
        stream_reference="rtsp://192.168.1.10:554/stream1",
        enabled=True,
        status=status,
        configuration={},
        updated_at=updated_at if updated_at is not None else utcnow(),
    )


# --- registry -------------------------------------------------------------------


def test_registry_records_and_reads_latest_report() -> None:
    registry = get_worker_registry()
    registry.record(1, "connecting")
    registry.record(1, "active", detail=None, metrics={"frames_processed": 3})
    report = registry.get(1)
    assert report is not None
    assert report.status == "active"
    assert report.metrics == {"frames_processed": 3}
    assert registry.last_seen(1) is not None


def test_registry_forget_and_clear() -> None:
    registry = get_worker_registry()
    registry.record(1, "active")
    registry.record(2, "active")
    registry.forget(1)
    assert registry.get(1) is None
    assert set(registry.snapshot()) == {2}
    registry.clear()
    assert registry.snapshot() == {}


# --- projection -----------------------------------------------------------------


def test_non_processing_state_is_never_projected(admin_env) -> None:
    assert monitoring_service.effective_status(_camera(status="stopped")) == "stopped"
    assert monitoring_service.effective_status(_camera(status="configured")) == "configured"


def test_fresh_activity_is_not_projected(admin_env) -> None:
    camera = _camera(status="active", updated_at=utcnow() - timedelta(hours=1))
    get_worker_registry().record(camera.id, "active")  # fresh report keeps it fresh
    assert monitoring_service.effective_status(camera) == "active"


def test_old_updated_at_without_report_is_projected_disconnected(admin_env) -> None:
    camera = _camera(status="active", updated_at=utcnow() - timedelta(hours=1))
    assert monitoring_service.effective_status(camera) == "disconnected"


def test_old_report_is_projected_disconnected(admin_env) -> None:
    camera = _camera(status="active", updated_at=utcnow() - timedelta(hours=1))
    stale = WorkerHealthRegistry(clock=lambda: utcnow() - timedelta(seconds=120))
    stale.record(camera.id, "active")
    registry_module._registry = stale
    assert monitoring_service.effective_status(camera) == "disconnected"
