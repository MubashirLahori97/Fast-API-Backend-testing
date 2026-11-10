"""Story 3.2: acting on the safety check.

`check_message_safety` (service.py) checks every client message, before any reply and before
the Health Consent. When it finds an urgent, emergency or crisis concern, `record_escalation`
runs in the same transaction that stores the level, so it happens exactly once per message. It:

- adds the story's advice to the conversation as an Oracle line, to show straight away;
- records an escalation for the support team to review (Super Admin story 4.1);
- for an emergency or a crisis, opens a safety hold on the conversation. No reply is given
  there until the client picks one of the story's options (`close_holds`). Messages sent
  during the hold are saved and checked, but get no reply, and the conversation can't be
  deleted. Urgent advice opens no hold: the conversation carries on.

Nobody follows up with the client afterwards: Phase 9 asks `check_ins_blocked` before sending
anything. Escalations and audit events hold ids, never message text or the check's reason.
The decisions are in docs/decisions/r3-conversations-and-3.2.md.
"""

import uuid
from datetime import UTC, datetime

from fastapi import Request
from sqlalchemy import case, select
from sqlalchemy.orm import Session

from app.auth.models import User
from app.conversations.models import Escalation, Message
from app.conversations.schemas import (
    EscalationLevel,
    MessageOut,
    SafetyAdviceOut,
    SafetyHoldOut,
    SafetyOption,
    SafetyOptionOut,
)
from app.core import audit
from app.core.errors import AppError, database_errors_retryable
from app.core.schemas import clean_line
from app.oracle.contract import SafetyCheck
from app.profiles.models import Profile

# Story 3.2's messages.
EMERGENCY = "This could be a medical emergency. Please call 911 now."
CRISIS = (
    "I’m really glad you told me. You don’t have to go through this alone. Please call or text "
    "988 to talk to someone now. If you’re in immediate danger, call 911."
)
URGENT = (
    "This is something to get checked soon. Please contact your provider within the next 24 hours."
)
OUTSIDE_US = "Please call your local emergency number now."
OPTION_NOT_SELECTED = "Please let me know you’re safe before we continue."

# Not in the stories (docs/decisions/r3-conversations-and-3.2.md).
EMERGENCY_OPENING = "This could be a medical emergency."  # the first sentence of EMERGENCY
CRISIS_OPENING = "I’m really glad you told me. You don’t have to go through this alone."
# For a family member, after 3.2's “Call 911 for [Name] now.”
EMERGENCY_FOR = "This could be a medical emergency. Please call 911 for {name} now."
URGENT_FOR = (
    "This is something to get checked soon. Please contact {name}’s provider within the next 24 "
    "hours."
)
POISON_CONTROL = (
    "For a poisoning or an overdose, you can also call Poison Control at 1-800-222-1222."
)
NO_SAFETY_HOLD = "You’ve already answered this. Let’s carry on."
# Super Admin story 4.1, for the admin endpoints of Phase A.
ESCALATION_NOT_FOUND = "We couldn’t find that escalation."
MARKED_AS_REVIEWED = "This escalation has been marked as reviewed."

HOLD_LEVELS = ("emergency", "crisis")
OPTION_LABELS: dict[SafetyOption, str] = {
    "called_for_help": "I’ve called for help",
    "reached_out": "I’ve reached out for help",
    "safe_now": "I’m safe now",
}
HOLD_OPTIONS: dict[str, tuple[SafetyOption, ...]] = {
    "emergency": ("called_for_help", "safe_now"),
    "crisis": ("reached_out", "safe_now"),
}
REASON_MAX_LENGTH = 200


def _family_name(profile: Profile) -> str | None:
    """The family member's first name for the advice, which speaks to their advocate."""
    if profile.is_self:
        return None
    return clean_line(profile.first_name or "") or None


def advice_text(level: str, *, name: str | None, outside_us: bool, poison_control: bool) -> str:
    """The story's advice for a level. `name` is a family member's: the advice then speaks to
    their advocate. Outside the US there's no 911, 988 or Poison Control, only "Please call your
    local emergency number now." (988 included: it's a US line, question 26)."""
    if level == "urgent":
        text = URGENT if name is None else URGENT_FOR.format(name=name)
    elif outside_us:
        opening = EMERGENCY_OPENING if level == "emergency" else CRISIS_OPENING
        return f"{opening} {OUTSIDE_US}"
    elif level == "emergency":
        text = EMERGENCY if name is None else EMERGENCY_FOR.format(name=name)
    else:
        text = CRISIS
    if poison_control and not outside_us:
        text = f"{text} {POISON_CONTROL}"
    return text


def _profile_type(db: Session, profile: Profile) -> str:
    """Kept on the escalation for when the profile is gone (Super Admin 4.1's profile type):
    a teen with their own account (story 1.5) is "teen", whose own profile it always is."""
    account = db.get(User, profile.account_id)
    if account is not None and account.account_type == "teen":
        return "teen"
    return "self" if profile.is_self else "family_member"


def safety_reason(check: SafetyCheck) -> str | None:
    """The check's reason, cleaned and capped, to store with the message."""
    if not isinstance(check.reason, str):
        return None
    return clean_line(check.reason)[:REASON_MAX_LENGTH] or None


def record_escalation(
    db: Session, message: Message, profile: Profile, check: SafetyCheck
) -> Escalation:
    """Adds the advice line and the escalation for a message whose check found an urgent,
    emergency or crisis concern. Called only by the check that stored the message's level,
    inside its transaction; the caller commits."""
    poison_control = bool(check.poison_control) and not message.outside_us
    line = Message(
        conversation_id=message.conversation_id,
        role="oracle",
        text=advice_text(
            check.level,
            name=_family_name(profile),
            outside_us=message.outside_us,
            poison_control=poison_control,
        ),
    )
    db.add(line)
    db.flush()
    escalation = Escalation(
        account_id=profile.account_id,
        profile_id=profile.id,
        profile_type=_profile_type(db, profile),
        conversation_id=message.conversation_id,
        message_id=message.id,
        response_message_id=line.id,
        level=check.level,
        outside_us=message.outside_us,
        poison_control=poison_control,
    )
    db.add(escalation)
    db.flush()
    # No actor, level or profile: the event alone mustn't say whose health it's about.
    audit.record(db, "escalation.recorded", target_type="escalation", target_id=escalation.id)
    alert_admin_team(db, escalation)
    if check.level in HOLD_LEVELS:
        tell_parent_about_teen(db, escalation)
    return escalation


def alert_admin_team(db: Session, escalation: Escalation) -> None:
    """HOOK (admin alerts for escalations): deliberately does nothing.

    Super Admin story 11.1 says "No escalation notifications: Given an escalation is recorded,
    when it happens, then no notification is sent. It appears on the Dashboard and in
    Escalation Management." So app.admin.notifications.service.notify_admins has no kind for
    escalations, and the team finds them through `list_escalations` (Needs Attention and
    Escalation Management). If the BA changes that, add the kind to
    app/admin/notifications/kinds.py and call it here:

        notify_admins(db, "escalation", {"level": escalation.level}, target_id=escalation.id)

    It runs in the transaction that records the escalation, so a notice would be saved with it
    (notify_admins doesn't commit). Never pass message text, the reason or a name: escalations
    are health data (docs/decisions/integration-conversations.md)."""
    return None


def tell_parent_about_teen(db: Session, escalation: Escalation) -> None:
    """Story 3.2: when a teen with their own account (`profile_type` "teen") has an emergency
    or a crisis, the parent is told that their teen may need help ("[Name] may need urgent
    help..." or "[Name] may need some support right now..."), with no conversation content.
    Runs in the transaction that records the escalation; app.teens.service.parent_told_at says
    when the parent was told (Super Admin story 4.1)."""
    # Imported here: app.teens imports app.notifications, which imports this module.
    from app.teens import service as teens

    teens.tell_parent(db, escalation)


def check_ins_blocked(
    db: Session,
    *,
    profile_id: uuid.UUID,
    conversation_id: uuid.UUID | None = None,
    since: datetime | None = None,
) -> bool:
    """Story 3.2's "No checking on the Client": true when an emergency or a crisis was detected
    for this profile (only in this conversation, if one is given; only after `since`, if
    given). Phase 9 must ask this before every follow-up, check-in or reminder it would send
    about the profile or conversation, and send nothing when it's true. Which notices it covers,
    and for how long, waits for question 28."""
    query = select(Escalation.id).where(
        Escalation.profile_id == profile_id, Escalation.level.in_(HOLD_LEVELS)
    )
    if conversation_id is not None:
        query = query.where(Escalation.conversation_id == conversation_id)
    if since is not None:
        query = query.where(Escalation.detected_at >= since)
    return db.scalar(query.limit(1)) is not None


# Safety holds


def open_holds(db: Session, conversation_id: uuid.UUID, *, lock: bool = False) -> list[Escalation]:
    """The conversation's emergencies and crises still waiting for an option, newest first."""
    query = (
        select(Escalation)
        .where(
            Escalation.conversation_id == conversation_id,
            Escalation.level.in_(HOLD_LEVELS),
            Escalation.client_choice.is_(None),
        )
        .order_by(Escalation.detected_at.desc())
    )
    if lock:
        query = query.with_for_update()
    return list(db.scalars(query))


def open_hold(db: Session, conversation_id: uuid.UUID) -> Escalation | None:
    """The newest open hold, whose options the app shows, or None."""
    holds = open_holds(db, conversation_id)
    return holds[0] if holds else None


def held_conversations(db: Session, conversation_ids: list[uuid.UUID]) -> set[uuid.UUID]:
    """Which of these conversations have an open hold."""
    if not conversation_ids:
        return set()
    return set(
        db.scalars(
            select(Escalation.conversation_id).where(
                Escalation.conversation_id.in_(conversation_ids),
                Escalation.level.in_(HOLD_LEVELS),
                Escalation.client_choice.is_(None),
            )
        )
    )


def check_option(hold: Escalation, option: str | None) -> SafetyOption:
    """The option must be one of those the hold's screen shows."""
    if option not in HOLD_OPTIONS[hold.level]:
        raise AppError(422, "safety_option_required", OPTION_NOT_SELECTED, "option")
    return option


def close_holds(holds: list[Escalation], option: SafetyOption) -> None:
    """Records the client's choice on every open hold in the conversation (read with
    `lock=True`): one choice answers the screen, whichever messages opened it."""
    now = datetime.now(UTC)
    for hold in holds:
        hold.client_choice = option
        hold.chosen_at = now


def hold_out(db: Session, hold: Escalation) -> SafetyHoldOut:
    line = db.get(Message, hold.response_message_id)
    return SafetyHoldOut(
        level=hold.level,
        message_id=hold.response_message_id,
        text=line.text,
        options=[
            SafetyOptionOut(option=option, label=OPTION_LABELS[option])
            for option in HOLD_OPTIONS[hold.level]
        ],
        reminder=OPTION_NOT_SELECTED,
    )


def advice_for(db: Session, message: Message) -> SafetyAdviceOut | None:
    """The advice line added for this client message, if its check escalated it."""
    escalation = db.scalar(select(Escalation).where(Escalation.message_id == message.id))
    if escalation is None:
        return None
    line = db.get(Message, escalation.response_message_id)
    return SafetyAdviceOut(
        level=escalation.level,
        message=MessageOut.model_validate(line).model_copy(update={"safety": escalation.level}),
    )


def advice_levels(db: Session, conversation_id: uuid.UUID) -> dict[uuid.UUID, EscalationLevel]:
    """The conversation's advice lines, by message id, with the level each one is for."""
    return dict(
        db.execute(
            select(Escalation.response_message_id, Escalation.level).where(
                Escalation.conversation_id == conversation_id
            )
        ).all()
    )


# For the admin side (Super Admin and Admin story 4.1, Phase A). No endpoint uses these yet.


def list_escalations(
    db: Session,
    *,
    status: str | None = None,
    level: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[Escalation]:
    """Not yet reviewed first, then newest first. Phase A adds search, the profile-type and
    date filters, and audits every view."""
    query = select(Escalation)
    if status is not None:
        query = query.where(Escalation.status == status)
    if level is not None:
        query = query.where(Escalation.level == level)
    query = query.order_by(
        case((Escalation.status == "not_reviewed", 0), else_=1), Escalation.detected_at.desc()
    )
    return list(db.scalars(query.limit(limit).offset(offset)))


def set_review_status(
    db: Session,
    escalation_id: uuid.UUID,
    status: str,
    reviewer_id: uuid.UUID,
    request: Request | None = None,
) -> Escalation:
    """Marks an escalation reviewed (with who and when) or not yet reviewed again. Phase A's
    endpoint answers MARKED_AS_REVIEWED. Review notes aren't stored yet: they're free text that
    may hold health data, which the 6-year record mustn't (docs/decisions/r3-conversations-and-
    3.2.md)."""
    if status not in ("not_reviewed", "reviewed"):
        raise ValueError(f"Unknown escalation status: {status}")
    with database_errors_retryable(db):
        escalation = db.get(Escalation, escalation_id, with_for_update=True)
        if escalation is None:
            raise AppError(404, "escalation_not_found", ESCALATION_NOT_FOUND)
        if escalation.status == status:
            return escalation
        escalation.status = status
        reviewed = status == "reviewed"
        escalation.reviewed_by_id = reviewer_id if reviewed else None
        escalation.reviewed_at = datetime.now(UTC) if reviewed else None
        audit.record(
            db,
            "escalation.reviewed" if reviewed else "escalation.review_undone",
            actor_id=reviewer_id,
            target_type="escalation",
            target_id=escalation.id,
            request=request,
        )
        db.commit()
    return escalation
