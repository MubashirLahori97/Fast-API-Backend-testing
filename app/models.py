"""Imports every table class so Base.metadata lists them all.

Alembic reads Base.metadata from here. When you add a models module, import it below.
"""

from app.accounts.models import (
    ConsentRevocation,
    DeletionRequest,
    PolicyAcceptance,
    PolicyVersion,
)
from app.admin.auth.models import AdminInvitation
from app.admin.deletions.models import DeletionReview
from app.admin.escalations.models import EscalationNote
from app.admin.notifications.models import AdminNotification, AdminNotificationPreference
from app.admin.policies.models import PolicyText
from app.auth.models import (
    PasswordResetToken,
    PendingSignUp,
    TrustedDevice,
    User,
    UserSession,
    VerificationChallenge,
)
from app.billing.catalog import BillingPlan, PlanPriceChange
from app.billing.models import Invoice, PausedFamilyMember, PaymentEvent, Subscription
from app.conversations.models import (
    Conversation,
    Escalation,
    HealthConsent,
    Message,
    MessageFeedback,
)
from app.core.audit import AuditEvent
from app.core.jobs import Job
from app.guidance.models import GuidanceSummary, ProviderNote, ProviderNoteVersion
from app.health.models import HealthAnswer, HealthFact, HealthProfile
from app.knowledge.models import (
    KnowledgeContent,
    KnowledgeContentVersion,
    KnowledgeFile,
    KnowledgeGap,
    KnowledgeGapRequest,
)
from app.notifications.models import Notification, NotificationPreference, PushToken
from app.profiles.models import Profile
from app.support.models import SupportRequest
from app.teens.models import TeenAccount, TeenLink, TeenParentNotice
from app.visits.models import VisitLog
from app.wellness.models import WellnessPlan, WellnessPlanItem, WellnessPlanVersion

__all__ = [
    "AdminInvitation",
    "AdminNotification",
    "AdminNotificationPreference",
    "AuditEvent",
    "BillingPlan",
    "ConsentRevocation",
    "Conversation",
    "DeletionRequest",
    "DeletionReview",
    "Escalation",
    "EscalationNote",
    "GuidanceSummary",
    "HealthAnswer",
    "HealthConsent",
    "HealthFact",
    "HealthProfile",
    "Invoice",
    "Job",
    "KnowledgeContent",
    "KnowledgeContentVersion",
    "KnowledgeFile",
    "KnowledgeGap",
    "KnowledgeGapRequest",
    "Message",
    "MessageFeedback",
    "Notification",
    "NotificationPreference",
    "PasswordResetToken",
    "PausedFamilyMember",
    "PaymentEvent",
    "PendingSignUp",
    "PlanPriceChange",
    "PolicyAcceptance",
    "PolicyText",
    "PolicyVersion",
    "Profile",
    "ProviderNote",
    "ProviderNoteVersion",
    "PushToken",
    "Subscription",
    "SupportRequest",
    "TeenAccount",
    "TeenLink",
    "TeenParentNotice",
    "TrustedDevice",
    "User",
    "UserSession",
    "VerificationChallenge",
    "VisitLog",
    "WellnessPlan",
    "WellnessPlanItem",
    "WellnessPlanVersion",
]
