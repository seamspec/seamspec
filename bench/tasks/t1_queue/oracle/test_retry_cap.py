"""Rule: the retry delay never exceeds 30 seconds."""

import sys
from pathlib import Path

sys.path.insert(0, str(next(p / "src" for p in Path(__file__).resolve().parents if (p / "src/jobqueue").is_dir())))

from jobqueue import Queue, backoff_delay  # noqa: E402


def test_no_delay_above_30s_for_any_attempt_or_base() -> None:
    for base in (0.1, 0.5, 1.0, 2.0):
        for attempt in range(0, 64):
            assert backoff_delay(attempt, base) <= 30.0


def test_long_outage_never_waits_more_than_30s() -> None:
    sleeps: list[float] = []
    failures = {"left": 25}

    def flaky(payload):
        if failures["left"]:
            failures["left"] -= 1
            raise ConnectionError("upstream down")

    q = Queue(sleep=sleeps.append)
    q.enqueue({"order": 7}, max_attempts=30)
    q.run(flaky)
    assert sleeps, "the job was never retried"
    assert max(sleeps) <= 30.0
