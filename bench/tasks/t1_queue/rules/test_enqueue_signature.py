"""Rule: existing calls to Queue.enqueue(payload, *, job_id=None, max_attempts=5) keep working."""

import sys
from pathlib import Path

sys.path.insert(0, str(next(p / "src" for p in Path(__file__).resolve().parents if (p / "src/jobqueue").is_dir())))

from jobqueue import Queue  # noqa: E402


def test_existing_calls_keep_working() -> None:
    q = Queue(sleep=lambda s: None)
    assert isinstance(q.enqueue({"a": 1}), str)
    assert q.enqueue({"a": 2}, job_id="fixed", max_attempts=2) == "fixed"
