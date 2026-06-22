"""A minimal thread-safe circuit breaker.

States:
  - CLOSED   : calls flow through. Consecutive failures are counted.
  - OPEN      : calls fail fast (CircuitOpenError) until the cooldown elapses.
  - HALF_OPEN : a single trial call is allowed. Success closes the circuit;
                failure re-opens it.

The breaker protects the OCR backend (Azure Document Intelligence): when it is
repeatedly failing, we stop hammering it and let messages back off / retry
later instead of burning delivery attempts.
"""
from __future__ import annotations

import threading
import time


class CircuitOpenError(RuntimeError):
    """Raised when a call is attempted while the circuit is OPEN."""


class CircuitBreaker:
    def __init__(
        self,
        *,
        failure_threshold: int = 5,
        recovery_time: float = 30.0,
        name: str = "ocr",
    ) -> None:
        self._failure_threshold = failure_threshold
        self._recovery_time = recovery_time
        self._name = name

        self._lock = threading.Lock()
        self._failures = 0
        self._state = "CLOSED"
        self._opened_at = 0.0

    @property
    def state(self) -> str:
        return self._state

    def _allow(self) -> None:
        """Raise CircuitOpenError if calls are currently blocked."""
        with self._lock:
            if self._state == "OPEN":
                if time.monotonic() - self._opened_at >= self._recovery_time:
                    # Cooldown elapsed: allow a single trial call.
                    self._state = "HALF_OPEN"
                else:
                    raise CircuitOpenError(
                        f"Circuit '{self._name}' is OPEN; backing off."
                    )

    def _on_success(self) -> None:
        with self._lock:
            self._failures = 0
            self._state = "CLOSED"

    def _on_failure(self) -> None:
        with self._lock:
            self._failures += 1
            if self._state == "HALF_OPEN" or self._failures >= self._failure_threshold:
                self._state = "OPEN"
                self._opened_at = time.monotonic()

    def call(self, func, *args, **kwargs):
        """Run ``func`` through the breaker. Re-raises the original exception."""
        self._allow()
        try:
            result = func(*args, **kwargs)
        except Exception:
            self._on_failure()
            raise
        else:
            self._on_success()
            return result
