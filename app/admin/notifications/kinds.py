"""Every notification the admin team gets (Super Admin 11.1, Admin 8.1), with its text.

- In-app text can name what it's about (the type of support request, a knowledge gap's
  question, a new Admin's first name): the admin panel is where the details belong.
- Email text never holds health information or Client names (11.1's Privacy): it's the kind's
  `email_text`, a general message such as "You have a new support request to review".
- Placeholders are filled from `data` when the notification is made; callers pass them under
  the keys in PLACEHOLDERS.

Not notified, on purpose (11.1's "What Isn't Notified"): escalations, which the team sees on
the Dashboard and in Escalation Management, and Client exports.
"""

from dataclasses import dataclass
from typing import Literal

# Preference types: each Admin and the Super Admin turns emails on or off per type (11.1).
Category = Literal[
    "support_requests",
    "knowledge_gaps",
    "deletion_requests",
    "deletion_deadlines",
    "knowledge_base",
    "policies",
    "admins",
]
CATEGORY_LABELS: dict[str, str] = {
    "support_requests": "Support requests",
    "knowledge_gaps": "Knowledge gaps",
    "deletion_requests": "Deletion requests",
    "deletion_deadlines": "Deletion deadline reminders",
    "knowledge_base": "Knowledge base",
    "policies": "Policy updates",
    "admins": "New admins",
}
# 11.1: "Deletion deadline reminders can't be turned off."
LOCKED_CATEGORIES = frozenset({"deletion_deadlines"})

# Who gets each kind.
Audience = Literal["team", "super_admin"]
TEAM_ROLES = ("admin", "super_admin")
AUDIENCE_ROLES: dict[str, tuple[str, ...]] = {"team": TEAM_ROLES, "super_admin": ("super_admin",)}
# Categories that only reach the Super Admin, so Admins aren't shown them in preferences.
SUPER_ADMIN_CATEGORIES = frozenset({"admins"})

# The admin panel screen a notification opens (11.1: "Tapping a notification opens the right
# screen"). target_id is the record it opens, when there is one.
Screen = Literal[
    "support_request",  # target_id: the support request
    "knowledge_gap",  # target_id: the knowledge gap
    "deletion_request",  # target_id: the deletion request
    "content_review",  # target_id: the content item waiting for approval
    "knowledge_base",
    "policy_versions",  # target_id: the policy version
    "admin",  # target_id: the Admin's row in Admin Management (admin_invitations.id)
]

# The support request types of Super Admin 5.1, for [request type].
REQUEST_TYPES = {
    "talk_to_support": "Talk to Support Team request",
    "consultation": "Consultation Request",
    "email_change": "Email Change Request",
    "knowledge_gap": "Knowledge Gap request",
}
POLICY_NAMES = {
    "terms": "Terms of Service",
    "privacy": "Privacy Policy",
    "health_consent": "Health Consent",
}

# Keys callers pass in `data`, and the placeholder each fills.
PLACEHOLDERS = {
    "request_type": "[request type]",  # a key of REQUEST_TYPES
    "question": "[question]",  # a knowledge gap's question (in-app only)
    "policy": "[policy]",  # a key of POLICY_NAMES
    "name": "[Name]",  # an Admin's first name (in-app only)
    "days": "[X]",
}


@dataclass(frozen=True)
class Kind:
    code: str
    category: Category
    title: str
    body: str  # the in-app text
    email_text: str  # the email's text: general, with no Client or health details
    screen: Screen
    audience: Audience = "team"
    # Placeholders the caller must pass (keys of PLACEHOLDERS).
    needs: tuple[str, ...] = ()
    # Shown instead of body or email_text when an optional placeholder isn't given (callers
    # in app/admin/common.py pass no data at all).
    fallback_body: str | None = None
    fallback_email_text: str | None = None

    @property
    def locked(self) -> bool:
        return self.category in LOCKED_CATEGORIES


_KINDS = (
    # Super Admin 5.1: a new Talk to Support Team, Consultation Request or Email Change
    # Request (the support package passes its kind as request_type).
    Kind(
        "support_request",
        "support_requests",
        "New support request",
        "You have a new [request type] to review.",
        "You have a new support request to review",
        "support_request",
        needs=("request_type",),
    ),
    # Super Admin 6.3: a new knowledge gap, with the question.
    Kind(
        "knowledge_gap",
        "knowledge_gaps",
        "New knowledge gap",
        "The Oracle couldn’t answer this question: “[question]”",
        "You have a new knowledge gap to review",
        "knowledge_gap",
        fallback_body="There’s a new knowledge gap to review.",
    ),
    # Super Admin 5.2 and 11.1: a deletion request has finished its 10-day grace period and is
    # ready for review (nothing is sent during the grace period), and the reminder 5 days
    # before its 45-day deadline, which can't be turned off.
    Kind(
        "deletion_request",
        "deletion_requests",
        "Deletion ready for review",
        "A data deletion request has finished its grace period and is ready for review.",
        "A data deletion request is ready for review",
        "deletion_request",
    ),
    # [X] defaults to settings.deletion_highlight_days (service._DEFAULTS): 5 calendar days.
    Kind(
        "deletion_deadline",
        "deletion_deadlines",
        "Deletion deadline",
        "A data deletion request is due in [X] days.",
        "A data deletion request is due in [X] days",
        "deletion_request",
    ),
    # Super Admin 11.1: content waiting for approval (Super Admin only). Admin 6.2 and 7.1: the
    # Super Admin approved or rejected content the Admin sent (to that Admin only: notify_admins'
    # recipient_id). No title in the texts: a knowledge gap answer's title is the client's
    # question. Nothing is synced since 6 Nov 19:22, so there's no failed-sync notice.
    Kind(
        "content_pending_approval",
        "knowledge_base",
        "Content to review",
        "New knowledge base content is waiting for your approval.",
        "You have knowledge base content to review",
        "content_review",
        audience="super_admin",
    ),
    Kind(
        "content_approved",
        "knowledge_base",
        "Content approved",
        "The Super Admin has approved content you sent. It’s now published.",
        "Content you sent has been approved",
        "content_review",
    ),
    Kind(
        "content_rejected",
        "knowledge_base",
        "Content rejected",
        "The Super Admin has rejected content you sent. Open it to see the reason.",
        "Content you sent has been rejected",
        "content_review",
    ),
    # Super Admin 9.2: a new version of a policy has been published.
    Kind(
        "policy_published",
        "policies",
        "Policy update",
        "A new version of the [policy] has been published.",
        "A new version of the [policy] has been published",
        "policy_versions",
        fallback_body="A new policy version has been published.",
        fallback_email_text="A new policy version has been published",
    ),
    # Super Admin 7.2: a new Admin has set up their account (Super Admin only).
    Kind(
        "admin_set_up",
        "admins",
        "New admin",
        "[Name] has set up their admin account.",
        "A new admin has set up their account",
        "admin",
        audience="super_admin",
        needs=("name",),
    ),
)

KINDS: dict[str, Kind] = {kind.code: kind for kind in _KINDS}
