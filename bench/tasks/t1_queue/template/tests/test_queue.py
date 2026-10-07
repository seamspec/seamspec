from jobqueue import Queue, backoff_delay


def test_backoff_grows() -> None:
    assert backoff_delay(0) < backoff_delay(1) < backoff_delay(2)


def test_jobs_run_in_order() -> None:
    seen = []
    q = Queue(sleep=lambda s: None)
    q.enqueue({"n": 1})
    q.enqueue({"n": 2})
    q.run(lambda p: seen.append(p["n"]))
    assert seen == [1, 2]


def test_failing_job_is_retried_then_given_up() -> None:
    calls = []

    def handler(p):
        calls.append(p)
        raise RuntimeError("boom")

    q = Queue(sleep=lambda s: None)
    jid = q.enqueue({"x": 1}, max_attempts=3)
    assert q.run(handler) == []
    assert len(calls) == 3 and jid in q.failed()
