"""Export My Data (story 11.4): a JSON file of everything the account holds about its own
profiles, made on request and sent straight back. Nothing is stored, emailed, or shown to the
support team.

What's in it, picked field by field (never whole rows):

- the account details: first name, email, date of birth, country, state, ZIP code, plan;
- the policies accepted, and the history of revoking and giving consent;
- each profile the account holds (the client's own and their managed family members), with
  its intake answers, Health Consents and health profile answers (story 6.1);
- each profile's conversations, with every message and the client's feedback on replies, the
  conversation's guidance summary (story 3.3) and its provider-ready notes with every version
  (3.4, 3.5);
- each profile's logged visits (story 5.2), with the Oracle's review of each, and its Wellness
  Plan (7.1): the current plan, every To Do item and focus area, and each earlier version.

Left out on purpose:

- invited teens: their accounts and profiles are their own, never the parent's (11.4);
- conversations the client deleted (they're gone from every list, and purged soon after);
- the safety check's internal fields and escalation records, which are the support team's
  review records (3.2), and the team's notes on support requests;
- pending health facts the client hasn't confirmed (they aren't part of the profile yet).

"""

import json
import uuid
from collections import defaultdict
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.accounts.models import ConsentRevocation, PolicyAcceptance, PolicyVersion
from app.auth.models import User
from app.billing import entitlements
from app.conversations.models import Conversation, HealthConsent, Message, MessageFeedback
from app.guidance.models import GuidanceSummary, ProviderNote, ProviderNoteVersion
from app.health.models import HealthAnswer
from app.profiles.models import Profile
from app.visits.models import VisitLog
from app.wellness.models import WellnessPlan, WellnessPlanItem, WellnessPlanVersion

EXPORT_FORMAT = "your-oracle-export"
EXPORT_VERSION = 1


def _iso(value: datetime | date | None) -> str | None:
    return value.isoformat() if value is not None else None


def _account(account: User) -> dict[str, Any]:
    return {
        "first_name": account.first_name,
        "email": account.email,
        "date_of_birth": _iso(account.date_of_birth),
        "country": account.country,
        "state": account.state,
        "zip_code": account.zip_code,
        "plan": entitlements.plan(account),
        "created_at": _iso(account.created_at),
    }


def _policies(db: Session, account: User) -> list[dict[str, Any]]:
    rows = db.execute(
        select(PolicyVersion, PolicyAcceptance.accepted_at)
        .join(PolicyAcceptance, PolicyAcceptance.policy_version_id == PolicyVersion.id)
        .where(PolicyAcceptance.user_id == account.id)
        .order_by(PolicyAcceptance.accepted_at)
    ).all()
    return [
        {
            "policy": policy.title,
            "kind": policy.kind,
            "version": policy.version,
            "accepted_at": _iso(accepted_at),
        }
        for policy, accepted_at in rows
    ]


def _consent_history(db: Session, account: User) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(ConsentRevocation)
        .where(ConsentRevocation.account_id == account.id)
        .order_by(ConsentRevocation.revoked_at)
    )
    return [
        {"revoked_at": _iso(row.revoked_at), "given_again_at": _iso(row.restored_at)}
        for row in rows
    ]


def _health_consents(db: Session, profile_ids: list[uuid.UUID]) -> dict[uuid.UUID, list]:
    rows = db.execute(
        select(HealthConsent.profile_id, PolicyVersion.version, HealthConsent.accepted_at)
        .join(PolicyVersion, HealthConsent.policy_version_id == PolicyVersion.id)
        .where(HealthConsent.profile_id.in_(profile_ids))
        .order_by(HealthConsent.accepted_at)
    ).all()
    by_profile: dict[uuid.UUID, list] = defaultdict(list)
    for profile_id, version, accepted_at in rows:
        by_profile[profile_id].append({"version": version, "accepted_at": _iso(accepted_at)})
    return by_profile


def _health_answers(db: Session, profile_ids: list[uuid.UUID]) -> dict[uuid.UUID, list]:
    """Story 6.1's saved answers, keyed by the question bank's keys (app/health/questions.json),
    with where each came from."""
    rows = db.scalars(
        select(HealthAnswer)
        .where(HealthAnswer.profile_id.in_(profile_ids))
        .order_by(HealthAnswer.question_key)
    )
    by_profile: dict[uuid.UUID, list] = defaultdict(list)
    for row in rows:
        by_profile[row.profile_id].append(
            {
                "question": row.question_key,
                "answer": row.answer,
                "source": row.source,
                "updated_at": _iso(row.updated_at),
            }
        )
    return by_profile


def _conversations(db: Session, profile_ids: list[uuid.UUID]) -> dict[uuid.UUID, list]:
    conversations = list(
        db.scalars(
            select(Conversation)
            .where(Conversation.profile_id.in_(profile_ids), Conversation.deleted_at.is_(None))
            .order_by(Conversation.created_at)
        )
    )
    conversation_ids = [conversation.id for conversation in conversations]
    messages: dict[uuid.UUID, list[Message]] = defaultdict(list)
    for message in db.scalars(
        select(Message)
        .where(Message.conversation_id.in_(conversation_ids))
        .order_by(Message.conversation_id, Message.created_at, Message.id)
    ):
        messages[message.conversation_id].append(message)
    feedback = {
        row.message_id: row
        for row in db.scalars(
            select(MessageFeedback)
            .join(Message, MessageFeedback.message_id == Message.id)
            .where(Message.conversation_id.in_(conversation_ids))
        )
    }

    summaries = {
        row.conversation_id: row
        for row in db.scalars(
            select(GuidanceSummary).where(
                GuidanceSummary.conversation_id.in_(conversation_ids),
                GuidanceSummary.content.is_not(None),
            )
        )
    }
    notes = _provider_notes(db, conversation_ids)

    by_profile: dict[uuid.UUID, list] = defaultdict(list)
    for conversation in conversations:
        summary = summaries.get(conversation.id)
        by_profile[conversation.profile_id].append(
            {
                "topic": conversation.topic,
                "started_at": _iso(conversation.created_at),
                "last_message_at": _iso(conversation.last_message_at),
                "messages": [
                    _message(message, feedback.get(message.id))
                    for message in messages[conversation.id]
                ],
                "guidance_summary": (
                    {
                        "stage": summary.stage,
                        "content": summary.content,
                        "updated_at": _iso(summary.content_updated_at),
                    }
                    if summary is not None
                    else None
                ),
                "provider_notes": notes[conversation.id],
            }
        )
    return by_profile


def _provider_notes(db: Session, conversation_ids: list[uuid.UUID]) -> dict[uuid.UUID, list]:
    """Each set of notes with its current appointment details and every version's content,
    the original first."""
    note_rows = list(
        db.scalars(
            select(ProviderNote)
            .where(ProviderNote.conversation_id.in_(conversation_ids))
            .order_by(ProviderNote.created_at)
        )
    )
    versions: dict[uuid.UUID, list] = defaultdict(list)
    for version in db.scalars(
        select(ProviderNoteVersion)
        .where(ProviderNoteVersion.note_id.in_([note.id for note in note_rows]))
        .order_by(ProviderNoteVersion.note_id, ProviderNoteVersion.version)
    ):
        versions[version.note_id].append(
            {
                "version": version.version,
                "specialty": version.specialty,
                "specialty_other": version.specialty_other,
                "content": version.content,
                "written_at": _iso(version.created_at),
            }
        )
    by_conversation: dict[uuid.UUID, list] = defaultdict(list)
    for note in note_rows:
        by_conversation[note.conversation_id].append(
            {
                "specialty": note.specialty,
                "specialty_other": note.specialty_other,
                "provider_name": note.provider_name,
                "appointment_date": _iso(note.appointment_date),
                "current_version": note.version,
                "versions": versions[note.id],
            }
        )
    return by_conversation


def _visit_logs(db: Session, profile_ids: list[uuid.UUID]) -> dict[uuid.UUID, list]:
    """Story 5.2's logs, newest visit first. A deleted log is gone, so it isn't here."""
    rows = db.scalars(
        select(VisitLog)
        .where(VisitLog.profile_id.in_(profile_ids))
        .order_by(VisitLog.visit_date.desc(), VisitLog.created_at.desc())
    )
    by_profile: dict[uuid.UUID, list] = defaultdict(list)
    for log in rows:
        by_profile[log.profile_id].append(
            {
                "visit_date": _iso(log.visit_date),
                "reason": log.reason,
                "duration": log.duration,
                "specialty": log.specialty,
                "specialty_other": log.specialty_other,
                "provider_name": log.provider_name,
                "practice": log.practice,
                "follow_up_date": _iso(log.follow_up_date),
                "diagnosis": log.diagnosis,
                "understanding": log.understanding,
                "unaddressed_concerns": log.unaddressed_concerns,
                "labs": log.labs,
                "medicine_changes": log.medicine_changes,
                "genesis_gold": log.genesis_gold_status,
                "sacred_seven": log.sacred_seven_status,
                "next_steps": log.next_steps,
                "own_notes": log.own_notes,
                "oracle_review": log.review if log.review_status == "ready" else None,
                "created_at": _iso(log.created_at),
                "updated_at": _iso(log.updated_at),
            }
        )
    return by_profile


def _wellness_plans(db: Session, profile_ids: list[uuid.UUID]) -> dict[uuid.UUID, dict]:
    """Story 7.1's plan per profile: the current content, its items (removed ones too, with
    why) and every earlier version. A profile without a plan has no entry."""
    plans = list(db.scalars(select(WellnessPlan).where(WellnessPlan.profile_id.in_(profile_ids))))
    plan_ids = [plan.id for plan in plans]
    items: dict[uuid.UUID, list] = defaultdict(list)
    for item in db.scalars(
        select(WellnessPlanItem)
        .where(WellnessPlanItem.plan_id.in_(plan_ids))
        .order_by(WellnessPlanItem.position)
    ):
        items[item.plan_id].append(
            {
                "kind": item.kind,
                "title": item.title,
                "details": item.details,
                "status": item.status,
                "completed_at": _iso(item.completed_at),
                "completed_by": item.completed_by,
                "follow_up_on": _iso(item.follow_up_on),
                "removed_at": _iso(item.removed_at),
                "removed_reason": item.removed_reason,
                "created_at": _iso(item.created_at),
            }
        )
    versions: dict[uuid.UUID, list] = defaultdict(list)
    for version in db.scalars(
        select(WellnessPlanVersion)
        .where(WellnessPlanVersion.plan_id.in_(plan_ids))
        .order_by(WellnessPlanVersion.version)
    ):
        versions[version.plan_id].append(
            {
                "version": version.version,
                "trigger": version.trigger,
                "outcome": version.outcome,
                "plan": version.snapshot,
                "changes": version.changes,
                "created_at": _iso(version.created_at),
            }
        )
    return {
        plan.profile_id: {
            "version": plan.version,
            "plan": plan.content,
            "last_updated": _iso(plan.content_updated_at),
            "items": items[plan.id],
            "earlier_versions": versions[plan.id],
        }
        for plan in plans
        if plan.version > 0
    }


def _message(message: Message, feedback: MessageFeedback | None) -> dict[str, Any]:
    item: dict[str, Any] = {
        "from": "you" if message.role == "client" else "oracle",
        "text": message.text,
        "sent_at": _iso(message.created_at),
    }
    if message.answer is not None:
        item["answer"] = message.answer  # what was tapped in reply to a widget
    if message.widgets:
        item["widgets"] = message.widgets
    if feedback is not None:
        item["your_feedback"] = {"rating": feedback.rating, "comment": feedback.comment}
    return item


def _profile(
    profile: Profile,
    account: User,
    consents: list,
    answers: list,
    conversations: list,
    visit_logs: list,
    wellness_plan: dict | None,
) -> dict[str, Any]:
    item: dict[str, Any] = {
        "profile": "you" if profile.is_self else "family member",
        "first_name": account.first_name if profile.is_self else profile.first_name,
        "date_of_birth": _iso(profile.date_of_birth),
    }
    if not profile.is_self:
        item.update(
            {
                "relationship": profile.family_relationship,
                "teen_profile_choice": profile.teen_profile_choice,
                "advocate_consent": profile.advocate_consent,
                "advocate_consent_at": _iso(profile.advocate_consent_at),
                "turned_off_at": _iso(profile.turned_off_at),
            }
        )
    item.update(
        {
            "sex_at_birth": profile.sex_at_birth,
            "gender_identity": profile.gender_identity,
            "gender_identity_other": profile.gender_identity_other,
            "pronouns": profile.pronouns,
            "pronouns_other": profile.pronouns_other,
            "intake_completed_at": _iso(profile.intake_completed_at),
            "deletion_requested_at": _iso(profile.deletion_requested_at),
            "created_at": _iso(profile.created_at),
            "health_consents": consents,
            "health_profile": answers,
            "conversations": conversations,
            "visit_logs": visit_logs,
            "wellness_plan": wellness_plan,
        }
    )
    return item


def build_export(db: Session, account: User) -> dict[str, Any]:
    """Everything above, for the signed-in account only. Read-only."""
    profiles = list(
        db.scalars(
            select(Profile)
            .where(Profile.account_id == account.id)
            .order_by(Profile.is_self.desc(), Profile.created_at)
        )
    )
    profile_ids = [profile.id for profile in profiles]
    consents = _health_consents(db, profile_ids)
    answers = _health_answers(db, profile_ids)
    conversations = _conversations(db, profile_ids)
    visit_logs = _visit_logs(db, profile_ids)
    plans = _wellness_plans(db, profile_ids)
    return {
        "format": EXPORT_FORMAT,
        "version": EXPORT_VERSION,
        "exported_at": _iso(datetime.now(UTC)),
        "account": _account(account),
        "policies_accepted": _policies(db, account),
        "consent_history": _consent_history(db, account),
        "profiles": [
            _profile(
                profile,
                account,
                consents[profile.id],
                answers[profile.id],
                conversations[profile.id],
                visit_logs[profile.id],
                plans.get(profile.id),
            )
            for profile in profiles
        ],
    }


def export_file(db: Session, account: User) -> tuple[bytes, str]:
    """The file's bytes (UTF-8 JSON, indented to be readable) and its download name."""
    data = build_export(db, account)
    body = json.dumps(data, ensure_ascii=False, indent=2).encode()
    filename = f"your-oracle-data-{datetime.now(UTC):%Y-%m-%d}.json"
    return body, filename
