"""Runs background jobs. Start it next to the API with: uv run python -m app.worker

Register a handler for each job kind with @handles("kind"). A job left "running" by a worker
that crashed isn't retried automatically yet; reset its status to "pending" by hand.
"""

import logging
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.core.jobs import claim_next

logger = logging.getLogger("app.worker")

MAX_ATTEMPTS = 5
POLL_SECONDS = 2

Handler = Callable[[Session, dict[str, Any]], None]
HANDLERS: dict[str, Handler] = {}


def handles(kind: str) -> Callable[[Handler], Handler]:
    """Decorator that registers a function as the handler for one job kind."""

    def register(func: Handler) -> Handler:
        HANDLERS[kind] = func
        return func

    return register


StartupHook = Callable[[Session], None]
STARTUP_HOOKS: list[StartupHook] = []


def on_startup(func: StartupHook) -> StartupHook:
    """Decorator for a function the worker runs once when it starts, after loading handlers:
    for example, to queue the first run of a job that repeats itself. It commits its own work,
    and must be safe to run again each time a worker starts."""
    STARTUP_HOOKS.append(func)
    return func


def run_once(db: Session) -> bool:
    """Run the next due job, if there is one. Returns False when there was nothing to do."""
    job = claim_next(db)
    if job is None:
        return False
    db.commit()  # saves the "running" status, so other workers skip this job

    try:
        HANDLERS[job.kind](db, job.payload)
    except Exception as exc:
        db.rollback()  # undo whatever the handler half-did
        job.last_error = type(exc).__name__  # the type only: messages can contain health data
        if job.attempts >= MAX_ATTEMPTS:
            job.status = "failed"
        else:
            job.status = "pending"
            job.run_at = datetime.now(UTC) + timedelta(minutes=5 * job.attempts)
        logger.error(
            "Job %s (%s) failed on attempt %s: %s",
            job.id,
            job.kind,
            job.attempts,
            type(exc).__name__,
        )
    else:
        job.status = "done"
    db.commit()
    return True


def load_handlers() -> None:
    """Imports the modules that register handlers. They import `handles` from here, so they
    can't be imported at the top of this module."""
    import app.admin.jobs  # noqa: F401
    import app.admin.notifications.jobs  # noqa: F401
    import app.auth.jobs  # noqa: F401
    import app.billing.jobs  # noqa: F401
    import app.conversations.jobs  # noqa: F401
    import app.notifications.jobs  # noqa: F401
    import app.privacy.jobs  # noqa: F401
    import app.support.jobs  # noqa: F401
    import app.teens.jobs  # noqa: F401
    import app.visits.jobs  # noqa: F401
    import app.wellness.jobs  # noqa: F401


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    load_handlers()
    logger.info("Worker started. Handlers: %s", ", ".join(HANDLERS) or "none yet")
    for hook in STARTUP_HOOKS:
        with SessionLocal() as db:
            hook(db)
    while True:
        with SessionLocal() as db:
            did_work = run_once(db)
        if not did_work:
            time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    # `python -m app.worker` runs this file as `__main__`, a second copy of the module. The job
    # modules register their handlers (and startup hooks) on `app.worker`, so run that copy's
    # main, or this one would see no handlers at all.
    import app.worker

    app.worker.main()
