"""Tests for the in-memory login rate limiter."""

from __future__ import annotations

from app.auth.rate_limit import LoginRateLimiter, login_rate_limit_key


class FakeClock:
    """A controllable monotonic clock for deterministic window tests."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def test_allows_up_to_max_attempts_then_blocks() -> None:
    limiter = LoginRateLimiter(max_attempts=3, window_seconds=60)
    assert limiter.allow("k") is True
    for _ in range(3):
        limiter.record_failure("k")
    assert limiter.allow("k") is False


def test_reset_clears_failures() -> None:
    limiter = LoginRateLimiter(max_attempts=1, window_seconds=60)
    limiter.record_failure("k")
    assert limiter.allow("k") is False
    limiter.reset("k")
    assert limiter.allow("k") is True


def test_window_expiry_frees_capacity() -> None:
    clock = FakeClock()
    limiter = LoginRateLimiter(max_attempts=2, window_seconds=30, clock=clock)
    limiter.record_failure("k")
    limiter.record_failure("k")
    assert limiter.allow("k") is False
    clock.advance(31)
    assert limiter.allow("k") is True


def test_retry_after_reports_remaining_window() -> None:
    clock = FakeClock()
    limiter = LoginRateLimiter(max_attempts=1, window_seconds=60, clock=clock)
    assert limiter.retry_after("k") == 0
    limiter.record_failure("k")
    assert limiter.retry_after("k") > 0


def test_keys_are_isolated() -> None:
    limiter = LoginRateLimiter(max_attempts=1, window_seconds=60)
    limiter.record_failure("a")
    assert limiter.allow("a") is False
    assert limiter.allow("b") is True


def test_login_rate_limit_key_normalises() -> None:
    assert login_rate_limit_key("127.0.0.1", " Admin ") == "127.0.0.1|admin"
    assert login_rate_limit_key(None, "admin") == "unknown|admin"
