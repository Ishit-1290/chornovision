"""CLI entry point: ``python -m vision.benchmarks`` (Phase 8; NFR-13, NFR-15).

Example::

    python -m vision.benchmarks --cameras 1,2,4 --duration 15 --detector-cost-ms 20 \\
        --output benchmarks/report.json

Each camera count is run for ``--duration`` seconds against the same synthetic clip. The report
includes the measured runtime metrics and two micro-benchmarks (event-handoff delivery latency
and snapshot-encode latency). Real OpenCV is required for the camera runs and the encode
micro-benchmark; failures there are reported honestly rather than hidden.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from .harness import (
    BenchmarkConfig,
    environment_info,
    measure_event_handoff_latency,
    measure_evidence_encode_latency,
    measure_recovery_time,
    run_camera_benchmark,
    write_report,
)


def _parse_counts(value: str) -> list[int]:
    counts = sorted({int(part) for part in value.split(",") if part.strip()})
    if not counts or counts[0] < 1:
        raise argparse.ArgumentTypeError("--cameras must list positive integers")
    return counts


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="vision.benchmarks",
        description="Run reproducible multi-camera vision-pipeline benchmarks.",
    )
    parser.add_argument("--cameras", default="1", type=_parse_counts)
    parser.add_argument("--duration", type=float, default=10.0)
    parser.add_argument("--detector-cost-ms", type=float, default=20.0)
    parser.add_argument("--target-fps", type=float, default=10.0)
    parser.add_argument("--capture-fps", type=float, default=30.0)
    parser.add_argument("--queue-maxsize", type=int, default=8)
    parser.add_argument("--output", default=None, help="write the full JSON report here")
    parser.add_argument("--skip-handoff", action="store_true")
    parser.add_argument("--skip-encode", action="store_true")
    parser.add_argument("--skip-recovery", action="store_true")
    args = parser.parse_args(argv)

    report: dict[str, object] = {
        "generated_at": datetime.now(UTC).isoformat(),
        "environment": environment_info(),
        "detector_mode": "synthetic",
        "parameters": {
            "camera_counts": args.cameras,
            "duration_seconds": args.duration,
            "detector_cost_ms": args.detector_cost_ms,
            "target_fps": args.target_fps,
            "queue_maxsize": args.queue_maxsize,
        },
        "runs": [],
        "micro": {},
    }

    with tempfile.TemporaryDirectory(prefix="cv-benchmark-") as tmp:
        workdir = Path(tmp)
        for count in args.cameras:
            config = BenchmarkConfig(
                camera_count=count,
                duration_seconds=args.duration,
                detector_cost_seconds=args.detector_cost_ms / 1000.0,
                process_target_fps=args.target_fps,
                queue_maxsize=args.queue_maxsize,
                capture_fps=args.capture_fps,
                clip_fps=args.capture_fps,
                clip_frames=max(300, int(args.capture_fps * (args.duration + 5.0))),
            )
            try:
                result = run_camera_benchmark(config, workdir=workdir)
            except Exception as exc:  # OpenCV missing, codec issue, etc.
                result = {"camera_count": count, "error": f"{type(exc).__name__}: {exc}"}
            report["runs"].append(result)  # type: ignore[union-attr]
            print(
                json.dumps(
                    {
                        "camera_count": count,
                        "totals": result.get("totals"),
                        "startup_seconds": result.get("startup_seconds"),
                        "resources": result.get("resources"),
                        "error": result.get("error"),
                    }
                )
            )

        micro: dict[str, object] = report["micro"]  # type: ignore[assignment]
        if not args.skip_handoff:
            micro["event_handoff"] = measure_event_handoff_latency(spool_dir=workdir / "spool")
        if not args.skip_encode:
            try:
                micro["evidence_encode"] = measure_evidence_encode_latency(
                    root=workdir / "evidence"
                )
            except Exception as exc:
                micro["evidence_encode"] = {"error": f"{type(exc).__name__}: {exc}"}
        if not args.skip_recovery:
            try:
                micro["recovery"] = measure_recovery_time(workdir=workdir)
            except Exception as exc:
                micro["recovery"] = {"error": f"{type(exc).__name__}: {exc}"}
        print(json.dumps({"micro": micro}))

    if args.output:
        write_report(Path(args.output), report)
        print(f"report written to {args.output}", file=sys.stderr)
    else:
        print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover - process entry point
    raise SystemExit(main())
