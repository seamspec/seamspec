"""Rule: a job is processed at most once, even if it is enqueued again with the same job_id."""

import sys
from pathlib import Path

sys.path.insert(0, str(next(p / "src" for p in Path(__file__).resolve().parents if (p / "src/jobqueue").is_dir())))

import threading  # noqa: E402

from jobqueue import Queue  # noqa: E402


def test_each_job_id_succeeds_exactly_once_under_duplicates() -> None:
    seen: dict[str, int] = {}
    lock = threading.Lock()

    def handler(payload):
        with lock:
            seen[payload["id"]] = seen.get(payload["id"], 0) + 1

    q = Queue(sleep=lambda s: None)
    for i in range(200):
        jid = f"j{i % 50}"
        q.enqueue({"id": jid}, job_id=jid)
    q.run(handler)
    for i in range(50):
        q.enqueue({"id": f"j{i}"}, job_id=f"j{i}")
    q.run(handler)
    assert seen and all(count == 1 for count in seen.values()), seen
    assert len(seen) == 50


def test_a_retried_job_is_not_run_again_after_it_succeeded() -> None:
    calls = []
    state = {"fail": 2}

    def handler(payload):
        calls.append(payload)
        if state["fail"]:
            state["fail"] -= 1
            raise RuntimeError("try again")

    q = Queue(sleep=lambda s: None)
    q.enqueue({"k": 1}, job_id="r")
    q.run(handler)
    q.enqueue({"k": 1}, job_id="r")
    q.run(handler)
    assert len(calls) == 3  # two failures, one success, never again
