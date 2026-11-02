"""Command-line administration utilities.

Usage::

    python -m app.cli create-admin --username admin
    CHRONOVISION_ADMIN_PASSWORD=... python -m app.cli create-admin --username admin
    python -m app.cli prune-evidence [--dry-run]

The password is read from stdin or an environment variable, or prompted for
interactively. It is never accepted as a plain command-line argument and is never
written to logs.
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys

from app.db import dispose_engine, get_session_factory
from app.services.admin_service import AdminError, create_admin

PASSWORD_ENV_VAR = "CHRONOVISION_ADMIN_PASSWORD"


def _resolve_password(args: argparse.Namespace) -> str:
    """Obtain the admin password from stdin, the environment, or an interactive prompt."""
    if args.password_stdin:
        return sys.stdin.readline().rstrip("\n")
    env_password = os.environ.get(PASSWORD_ENV_VAR)
    if env_password:
        return env_password
    first = getpass.getpass("Admin password: ")
    second = getpass.getpass("Confirm password: ")
    if first != second:
        raise AdminError("passwords do not match")
    return first


def _create_admin_command(args: argparse.Namespace) -> int:
    try:
        password = _resolve_password(args)
    except AdminError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    db = get_session_factory()()
    try:
        user = create_admin(db, args.username, password)
    except AdminError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        db.close()
        dispose_engine()

    print(f"created administrator {user.username!r} (id={user.id})")
    return 0


def _prune_evidence_command(args: argparse.Namespace) -> int:
    from app.services import evidence_service

    db = get_session_factory()()
    try:
        if args.dry_run:
            report = _dry_run_retention(db)
        else:
            report = evidence_service.run_retention(db)
    finally:
        db.close()
        dispose_engine()

    prefix = "would delete" if args.dry_run else "deleted"
    print(f"{prefix} {report.deleted} evidence item(s); freed {report.bytes_freed} bytes")
    print(f"remaining {report.remaining_bytes} bytes; protected {report.protected_count}")
    if report.blocked_by_protection:
        print("storage cap still exceeded: remaining candidates are all protected")
    return 0


def _dry_run_retention(db):
    """Compute the retention plan without deleting anything.

    Runs the real policy against a rolled-back transaction so the reported effect matches a
    real run, then discards it.
    """
    from app.services import evidence_service

    report = evidence_service.run_retention(db)
    db.rollback()
    return report


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser."""
    parser = argparse.ArgumentParser(prog="chronovision-admin")
    subparsers = parser.add_subparsers(dest="command", required=True)

    create = subparsers.add_parser("create-admin", help="create the initial administrator account")
    create.add_argument("--username", required=True, help="administrator username")
    create.add_argument(
        "--password-stdin",
        action="store_true",
        help="read the password from stdin instead of prompting",
    )
    create.set_defaults(func=_create_admin_command)

    prune = subparsers.add_parser(
        "prune-evidence",
        help="apply evidence retention (time window + storage cap)",
    )
    prune.add_argument(
        "--dry-run",
        action="store_true",
        help="report what would be deleted without changing anything",
    )
    prune.set_defaults(func=_prune_evidence_command)
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns a process exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
