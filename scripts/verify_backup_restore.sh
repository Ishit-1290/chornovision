#!/usr/bin/env bash
#
# verify_backup_restore.sh — Phase 9 backup/restore verification (W §13 M8).
#
# Backs up a *disposable* PostgreSQL cluster's structured data with ``pg_dump`` and restores
# it into a second fresh database with ``pg_restore``, then checks that:
#
#   * the schema (Alembic revision) survived the round trip;
#   * row counts match between source and restored databases;
#   * foreign-key relationships are intact (every evidence row references a real event);
#   * filesystem evidence remains accessible after the evidence tree is copied alongside
#     the database backup (the restore procedure keeps the two in sync).
#
# The script never touches the application's real database, evidence directory, or
# PostgreSQL service: it creates an isolated ``initdb`` cluster in a temporary directory and
# removes it on exit. Requires ``initdb``/``pg_ctl``/``psql``/``pg_dump``/``pg_restore``
# (PostgreSQL 15+) on ``PATH``.
#
# Usage:  scripts/verify_backup_restore.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND="$ROOT/backend"
PY="$BACKEND/.venv/bin/python"
ALEMBIC="$BACKEND/.venv/bin/alembic"
EVIDENCE_SRC_BYTES="phase9-evidence-bytes"

for tool in initdb pg_ctl psql pg_dump pg_restore createdb; do
    if ! command -v "$tool" >/dev/null 2>&1; then
        echo "FAIL: required tool '$tool' not found on PATH" >&2
        exit 127
    fi
done
if [[ ! -x "$PY" ]]; then
    echo "FAIL: backend virtualenv not found at $PY" >&2
    exit 127
fi

WORK="$(mktemp -d "${TMPDIR:-/tmp/opencode}/chronovision-backup-XXXXXX")"
DATA="$WORK/pgdata"
SOCK="$WORK/sock"
PGRUN="$WORK/pg.log"
EVIDENCE_SRC="$WORK/evidence-src"
EVIDENCE_DST="$WORK/evidence-dst"
DUMP="$WORK/chronovision.dump"
mkdir -p "$SOCK" "$EVIDENCE_SRC"

PORT="$("$PY" - <<'PYEOF'
import socket
s = socket.socket()
s.bind(("127.0.0.1", 0))
print(s.getsockname()[1])
s.close()
PYEOF
)"

cleanup() {
    pg_ctl -D "$DATA" -m immediate stop >/dev/null 2>&1 || true
    rm -rf "$WORK"
}
trap cleanup EXIT

echo "==> creating disposable PostgreSQL cluster in $WORK (port $PORT)"
initdb -D "$DATA" -U postgres --auth-local=trust --auth-host=trust >/dev/null
pg_ctl -D "$DATA" -o "-p $PORT -k $SOCK -c listen_addresses=127.0.0.1" -l "$PGRUN" -w start >/dev/null

psql_admin() { psql -h 127.0.0.1 -p "$PORT" -U postgres -v ON_ERROR_STOP=1 "$@"; }

# Environment the application/alembic read (identical shape to a real deployment).
export POSTGRES_HOST=127.0.0.1
export POSTGRES_PORT="$PORT"
export POSTGRES_USER=postgres
export POSTGRES_PASSWORD="disposable-password-not-a-real-secret"
export SECRET_KEY="backup-verify-secret-key-$(printf 'a%.0s' {1..32})"
export INTERNAL_API_TOKEN="backup-verify-internal-token-$(printf 'b%.0s' {1..32})"
export ENVIRONMENT=test

echo "==> creating source database and running migrations"
psql_admin -c "CREATE DATABASE src;" >/dev/null
export POSTGRES_DB=src
(cd "$BACKEND" && "$ALEMBIC" upgrade head >/dev/null)

echo "==> seeding representative structured data and evidence bytes"
export EVIDENCE_DIR="$EVIDENCE_SRC"
(cd "$BACKEND" && "$PY" - <<'PYEOF'
from pathlib import Path

from app.db import get_session_factory
from app.models.camera import Camera
from app.models.event import Event
from app.models.evidence import Evidence, EvidenceStatus, RetentionStatus
from app.models.user import User
from app.auth.security import hash_password
from app.utils import utcnow

now = utcnow()
relative = "camera-1/2026/10/29/evt-1-snapshot.jpg"
path = Path(__import__("os").environ["EVIDENCE_DIR"]) / relative
path.parent.mkdir(parents=True, exist_ok=True)
path.write_bytes(b"phase9-evidence-bytes")

session = get_session_factory()()
try:
    user = User(username="admin", password_hash=hash_password("correct-horse-battery-staple"), is_active=True)
    session.add(user)
    camera = Camera(name="front-door", stream_reference="rtsp://192.168.1.10:554/s1")
    session.add(camera)
    session.flush()
    event = Event(
        event_id="11111111-1111-5111-8111-aaaaaaaaaaaa",
        camera_id=camera.id,
        event_type="person_entering",
        start_time=now,
        trigger_time=now,
        last_updated_at=now,
        status="completed",
        severity="info",
        certainty="high",
        message="A person entered.",
        attributes={},
        evidence_refs=["snapshot:1"],
    )
    session.add(event)
    session.flush()
    session.add(
        Evidence(
            event_id=event.id,
            media_type="snapshot",
            relative_path=relative,
            status=EvidenceStatus.AVAILABLE.value,
            retention_status=RetentionStatus.RETAINED.value,
            file_size_bytes=path.stat().st_size,
            captured_at=now,
        )
    )
    session.commit()
finally:
    session.close()
PYEOF
)

echo "==> dumping source database (custom format)"
pg_dump -h 127.0.0.1 -p "$PORT" -U postgres -Fc -f "$DUMP" src

echo "==> restoring into a fresh database"
psql_admin -c "CREATE DATABASE dst;" >/dev/null
pg_restore -h 127.0.0.1 -p "$PORT" -U postgres -d dst --no-owner "$DUMP" >/dev/null

echo "==> copying the evidence tree alongside the database backup"
cp -a "$EVIDENCE_SRC" "$EVIDENCE_DST"

echo "==> verifying the restored database and evidence"
export POSTGRES_DB=dst
export EVIDENCE_DIR="$EVIDENCE_DST"
(cd "$BACKEND" && EVIDENCE_SRC_BYTES="$EVIDENCE_SRC_BYTES" "$PY" - <<'PYEOF'
import os
import sys
from pathlib import Path

from sqlalchemy import func, select

from app.db import get_session_factory
from app.models.camera import Camera
from app.models.event import Event
from app.models.evidence import Evidence

session = get_session_factory()()
failures: list[str] = []
try:
    counts = {
        "cameras": session.execute(select(func.count()).select_from(Camera)).scalar_one(),
        "events": session.execute(select(func.count()).select_from(Event)).scalar_one(),
        "evidence": session.execute(select(func.count()).select_from(Evidence)).scalar_one(),
    }
    expected = {"cameras": 1, "events": 1, "evidence": 1}
    if counts != expected:
        failures.append(f"row counts {counts} != expected {expected}")

    # Referential integrity: every evidence row points at a real event (FK satisfied).
    orphan_evidence = session.execute(
        select(func.count())
        .select_from(Evidence)
        .outerjoin(Event, Evidence.event_id == Event.id)
        .where(Event.id.is_(None))
    ).scalar_one()
    if orphan_evidence:
        failures.append(f"{orphan_evidence} evidence row(s) reference a missing event")

    # Evidence accessibility after restore: the file resolves inside the root and matches.
    export = session.query(Evidence).one()
    if not export.relative_path:
        failures.append("restored evidence has no relative_path")
    else:
        root = Path(os.environ["EVIDENCE_DIR"]).resolve()
        path = root.joinpath(*export.relative_path.replace("\\", "/").split("/")).resolve()
        if root not in path.parents:
            failures.append("restored evidence path escapes the evidence root")
        elif not path.is_file():
            failures.append(f"restored evidence file missing: {path}")
        elif path.read_bytes() != os.environ["EVIDENCE_SRC_BYTES"].encode():
            failures.append("restored evidence bytes differ from the source")
finally:
    session.close()

if failures:
    print("FAIL: " + "; ".join(failures), file=sys.stderr)
    sys.exit(1)
print("    restored rows:", counts)
print("    referential integrity: OK")
print("    evidence file accessible and identical: OK")
PYEOF
)

SRC_REV="$(psql -h 127.0.0.1 -p "$PORT" -U postgres -d src -tAc 'SELECT version_num FROM alembic_version')"
DST_REV="$(psql -h 127.0.0.1 -p "$PORT" -U postgres -d dst -tAc 'SELECT version_num FROM alembic_version')"
if [[ "$SRC_REV" != "$DST_REV" ]]; then
    echo "FAIL: alembic revision mismatch (src=$SRC_REV dst=$DST_REV)" >&2
    exit 1
fi
echo "    alembic revision preserved: $DST_REV"

echo "PASS: backup/restore verified (structured data + evidence) on a disposable cluster"
