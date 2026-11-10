"""The Dashboard (Super Admin and Admin story 2.1). Only counts: no client's or teen's name,
conversation or health information. The Super Admin's extra metrics are None for Admins, and
the endpoint leaves None fields out, so they're never sent to an Admin's screen."""

from datetime import date
from typing import Literal

from pydantic import BaseModel

Interval = Literal["week", "month"]


class EscalationLevels(BaseModel):
    emergency: int
    crisis: int
    urgent: int


class SupportRequestKinds(BaseModel):
    talk_to_support: int
    consultation: int
    knowledge_gap: int
    email_change: int


class NeedsAttention(BaseModel):
    """What's open now, whatever the date range."""

    escalations_not_reviewed: EscalationLevels
    support_requests_open: SupportRequestKinds
    # Deletion requests past their grace period and waiting for review (2.1, 5.2).
    deletion_requests_pending: int
    # Of those, due within settings.deletion_highlight_days (not counting legal holds).
    deletion_requests_near_deadline: int
    knowledge_gaps_new: int
    content_pending_approval: int | None = None  # Super Admin only
    all_clear: bool
    message: str | None = None  # "You’re all caught up."


class TeenAccounts(BaseModel):
    joined: int
    invite_sent: int
    access_paused: int


class Subscribers(BaseModel):
    individual: int
    family: int


class FreeTrial(BaseModel):
    current: int  # clients on the free trial now
    converted: int  # subscriptions started within the date range


class Kpis(BaseModel):
    total_registered_clients: int
    active_clients: int
    total_conversations: int
    escalations: int
    escalations_not_reviewed: int
    teen_accounts: TeenAccounts
    active_subscribers: Subscribers | None = None  # Super Admin only
    free_trial: FreeTrial | None = None  # Super Admin only


class Point(BaseModel):
    period_start: date
    value: int


class SubscriberPoint(BaseModel):
    period_start: date
    individual: int
    family: int


class TopicCount(BaseModel):
    topic: str
    conversations: int


class EscalationBreakdown(BaseModel):
    not_reviewed: int
    reviewed: int
    emergency: int
    crisis: int
    urgent: int


class Graphs(BaseModel):
    client_growth: list[Point]  # registered clients at the end of each period
    conversations_over_time: list[Point]  # conversations started in each period
    top_health_topics: list[TopicCount]  # highest first
    escalation_breakdown: EscalationBreakdown
    teen_accounts_over_time: list[Point]  # joined teen accounts at the end of each period
    subscribers_over_time: list[SubscriberPoint] | None = None  # Super Admin only


class DashboardOut(BaseModel):
    date_from: date
    date_to: date
    interval: Interval
    needs_attention: NeedsAttention
    kpis: Kpis
    graphs: Graphs
    message: str | None = None  # "There’s no data for this date range."
