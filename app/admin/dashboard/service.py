"""The Dashboard's numbers (Super Admin and Admin story 2.1), as aggregate queries.

- **Needs Attention** counts what's open now: escalations not yet reviewed (by level, with no
  overdue count), open support requests (by type), deletion requests past their grace period
  and those close to their deadline, new knowledge gaps, and for the Super Admin content
  waiting for approval.
- **KPIs and graphs** cover the date range, in UTC days, with periods of a week (from Monday)
  or a month.
- **Super Admin only:** active subscribers, the free trial, subscribers over time and content
  to review. They're not worked out at all for an Admin.
- Teen Accounts: joined, invite sent and access paused are the teens package's
  (teens.service.dashboard_counts), and are what's true now; the graph counts the teen
  accounts that had joined by each period's end.

Approximations, recorded in docs/decisions/phase-a2-admin-operations.md: "active clients" are
clients with a session in use during the range; subscribers over time count subscriptions
started before and not ended by the end of each period, by their current plan.
"""

from datetime import UTC, date, datetime, timedelta
from typing import get_args

from sqlalchemy import Date, DateTime, and_, column, func, or_, select, values
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.accounts.models import OPEN_DELETION_STATUSES, DeletionRequest
from app.admin.common import day_start, is_teen, subscription_gives_access
from app.admin.dashboard.schemas import (
    DashboardOut,
    EscalationBreakdown,
    EscalationLevels,
    FreeTrial,
    Graphs,
    Interval,
    Kpis,
    NeedsAttention,
    Point,
    SubscriberPoint,
    Subscribers,
    SupportRequestKinds,
    TeenAccounts,
    TopicCount,
)
from app.auth.models import User, UserSession
from app.billing.models import Subscription
from app.conversations.models import Conversation, Escalation
from app.core.config import settings
from app.core.errors import AppError
from app.knowledge import service as knowledge
from app.knowledge.models import KnowledgeContent
from app.support import service as support
from app.teens import service as teens
from app.teens.models import TeenAccount

# Super Admin 2.1's messages.
NO_DATA = "There’s no data for this date range."
ALL_CAUGHT_UP = "You’re all caught up."
LOAD_FAILED = "We couldn’t load the dashboard. Please try again."
# Not in the stories (docs/decisions/phase-a2-admin-operations.md).
BAD_RANGE = "Please choose an end date on or after the start date."

DEFAULT_RANGE_DAYS = 30
# Ranges longer than this default to monthly periods.
WEEKLY_UP_TO_DAYS = 182


def _now() -> datetime:
    return datetime.now(UTC)


def _next_period(start: date, interval: Interval) -> date:
    if interval == "week":
        return start + timedelta(days=7)
    return (start.replace(day=28) + timedelta(days=4)).replace(day=1)


Period = tuple[date, datetime, datetime]  # (label, from, to)


def _periods(first_day: date, last_day: date, interval: Interval) -> list[Period]:
    """(label, from, to) for each period touching the range, clipped to the range."""
    start = (
        first_day - timedelta(days=first_day.weekday())
        if interval == "week"
        else first_day.replace(day=1)
    )
    range_from, range_to = day_start(first_day), day_start(last_day + timedelta(days=1))
    periods = []
    while start <= last_day:
        following = _next_period(start, interval)
        periods.append(
            (start, max(day_start(start), range_from), min(day_start(following), range_to))
        )
        start = following
    return periods


def _periods_table(periods: list[Period]):
    return values(
        column("period_start", Date),
        column("period_from", DateTime(timezone=True)),
        column("period_to", DateTime(timezone=True)),
        name="periods",
    ).data(periods)


def _adult_clients():
    return and_(User.role == "client", ~is_teen())


def _count(db: Session, query) -> int:
    return db.scalar(query) or 0


def _needs_attention(db: Session, admin: User, now: datetime) -> NeedsAttention:
    levels = dict(
        db.execute(
            select(Escalation.level, func.count())
            .where(Escalation.status == "not_reviewed")
            .group_by(Escalation.level)
        ).all()
    )
    open_requests = support.open_counts(db, admin)
    # 2.1's Deletion Requests card (6 Nov 19:22): requests past their grace period and waiting
    # for review, and how many of those are close to their 45-day deadline.
    open_deletions = and_(
        DeletionRequest.status.in_(OPEN_DELETION_STATUSES),
        DeletionRequest.locked_at.is_not(None),
    )
    pending = _count(db, select(func.count()).select_from(DeletionRequest).where(open_deletions))
    near_by = now + timedelta(days=settings.deletion_highlight_days)
    near = _count(
        db,
        select(func.count())
        .select_from(DeletionRequest)
        .where(
            open_deletions,
            DeletionRequest.status != "on_legal_hold",
            DeletionRequest.due_at <= near_by,
        ),
    )
    gaps = knowledge.new_gap_count(db)
    content = None
    if admin.role == "super_admin":
        content = _count(
            db,
            select(func.count())
            .select_from(KnowledgeContent)
            .where(KnowledgeContent.status == "pending_approval"),
        )
    escalations = EscalationLevels(
        **{level: levels.get(level, 0) for level in ("emergency", "crisis", "urgent")}
    )
    requests = SupportRequestKinds(**open_requests)
    all_clear = (
        sum(levels.values()) == 0
        and sum(open_requests.values()) == 0
        and pending == 0
        and gaps == 0
        and not content
    )
    return NeedsAttention(
        escalations_not_reviewed=escalations,
        support_requests_open=requests,
        deletion_requests_pending=pending,
        deletion_requests_near_deadline=near,
        knowledge_gaps_new=gaps,
        content_pending_approval=content,
        all_clear=all_clear,
        message=ALL_CAUGHT_UP if all_clear else None,
    )


def _kpis(
    db: Session, admin: User, range_from: datetime, range_to: datetime, now: datetime
) -> Kpis:
    registered = _count(
        db,
        select(func.count()).select_from(User).where(_adult_clients(), User.created_at < range_to),
    )
    active = _count(
        db,
        select(func.count(func.distinct(UserSession.user_id)))
        .join(User, User.id == UserSession.user_id)
        .where(
            _adult_clients(),
            UserSession.created_at < range_to,
            UserSession.last_seen_at >= range_from,
        ),
    )
    conversations = _count(
        db,
        select(func.count())
        .select_from(Conversation)
        .where(Conversation.created_at >= range_from, Conversation.created_at < range_to),
    )
    in_range = and_(Escalation.detected_at >= range_from, Escalation.detected_at < range_to)
    escalations = _count(db, select(func.count()).select_from(Escalation).where(in_range))
    not_reviewed = _count(
        db,
        select(func.count())
        .select_from(Escalation)
        .where(in_range, Escalation.status == "not_reviewed"),
    )
    kpis = Kpis(
        total_registered_clients=registered,
        active_clients=active,
        total_conversations=conversations,
        escalations=escalations,
        escalations_not_reviewed=not_reviewed,
        teen_accounts=TeenAccounts(**teens.dashboard_counts(db)),
    )
    if admin.role == "super_admin":
        plans = dict(
            db.execute(
                select(Subscription.plan, func.count())
                .where(subscription_gives_access(now))
                .group_by(Subscription.plan)
            ).all()
        )
        kpis.active_subscribers = Subscribers(
            individual=plans.get("individual", 0), family=plans.get("family", 0)
        )
        on_trial = _count(
            db,
            select(func.count())
            .select_from(User)
            .outerjoin(Subscription, Subscription.account_id == User.id)
            .where(_adult_clients(), Subscription.id.is_(None), User.trial_ends_at > now),
        )
        converted = _count(
            db,
            select(func.count())
            .select_from(Subscription)
            .where(Subscription.started_at >= range_from, Subscription.started_at < range_to),
        )
        kpis.free_trial = FreeTrial(current=on_trial, converted=converted)
    return kpis


def _graphs(
    db: Session,
    admin: User,
    periods: list[Period],
    range_from: datetime,
    range_to: datetime,
) -> Graphs:
    table = _periods_table(periods)
    growth = dict(
        db.execute(
            select(table.c.period_start, func.count(User.id))
            .select_from(table)
            .outerjoin(User, and_(User.created_at < table.c.period_to, _adult_clients()))
            .group_by(table.c.period_start)
        ).all()
    )
    started = dict(
        db.execute(
            select(table.c.period_start, func.count(Conversation.id))
            .select_from(table)
            .outerjoin(
                Conversation,
                and_(
                    Conversation.created_at >= table.c.period_from,
                    Conversation.created_at < table.c.period_to,
                ),
            )
            .group_by(table.c.period_start)
        ).all()
    )
    topic = func.lower(func.trim(Conversation.topic))
    topics = db.execute(
        select(topic, func.count())
        .where(
            Conversation.topic.is_not(None),
            func.trim(Conversation.topic) != "",
            Conversation.created_at >= range_from,
            Conversation.created_at < range_to,
        )
        .group_by(topic)
        # Only topics enough clients asked about, so a rare one can't point to a person.
        .having(func.count() >= settings.dashboard_topic_min_count)
        .order_by(func.count().desc(), topic)
        .limit(settings.dashboard_topic_limit)
    ).all()
    in_range = and_(Escalation.detected_at >= range_from, Escalation.detected_at < range_to)
    by_status = dict(
        db.execute(
            select(Escalation.status, func.count()).where(in_range).group_by(Escalation.status)
        ).all()
    )
    by_level = dict(
        db.execute(
            select(Escalation.level, func.count()).where(in_range).group_by(Escalation.level)
        ).all()
    )
    # Teen accounts (still teens: one that became an adult account has no TeenAccount row) that
    # had joined by each period's end.
    joined = dict(
        db.execute(
            select(table.c.period_start, func.count(TeenAccount.account_id))
            .select_from(table)
            .outerjoin(TeenAccount, TeenAccount.joined_at < table.c.period_to)
            .group_by(table.c.period_start)
        ).all()
    )
    graphs = Graphs(
        client_growth=[Point(period_start=p[0], value=growth.get(p[0], 0)) for p in periods],
        conversations_over_time=[
            Point(period_start=p[0], value=started.get(p[0], 0)) for p in periods
        ],
        top_health_topics=[TopicCount(topic=name, conversations=count) for name, count in topics],
        escalation_breakdown=EscalationBreakdown(
            not_reviewed=by_status.get("not_reviewed", 0),
            reviewed=by_status.get("reviewed", 0),
            emergency=by_level.get("emergency", 0),
            crisis=by_level.get("crisis", 0),
            urgent=by_level.get("urgent", 0),
        ),
        teen_accounts_over_time=[
            Point(period_start=p[0], value=joined.get(p[0], 0)) for p in periods
        ],
    )
    if admin.role == "super_admin":
        active_then = and_(
            Subscription.started_at < table.c.period_to,
            or_(Subscription.ended_at.is_(None), Subscription.ended_at >= table.c.period_to),
        )
        counts: dict[tuple[date, str], int] = {
            (period, plan): count
            for period, plan, count in db.execute(
                select(table.c.period_start, Subscription.plan, func.count())
                .select_from(table)
                .join(Subscription, active_then)
                .group_by(table.c.period_start, Subscription.plan)
            ).all()
        }
        graphs.subscribers_over_time = [
            SubscriberPoint(
                period_start=p[0],
                individual=counts.get((p[0], "individual"), 0),
                family=counts.get((p[0], "family"), 0),
            )
            for p in periods
        ]
    return graphs


def dashboard(
    db: Session,
    admin: User,
    date_from: date | None,
    date_to: date | None,
    interval: Interval | None,
) -> DashboardOut:
    """Super Admin and Admin 2.1. The range defaults to the last 30 days (UTC); the periods
    to weeks, or months for ranges over about six months."""
    date_to = date_to or _now().date()
    date_from = date_from or date_to - timedelta(days=DEFAULT_RANGE_DAYS - 1)
    if date_from > date_to:
        raise AppError(422, "invalid_date_range", BAD_RANGE, "date_from")
    if interval not in get_args(Interval):
        interval = "week" if (date_to - date_from).days < WEEKLY_UP_TO_DAYS else "month"
    range_from, range_to = day_start(date_from), day_start(date_to + timedelta(days=1))
    now = _now()
    try:
        needs = _needs_attention(db, admin, now)
        kpis = _kpis(db, admin, range_from, range_to, now)
        graphs = _graphs(db, admin, _periods(date_from, date_to, interval), range_from, range_to)
        signed_up = _count(
            db,
            select(func.count())
            .select_from(User)
            .where(_adult_clients(), User.created_at >= range_from, User.created_at < range_to),
        )
    except SQLAlchemyError:
        db.rollback()
        raise AppError(503, "dashboard_unavailable", LOAD_FAILED) from None
    empty = not any(
        (signed_up, kpis.active_clients, kpis.total_conversations, kpis.escalations)
    ) and not (kpis.free_trial and kpis.free_trial.converted)
    return DashboardOut(
        date_from=date_from,
        date_to=date_to,
        interval=interval,
        needs_attention=needs,
        kpis=kpis,
        graphs=graphs,
        message=NO_DATA if empty else None,
    )
