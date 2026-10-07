"""Jobs are handed to a handler; failures are retried with exponential backoff."""

from __future__ import annotations

import itertools
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

MAX_DELAY = 30.0  # seconds

Handler = Callable[[dict[str, Any]], None]


def backoff_delay(attempt: int, base: float = 0.5) -> float:
    """Seconds to wait before retry number `attempt` (0-based)."""
    return min(base * 2**attempt, MAX_DELAY)


@dataclass
class Job:
    id: str
    payload: dict[str, Any]
    max_attempts: int = 5
    attempts: int = 0
    errors: list[str] = field(default_factory=list)


class Queue:
    """FIFO queue. `run()` processes everything that is waiting."""

    def __init__(self, sleep: Callable[[float], None] = time.sleep) -> None:
        self._waiting: deque[Job] = deque()
        self._done: set[str] = set()
        self._failed: dict[str, Job] = {}
        self._ids = itertools.count(1)
        self._sleep = sleep

    def enqueue(self, payload: dict[str, Any], *, job_id: str | None = None, max_attempts: int = 5) -> str:
        """Add a job and return its id. A job id that already succeeded is ignored."""
        jid = job_id or f"job-{next(self._ids)}"
        if jid not in self._done:
            self._waiting.append(Job(jid, dict(payload), max_attempts))
        return jid

    def run(self, handler: Handler) -> list[str]:
        """Process waiting jobs; return the ids that succeeded in this call."""
        succeeded: list[str] = []
        while self._waiting:
            job = self._waiting.popleft()
            if job.id in self._done:
                continue
            while True:
                try:
                    handler(job.payload)
                except Exception as exc:  # noqa: BLE001 - any handler error is retried
                    job.errors.append(repr(exc))
                    job.attempts += 1
                    if job.attempts >= job.max_attempts:
                        self._failed[job.id] = job
                        break
                    self._sleep(backoff_delay(job.attempts - 1))
                else:
                    self._done.add(job.id)
                    succeeded.append(job.id)
                    break
        return succeeded

    def failed(self) -> dict[str, Job]:
        return dict(self._failed)
