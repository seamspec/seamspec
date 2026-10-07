"""Rule: existing calls to Queue.enqueue(payload, *, job_id=None, max_attempts=5) keep working."""

import sys
from pathlib import Path

sys.path.insert(0, str(next(p / "src" for p in Path(__file__).resolve().parents if (p / "src/jobqueue").is_dir())))

from jobqueue import Queue  # noqa: E402


def test_payload_positional_and_keyword_options() -> None:
    received = []
    q = Queue(sleep=lambda s: None)
    first = q.enqueue({"user": 1})
    second = q.enqueue({"user": 2}, job_id="pay-42")
    third = q.enqueue({"user": 3}, max_attempts=1)
    fourth = q.enqueue({"user": 4}, job_id="pay-43", max_attempts=3)
    assert all(isinstance(j, str) for j in (first, second, third, fourth))
    assert second == "pay-42" and fourth == "pay-43"
    q.run(received.append)
    assert {"user": 2} in received and {"user": 4} in received  # payload reaches the handler unchanged


def test_max_attempts_is_respected() -> None:
    calls = []

    def always_fails(payload):
        calls.append(payload)
        raise RuntimeError("no")

    q = Queue(sleep=lambda s: None)
    q.enqueue({"z": 1}, max_attempts=2)
    q.run(always_fails)
    assert len(calls) == 2
