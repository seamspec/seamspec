"""Rule: a job is processed at most once, even if it is enqueued again with the same job_id."""

import sys
from pathlib import Path

sys.path.insert(0, str(next(p / "src" for p in Path(__file__).resolve().parents if (p / "src/jobqueue").is_dir())))

from jobqueue import Queue  # noqa: E402


def test_same_job_id_twice_runs_once() -> None:
    calls = []
    q = Queue(sleep=lambda s: None)
    q.enqueue({"n": 1}, job_id="a")
    q.enqueue({"n": 1}, job_id="a")
    q.run(calls.append)
    assert len(calls) == 1


def test_finished_job_is_not_run_again() -> None:
    calls = []
    q = Queue(sleep=lambda s: None)
    q.enqueue({"n": 1}, job_id="a")
    q.run(calls.append)
    q.enqueue({"n": 1}, job_id="a")
    q.run(calls.append)
    assert len(calls) == 1
