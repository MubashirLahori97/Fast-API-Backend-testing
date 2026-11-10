"""The audit log's categories and action names (Super Admin 10.1).

An action's category comes from, in order:

1. ACTIONS, for actions named explicitly;
2. the `.viewed` suffix: an Admin or the Super Admin opened something (Client Details, an
   escalation), 10.1's "Admin views";
3. PREFIXES, so the actions other packages add later fall into the right group.

Anything else is "other": client activity that holds no health information (a conversation
started, notes downloaded). `category_condition` is the same rule in SQL, for the filter.
"""

from sqlalchemy import ColumnElement, and_, false, not_, or_

from app.core.audit import AuditEvent

# 10.1's groups, in its order, plus "subscriptions" (Clients' billing events, which only the
# Super Admin may see: Super Admin 7.2) and "other".
CATEGORY_LABELS: dict[str, str] = {
    "sign_in_security": "Sign-in and security",
    "client_accounts": "Client accounts",
    "consent": "Consent",
    "data": "Data",
    "escalations": "Escalations",
    "support_requests": "Support requests",
    "knowledge_base": "Knowledge base",
    "admins": "Admins",
    "plans": "Plans",
    "admin_views": "Admin views",
    "subscriptions": "Subscriptions",
    "other": "Other client activity",
}
# Super Admin 7.2: Admins can't see Clients' subscription details.
SUPER_ADMIN_ONLY_CATEGORIES = frozenset({"subscriptions"})

# Who did it (10.1: Client, Teen, Admin, Super Admin or System). "anonymous" is a request from
# someone not signed in, such as a sign-in with an unknown email.
ROLE_LABELS: dict[str, str] = {
    "client": "Client",
    "teen": "Teen",
    "admin": "Admin",
    "super_admin": "Super Admin",
    "system": "System",
    "anonymous": "Not signed in",
}

# Prefixes, none of which starts another, so each action matches at most one.
PREFIXES: dict[str, str] = {
    "auth.": "sign_in_security",
    "account.": "client_accounts",
    "profile.": "client_accounts",
    "client.": "client_accounts",
    "teen.": "client_accounts",
    "consent.": "consent",
    "policy.": "consent",
    "health_consent.": "consent",
    "deletion.": "data",
    "legal_hold.": "data",
    "escalation.": "escalations",
    "support.": "support_requests",
    "knowledge.": "knowledge_base",
    "content.": "knowledge_base",
    "admin.": "admins",
    "plan.": "plans",
    "plans.": "plans",
    "price.": "plans",
    "billing.": "subscriptions",
    "audit.": "admin_views",
}
VIEWED_SUFFIX = ".viewed"

# (category, label) for the actions named explicitly: the ones whose prefix would put them in
# the wrong group, and the ones whose label reads better written out.
ACTIONS: dict[str, tuple[str, str]] = {
    # Sign-in and security
    "auth.sign_in.succeeded": ("sign_in_security", "Signed in"),
    "auth.sign_in.failed": ("sign_in_security", "Sign-in failed"),
    "auth.sign_in.blocked": ("sign_in_security", "Sign-in blocked"),
    "auth.code.sent": ("sign_in_security", "Verification code sent"),
    "auth.code.failed": ("sign_in_security", "Wrong verification code"),
    "auth.code.rejected": ("sign_in_security", "Verification code refused"),
    "auth.code.limited": ("sign_in_security", "Too many verification codes"),
    "auth.signed_out": ("sign_in_security", "Signed out"),
    "auth.session_timed_out": ("sign_in_security", "Signed out after inactivity"),
    "auth.session_revoked": ("sign_in_security", "Session ended"),
    "auth.account_locked": ("sign_in_security", "Account locked"),
    "auth.rate_limited": ("sign_in_security", "Too many attempts from one address"),
    "auth.password_reset.requested": ("sign_in_security", "Password reset requested"),
    "auth.password_reset.completed": ("sign_in_security", "Password reset"),
    "auth.password_reset.failed": ("sign_in_security", "Password reset failed"),
    "auth.password_changed": ("sign_in_security", "Password changed"),
    "auth.password_change.failed": ("sign_in_security", "Password change failed"),
    # Client accounts
    "auth.sign_up.started": ("client_accounts", "Sign-up started"),
    "auth.sign_up.refused": ("client_accounts", "Sign-up refused"),
    "auth.signed_up": ("client_accounts", "Signed up"),
    "auth.email_verified": ("client_accounts", "Email verified"),
    "account.details_updated": ("client_accounts", "Account details changed"),
    "account.state_changed": ("client_accounts", "State changed"),
    "account.email_changed": ("client_accounts", "Email changed"),
    "profile.created": ("client_accounts", "Family member added"),
    "profile.turned_off": ("client_accounts", "Family member turned off"),
    "profile.turned_on": ("client_accounts", "Family member turned on"),
    # Consent
    "policy.accepted": ("consent", "Policy accepted"),
    "policy.published": ("consent", "Policy version published"),
    "health_consent.accepted": ("consent", "Health Consent accepted"),
    "consent.revoked": ("consent", "Consent revoked"),
    "consent.given_again": ("consent", "Consent given again"),
    "profile.advocate_consent_recorded": ("consent", "Advocate consent given"),
    "profile.advocate_consent_cleared": ("consent", "Advocate consent cleared"),
    # Data
    "account.data_exported": ("data", "Data exported"),
    "account.deletion_requested": ("data", "Deletion requested"),
    "profile.deletion_requested": ("data", "Family member deletion requested"),
    "deletion.requested": ("data", "Deletion requested"),
    "deletion.acknowledged": ("data", "Deletion request acknowledged"),
    "deletion.grace_period_started": ("data", "Grace period started"),
    "deletion.grace_period_ended": ("data", "Grace period ended"),
    "deletion.created_by_team": ("data", "Deletion request added by the team"),
    "deletion.viewed": ("data", "Deletion request viewed"),
    "deletion.note_saved": ("data", "Deletion note saved"),
    "deletion.checklist_saved": ("data", "Deletion checklist updated"),
    "deletion.invited_teen_deleted": ("data", "Invited teen's account deleted"),
    "deletion.review_started": ("data", "Deletion review started"),
    "deletion.completed": ("data", "Deletion completed"),
    "deletion.declined": ("data", "Deletion declined"),
    "deletion.legal_hold_placed": ("data", "Placed on legal hold"),
    "deletion.legal_hold_lifted": ("data", "Legal hold lifted"),
    "deletion.purged": ("data", "Data deleted"),
    # Escalations and support requests
    "escalation.recorded": ("escalations", "Escalation recorded"),
    "escalation.reviewed": ("escalations", "Escalation reviewed"),
    "support.request_sent": ("support_requests", "Support request received"),
    "support.request_note_saved": ("support_requests", "Note saved"),
    "support.request_resolved": ("support_requests", "Support request resolved"),
    "support.request_reopened": ("support_requests", "Support request reopened"),
    "support.request_viewed": ("support_requests", "Support request opened"),
    # Admins
    "admin.invited": ("admins", "Admin invited"),
    "admin.invite_resent": ("admins", "Admin invite resent"),
    "admin.invite_cancelled": ("admins", "Admin invite cancelled"),
    "admin.invite_accepted": ("admins", "Admin invite accepted"),
    "admin.invite_rejected": ("admins", "Admin invite link refused"),
    "admin.set_up": ("admins", "Admin account set up"),
    "admin.edited": ("admins", "Admin edited"),
    "admin.deactivated": ("admins", "Admin deactivated"),
    "admin.reactivated": ("admins", "Admin reactivated"),
    "admin.profile_updated": ("admins", "Own profile updated"),
    "admin.super_admin_created": ("admins", "Super Admin account created"),
    # Admin views
    "audit.exported": ("admin_views", "Audit logs exported"),
}


def category_of(action: str) -> str:
    if action in ACTIONS:
        return ACTIONS[action][0]
    if action.endswith(VIEWED_SUFFIX):
        return "admin_views"
    for prefix, category in PREFIXES.items():
        if action.startswith(prefix):
            return category
    return "other"


def label_of(action: str) -> str:
    """The action as 10.1's screen shows it, for example "Deletion completed"."""
    if action in ACTIONS:
        return ACTIONS[action][1]
    words = action.replace(".", " ").replace("_", " ").split()
    return " ".join(words).capitalize() if words else action


def _prefix_match(prefixes: list[str]) -> ColumnElement[bool]:
    if not prefixes:
        return false()
    return or_(*(AuditEvent.action.startswith(prefix, autoescape=True) for prefix in prefixes))


def category_condition(category: str) -> ColumnElement[bool]:
    """SQL for category_of(AuditEvent.action) == category."""
    action = AuditEvent.action
    explicit = [name for name, (group, _) in ACTIONS.items() if group == category]
    unlisted = not_(action.in_(list(ACTIONS)))
    viewed = action.endswith(VIEWED_SUFFIX, autoescape=True)
    prefixes = [prefix for prefix, group in PREFIXES.items() if group == category]
    if category == "other":
        return and_(unlisted, not_(viewed), not_(_prefix_match(list(PREFIXES))))
    by_rule = and_(unlisted, not_(viewed), _prefix_match(prefixes))
    if category == "admin_views":
        by_rule = or_(by_rule, and_(unlisted, viewed))
    return or_(action.in_(explicit), by_rule) if explicit else by_rule
