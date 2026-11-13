"""Vision worker runtime entry point: ``python -m vision.runtime`` (FR-02, W §14).

This is a **separate runtime** from the FastAPI backend. It:

1. builds the internal HTTP client from validated settings;
2. asks the backend to reconcile cameras left in a processing state (the worker owns runtime
   reconciliation, D-24);
3. polls the requested plan and runs one worker per enabled camera;
4. shuts every worker down cleanly on ``SIGINT``/``SIGTERM``.

It never runs inside an HTTP handler (NFR-02) and never depends on the browser (NFR-01).
"""

from __future__ import annotations

import logging
import signal
import threading
import time
from collections.abc import Callable, Sequence

from app.config import get_settings

from vision.camera_manager.manager import CameraManager
from vision.camera_manager.worker import CameraConfig, CameraWorker
from vision.config import TrackerKind, VisionSettings, get_vision_settings
from vision.detection.detector import YoloDetector
from vision.event_handoff import EventHandoff
from vision.evidence import EvidenceCoordinator, EvidenceManager, EvidencePolicy, EvidenceStore
from vision.ingestion.rotation import normalize_rotation
from vision.ingestion.sources import OpenCVFrameSource
from vision.internal_client import InternalClient, InternalClientError
from vision.net import PinnedTarget
from vision.supervisor import Supervisor
from vision.tracking.tracker import ByteTrackTracker, IoUTracker, Tracker

LOGGER = logging.getLogger("vision.runtime")


def _configure_logging(level: str) -> None:
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s %(message)s")


def _tracker_for(settings: VisionSettings) -> Tracker:
    if settings.tracker is TrackerKind.IOU:
        return IoUTracker()
    return ByteTrackTracker()


def _build_coordinator(
    camera: CameraConfig,
    *,
    settings: VisionSettings,
    client: InternalClient,
    clock: Callable[[], float] = time.monotonic,
    logger: logging.Logger,
) -> EvidenceCoordinator:
    """Build the per-camera event handoff + evidence capture coordinator."""
    policy = EvidencePolicy.from_settings(get_settings())
    handoff = EventHandoff(
        client=client,
        camera_id=camera.id,
        queue_maxsize=settings.evidence_handoff_queue_maxsize,
        spool_max_bytes=settings.evidence_handoff_spool_max_mb * 1024 * 1024,
        max_attempts=settings.evidence_handoff_max_attempts,
        retry_backoff_seconds=settings.evidence_handoff_retry_backoff_seconds,
        logger=logger,
    )
    manager = EvidenceManager(
        policy=policy,
        store=EvidenceStore(),
        registrar=handoff.enqueue_evidence,
        encoder_queue_maxsize=settings.evidence_encoder_queue_maxsize,
        # The same per-camera rotation that straightens detection also straightens the
        # recorded snapshot/clip, so evidence matches the live view (D-72/D-74).
        rotation=normalize_rotation((camera.configuration or {}).get("rotation")),
        logger=logger,
    )
    return EvidenceCoordinator(
        camera_id=camera.id,
        manager=manager,
        handoff=handoff,
        clock=clock,
        logger=logger,
    )


def _build_worker(
    camera: CameraConfig,
    *,
    settings: VisionSettings,
    client: InternalClient,
    coordinator: EvidenceCoordinator | None = None,
    logger: logging.Logger,
) -> CameraWorker:
    def report(status: str, detail: str | None, metrics: dict[str, object]) -> None:
        result = client.report_state(camera.id, status, detail=detail, metrics=metrics)
        if not result.applied and result.status != status:
            logger.warning(
                "camera %s: backend kept state %s (reported %s)",
                camera.id,
                result.status,
                status,
            )

    def source_factory(target: PinnedTarget) -> OpenCVFrameSource:
        return OpenCVFrameSource(
            target.url,
            open_timeout=settings.connect_timeout_seconds,
            read_timeout=settings.read_timeout_seconds,
        )

    def detector_factory() -> YoloDetector:
        return YoloDetector(
            weights=settings.detector_weights,
            device=settings.detector_device,
            confidence=settings.detector_confidence,
            iou=settings.detector_iou,
            imgsz=settings.detector_imgsz,
            person_only=settings.detector_person_only,
        )

    coordinator = coordinator or _build_coordinator(
        camera, settings=settings, client=client, logger=logger
    )
    return CameraWorker(
        camera,
        settings=settings,
        report=report,
        source_factory=source_factory,
        detector_factory=detector_factory,
        tracker_factory=lambda: _tracker_for(settings),
        event_sink=coordinator,
        evidence=coordinator,
        logger=logger,
    )


def build_supervisor(
    settings: VisionSettings | None = None, *, client: InternalClient | None = None
) -> Supervisor:
    """Construct the supervisor and its manager (used by ``main`` and by tests)."""
    settings = settings or get_vision_settings()
    client = client or InternalClient(
        base_url=settings.backend_base_url,
        token=settings.internal_api_token,
        timeout=settings.internal_request_timeout_seconds,
        max_retries=settings.internal_max_retries,
    )

    def worker_factory(camera: CameraConfig) -> CameraWorker:
        return _build_worker(camera, settings=settings, client=client, logger=LOGGER)

    manager = CameraManager(
        worker_factory=worker_factory,
        max_concurrent=settings.max_concurrent_cameras,
        stop_timeout=settings.connect_timeout_seconds + 5.0,
        logger=LOGGER,
    )
    return Supervisor(client=client, settings=settings, manager=manager, logger=LOGGER)


def _install_signal_handlers(stop_event: threading.Event) -> None:
    def _handler(signum: int, _frame: object) -> None:
        LOGGER.info("received signal %s; shutting down", signum)
        stop_event.set()

    for signame in ("SIGINT", "SIGTERM"):
        signal_number = getattr(signal, signame, None)
        if signal_number is not None:
            signal.signal(signal_number, _handler)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the vision worker until interrupted. Returns a process exit code."""
    settings = get_vision_settings()
    _configure_logging(settings.log_level)
    LOGGER.info("vision worker starting; backend=%s", settings.backend_base_url)

    client = InternalClient(
        base_url=settings.backend_base_url,
        token=settings.internal_api_token,
        timeout=settings.internal_request_timeout_seconds,
        max_retries=settings.internal_max_retries,
    )
    supervisor = build_supervisor(settings, client=client)

    try:
        reconciled = client.reconcile()
        LOGGER.info("startup reconcile reset %d processing camera(s)", reconciled)
    except InternalClientError as exc:
        LOGGER.warning("startup reconcile failed: %s", exc)

    stop_event = threading.Event()
    _install_signal_handlers(stop_event)
    try:
        supervisor.run(stop_event)
    finally:
        supervisor.shutdown()
    LOGGER.info("vision worker stopped")
    return 0


if __name__ == "__main__":  # pragma: no cover - process entry point
    raise SystemExit(main())
