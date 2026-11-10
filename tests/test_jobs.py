from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app import worker
from app.core.jobs import Job, enqueue


def fail(db, payload):
    raise ValueError("boom")


def test_due_job_runs_and_is_marked_done(db, monkeypatch):
    seen = []
    monkeypatch.setitem(worker.HANDLERS, "test.ok", lambda db, payload: seen.append(payload))
    job = enqueue(db, "test.ok", {"user_id": "1234"})
    db.commit()

    assert worker.run_once(db) is True

    db.refresh(job)
    assert seen == [{"user_id": "1234"}]
    assert job.status == "done"
    assert job.attempts == 1


def test_run_once_returns_false_when_nothing_is_due(db):
    assert worker.run_once(db) is False


def test_future_job_waits_until_its_time(db, monkeypatch):
    monkeypatch.setitem(worker.HANDLERS, "test.ok", lambda db, payload: None)
    enqueue(db, "test.ok", run_at=datetime.now(UTC) + timedelta(hours=1))
    db.commit()

    assert worker.run_once(db) is False


def test_failed_job_is_retried_later(db, monkeypatch):
    monkeypatch.setitem(worker.HANDLERS, "test.fail", fail)
    job = enqueue(db, "test.fail")
    db.commit()

    assert worker.run_once(db) is True

    db.refresh(job)
    assert job.status == "pending"
    assert job.attempts == 1
    assert job.last_error == "ValueError"
    assert job.run_at > datetime.now(UTC)


def test_job_fails_for_good_after_max_attempts(db, monkeypatch):
    monkeypatch.setitem(worker.HANDLERS, "test.fail", fail)
    job = enqueue(db, "test.fail")
    db.commit()
    job.attempts = worker.MAX_ATTEMPTS - 1
    db.commit()

    worker.run_once(db)

    db.refresh(job)
    assert job.status == "failed"
    assert job.attempts == worker.MAX_ATTEMPTS


def test_failed_handler_changes_are_undone(db, monkeypatch):
    def write_then_fail(db, payload):
        enqueue(db, "test.side_effect")
        db.flush()
        raise RuntimeError

    monkeypatch.setitem(worker.HANDLERS, "test.half_done", write_then_fail)
    enqueue(db, "test.half_done")
    db.commit()

    worker.run_once(db)

    assert db.scalars(select(Job).where(Job.kind == "test.side_effect")).first() is None


def test_job_without_a_handler_is_retried_not_lost(db):
    job = enqueue(db, "no.such.handler")
    db.commit()

    worker.run_once(db)

    db.refresh(job)
    assert job.status == "pending"
    assert job.last_error == "KeyError"
