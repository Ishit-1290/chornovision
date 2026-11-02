"""Shared fixtures for the vision-worker tests.

The vision modules reuse :func:`app.config.get_settings` for the SSRF policy and the internal
token, so the backend test secrets are placed in the environment before those modules are
imported. Unlike the backend suite, they are left in place (the vision worker genuinely needs
them at runtime).
"""

from __future__ import annotations

import os

_TEST_ENV = {
    "POSTGRES_PASSWORD": "test-postgres-password-" + "x" * 24,
    "SECRET_KEY": "test-secret-key-" + "y" * 32,
    "INTERNAL_API_TOKEN": "test-internal-token-" + "z" * 32,
    "ENVIRONMENT": "test",
}

for _key, _value in _TEST_ENV.items():
    os.environ.setdefault(_key, _value)

from collections.abc import Iterator  # noqa: E402

import pytest  # noqa: E402
from app.config import clear_settings_cache  # noqa: E402
from app.services.worker_registry import reset_worker_registry  # noqa: E402

from vision.config import clear_vision_settings_cache  # noqa: E402


@pytest.fixture(autouse=True)
def _clean_caches() -> Iterator[None]:
    clear_settings_cache()
    clear_vision_settings_cache()
    reset_worker_registry()
    try:
        yield
    finally:
        clear_settings_cache()
        clear_vision_settings_cache()
        reset_worker_registry()
