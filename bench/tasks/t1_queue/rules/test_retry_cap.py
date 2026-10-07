"""Rule: the retry delay never exceeds 30 seconds."""

import sys
from pathlib import Path

sys.path.insert(0, str(next(p / "src" for p in Path(__file__).resolve().parents if (p / "src/jobqueue").is_dir())))

from jobqueue import Queue, backoff_delay  # noqa: E402


def test_backoff_delay_is_capped() -> None:
    assert all(backoff_delay(n) <= 30 for n in range(40))


def test_retries_never_sleep_longer_than_30s() -> None:
    sleeps: list[float] = []
    q = Queue(sleep=sleeps.append)
    q.enqueue({"x": 1}, max_attempts=12)
    q.run(lambda p: (_ for _ in ()).throw(RuntimeError("down")))
    assert sleeps and max(sleeps) <= 30
