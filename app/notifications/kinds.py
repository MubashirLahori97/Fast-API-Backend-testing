"""Every notification the app sends (story 12.1), with its text.

Texts use the stories' placeholders. Two kinds of placeholder are filled at different times:

- [Name], [X], [time] and [new email] are filled when the notification is created, from a
  first name or from a value the caller passes. Callers pass them in `data` under the keys in
  PLACEHOLDERS ("name", "days", "time", "new_email").
- [topic] and [specialty] are health data, so they're never stored in the notifications table.
  They're filled from the linked record (see targets.py) each time the app loads the list. When
  the record is gone, the kind's generic text is shown instead.

Push and email never carry names or health details (12.1's non-functional requirements): they
use `outside`, or the general message when a kind has none.

Texts not in the stories are listed in docs/decisions/phase-9-notifications.md.
"""

from dataclasses import dataclass
from typing import Literal

from app.billing.entitlements import TRIAL_ENDED

# Preference types (12.1's Notification Preferences). The client can turn the first five on or
# off and choose push, email or both; the last three are shown but can't be turned off.
Category = Literal[
    "guidance_follow_ups",
    "appointments",
    "wellness_plan",
    "health_profile",
    "inactivity",
    "billing",
    "requests_account",
    "teen_safety_access",
]
CATEGORY_LABELS: dict[str, str] = {
    "guidance_follow_ups": "Guidance follow-ups",
    "appointments": "Appointments",
    "wellness_plan": "Wellness Plan",
    "health_profile": "Health profile",
    "inactivity": "Inactivity",
    "billing": "Subscription and billing",
    "requests_account": "Requests and account",
    "teen_safety_access": "Teen safety and access",
}
LOCKED_CATEGORIES = frozenset({"billing", "requests_account", "teen_safety_access"})
TOGGLEABLE_CATEGORIES = tuple(c for c in CATEGORY_LABELS if c not in LOCKED_CATEGORIES)

# The screen a notification opens (12.1: "Tapping a notification opens the right screen, and
# switches to the right profile if needed"). The app maps each to its own route.
Screen = Literal[
    "conversation",  # target_id: the conversation
    "new_conversation",
    "visit_notes",  # target_id: the provider-ready note
    "log_visit",  # target_id: the provider-ready note the visit is for
    "wellness_plan",
    "check_in",
    "health_profile",
    "plans",  # choose a plan (9.1)
    "billing",  # Manage Billing & Subscription (11.3)
    "manage_family",
    "my_profile",
    "privacy_data",
    "adult_sign_up",  # 1.6's Create My Account
]

# 12.1's example of the general message for push and email.
GENERAL_UPDATE = "You have a new update from the Oracle"

# Values callers pass in `data`, and the story placeholder each one fills.
PLACEHOLDERS = {
    "name": "[Name]",
    "days": "[X]",
    "time": "[time]",
    "new_email": "[new email]",
    "date": "[date]",  # a deletion date (8.2, 11.4), as "December 5, 2026"
}
# Health data, filled from the linked record each time the list is shown (targets.py).
DETAIL_PLACEHOLDERS = {"topic": "[topic]", "specialty": "[specialty]"}
# The values that may go into a scheduled job's payload: never names or email addresses.
SCHEDULE_OPTIONS = frozenset({"days", "time"})


@dataclass(frozen=True)
class Kind:
    code: str
    category: Category
    title: str  # the heading in the notification centre; never a name or health detail
    body: str  # for the client's own profile, or about the account
    screen: Screen
    # For a managed family member's profile (12.1: reminders "show their name").
    family_body: str | None = None
    # Shown instead of body or family_body when [topic] or [specialty] can't be filled.
    generic_body: str | None = None
    generic_family_body: str | None = None
    # What target_id points at, for kinds that open one record (see targets.py).
    target: str | None = None
    # A follow-up or check-in, including the Wellness Plan and health profile ones: never sent
    # about a profile that has had an emergency or crisis (3.2; see service.after_emergency_or_
    # crisis). Reminders the client set up themselves (an appointment, lab results) and plan
    # updates still go, until question 28 says otherwise.
    check_in: bool = False
    # Push and email text. None means the general message.
    outside: str | None = None
    # Placeholders the caller must pass in `data` (keys of PLACEHOLDERS).
    needs: tuple[str, ...] = ()

    @property
    def locked(self) -> bool:
        return self.category in LOCKED_CATEGORIES


_KINDS = (
    # Guidance follow-ups. Scheduled by Phase 5 (3.3), settings.guidance_follow_up_days after
    # a summary, with target_id = the conversation.
    Kind(
        "guidance_follow_up",
        "guidance_follow_ups",
        "Checking in",
        "It’s been two weeks since we talked about [topic]. How are you feeling?",
        "conversation",
        family_body=(
            "It’s been two weeks since we talked about [topic] for [Name]. How is [Name] feeling?"
        ),
        generic_body="It’s been two weeks since we last talked. How are you feeling?",
        generic_family_body=(
            "It’s been two weeks since we last talked about [Name]. How is [Name] feeling?"
        ),
        target="conversation",
        check_in=True,
    ),
    # Appointments. Scheduled by Phase 5 (3.4) when provider-ready notes are saved, and by
    # Phase 6 (5.2), with target_id = the provider-ready note or visit log.
    Kind(
        "appointment_reminder",
        "appointments",
        "Appointment reminder",
        "Your [specialty] appointment is coming up.",
        "visit_notes",
        family_body="[Name]’s [specialty] appointment is coming up.",
        generic_body="Your appointment is coming up.",
        generic_family_body="[Name]’s appointment is coming up.",
        target="provider_note",
    ),
    Kind(
        "appointment_follow_up",
        "appointments",
        "How did it go?",
        "How did your [specialty] appointment go?",
        "log_visit",
        family_body="How did [Name]’s appointment go?",
        generic_body="How did your appointment go?",
        target="provider_note",
        check_in=True,
    ),
    Kind(
        "booking_follow_up",
        "appointments",
        "Booking reminder",
        "Have you booked your appointment yet?",
        "visit_notes",
        family_body="Have you booked [Name]’s appointment yet?",
        target="provider_note",
        check_in=True,
    ),
    Kind(
        "lab_results_expected",
        "appointments",
        "Lab results",
        "Your lab results should be ready soon. When you have them, you can type the values "
        "into a conversation.",
        "new_conversation",
        family_body=(
            "[Name]’s lab results should be ready soon. When you have them, you can type the "
            "values into a conversation."
        ),
        target="visit_log",
    ),
    # Wellness Plan (Phase 7, story 7.1).
    Kind(
        "wellness_plan_updated",
        "wellness_plan",
        "Wellness Plan updated",
        "Your Wellness Plan has been updated.",
        "wellness_plan",
        family_body="[Name]’s Wellness Plan has been updated.",
    ),
    Kind(
        "wellness_plan_check_in",
        "wellness_plan",
        "Check-in",
        "Check in with the Oracle: about 2 minutes.",
        "check_in",
        family_body="Check in with the Oracle about [Name]: about 2 minutes.",
        check_in=True,
    ),
    # Health profile (Phase 4, story 6.1). The review reminder passes data={"time": "3
    # months"} and so on (settings.health_profile_review_months); its text is 4.1's.
    Kind(
        "health_profile_review",
        "health_profile",
        "Health profile",
        "It’s been [time] since we last updated your profile. Has anything changed?",
        "health_profile",
        family_body=(
            "It’s been [time] since we last updated [Name]’s profile. Has anything changed?"
        ),
        needs=("time",),
        check_in=True,
    ),
    Kind(
        "health_profile_review_after_visit",
        "health_profile",
        "Health profile",
        "You’ve logged a visit. Has anything changed in your health profile?",
        "health_profile",
        family_body="You’ve logged a visit for [Name]. Has anything changed in [Name]’s profile?",
        check_in=True,
    ),
    Kind(
        "health_profile_incomplete",
        "health_profile",
        "Health profile",
        "Complete your health profile, so I can tailor my guidance to you.",
        "health_profile",
        family_body="Complete [Name]’s health profile, so I can tailor my guidance to them.",
        check_in=True,
    ),
    # Inactivity: sent by this package's sweep (service.send_inactivity_check_ins).
    Kind(
        "inactivity_check_in",
        "inactivity",
        "Checking in",
        "It’s been a while. How have you been?",
        "new_conversation",
        check_in=True,
        outside="It’s been a while. How have you been?",
    ),
    # Subscription and billing. The trial reminders are sent by this package's sweep; the
    # rest by Phase 8 (9.1, 11.3).
    Kind(
        "trial_ending",
        "billing",
        "Free trial",
        "Your free trial ends in [X] days. Choose a plan to keep talking with me.",
        "plans",
        outside="Your free trial ends in [X] days. Choose a plan to keep talking with me.",
        needs=("days",),
    ),
    Kind("trial_ended", "billing", "Free trial", TRIAL_ENDED, "plans", outside=TRIAL_ENDED),
    Kind(
        "renewal_failed",
        "billing",
        "Payment issue",
        "We couldn’t renew your subscription. Please update your payment method to keep your "
        "access.",
        "billing",
        outside=(
            "We couldn’t renew your subscription. Please update your payment method to keep "
            "your access."
        ),
    ),
    Kind(
        "family_members_turned_off",
        "billing",
        "Family plan",
        "Your Family plan has ended, so your family members’ profiles are turned off. Their "
        "information is kept, and you can turn them back on by returning to the Family plan.",
        "manage_family",
        outside=(
            "Your Family plan has ended, so your family members’ profiles are turned off. Their "
            "information is kept, and you can turn them back on by returning to the Family plan."
        ),
    ),
    Kind(
        "family_members_turned_on",
        "billing",
        "Family plan",
        "Your Family plan is active again, and your family members’ profiles are turned back on.",
        "manage_family",
        outside=(
            "Your Family plan is active again, and your family members’ profiles are turned back "
            "on."
        ),
    ),
    # Requests and account (Phase 10: 8.2's purge, 11.1, 11.4). The member is gone by the
    # time deletion_complete is sent, so the caller passes data={"name": ...} and no profile.
    Kind(
        "deletion_complete",
        "requests_account",
        "Deletion complete",
        "[Name]’s data has been deleted.",
        "manage_family",
        outside="A deletion you asked for is complete.",
        needs=("name",),
    ),
    Kind(
        "email_changed",
        "requests_account",
        "Email address changed",
        "Your email address has been changed to [new email]. Please sign in again with your new "
        "email address. We’ll send you a verification code to confirm it’s you.",
        "my_profile",
        outside=(
            "Your email address has been changed. Please sign in again with your new email address."
        ),
        needs=("new_email",),
    ),
    # Deletion requests (8.2, 11.4; docs/decisions/deletion-flow-1922.md). [date] is the end of
    # the grace period. The account's acknowledgement is 11.4's email text.
    Kind(
        "deletion_acknowledged",
        "requests_account",
        "Deletion requested",
        "We’ve received your request to delete your account. You can keep using Your Oracle and "
        "download your information until [date]. After that, your account will be deleted.",
        "privacy_data",
        outside=(
            "We’ve received your request to delete your account. You can keep using Your Oracle "
            "and download your information until [date]. After that, your account will be "
            "deleted."
        ),
        needs=("date",),
    ),
    # 8.2's "Deletion requested", sent with the family member's profile.
    Kind(
        "member_deletion_acknowledged",
        "requests_account",
        "Deletion requested",
        "Your request has been received. [Name]’s profile will be deleted after [date]. You can "
        "keep using it until then.",
        "manage_family",
        family_body=(
            "Your request has been received. [Name]’s profile will be deleted after [date]. You "
            "can keep using it until then."
        ),
        outside=(
            "Your request has been received. Your family member’s profile will be deleted after "
            "[date]. You can keep using it until then."
        ),
        needs=("date",),
    ),
    # 12.1's grace period reminder. The story gives the text for teens; adults get the same.
    Kind(
        "deletion_reminder",
        "requests_account",
        "Deletion reminder",
        "Your account will be deleted tomorrow. Download your information now if you’d like a "
        "copy.",
        "privacy_data",
        outside=(
            "Your account will be deleted tomorrow. Download your information now if you’d like "
            "a copy."
        ),
    ),
    # Teens with their own account, sent to the parent (Phase 3b, 8.2, 11.3, 1.6, 3.2). The
    # teen is another account, so the caller passes data={"name": the teen's first name}.
    # The paused and restored texts are the parent's pre-5 Nov ones (docs/PLAN.md, question 48).
    Kind(
        "teen_access_paused",
        "teen_safety_access",
        "Teen access",
        "[Name]’s access is paused because your Family plan has ended. Renew to restore it.",
        "manage_family",
        outside="Your teen’s access is paused because your Family plan has ended. Renew to "
        "restore it.",
        needs=("name",),
    ),
    Kind(
        "teen_access_restored",
        "teen_safety_access",
        "Teen access",
        "[Name]’s access has been restored.",
        "manage_family",
        outside="Your teen’s access has been restored.",
        needs=("name",),
    ),
    # Story 3.2's two parent notices, from app/teens/service.py's tell_parent (an emergency, then
    # a crisis). No conversation content; push and email say only the name-free text.
    Kind(
        "teen_may_need_urgent_help",
        "teen_safety_access",
        "Important update",
        "[Name] may need urgent help. Please check on them now. If you think they’re in danger, "
        "call 911.",
        "manage_family",
        outside="You have an important update from the Oracle. Please open Your Oracle.",
        needs=("name",),
    ),
    Kind(
        "teen_may_need_support",
        "teen_safety_access",
        "Important update",
        "[Name] may need some support right now. Please check in with them. If you think "
        "they’re in danger, call 911. You can also call or text 988.",
        "manage_family",
        outside="You have an important update from the Oracle. Please open Your Oracle.",
        needs=("name",),
    ),
    Kind(
        "teen_own_account",
        "teen_safety_access",
        "Teen access",
        "[Name] now has their own Your Oracle account. Their place in your family plan is free "
        "again.",
        "manage_family",
        outside=(
            "Your teen now has their own Your Oracle account. Their place in your family plan is "
            "free again."
        ),
        needs=("name",),
    ),
    # Teens with their own account, sent to the teen (Phase 3b, 1.6). The invite email goes to
    # someone without an account yet, so it's emails.teen_invite, not a kind.
    Kind(
        "age_of_majority_reminder",
        "teen_safety_access",
        "Your account",
        "In two weeks, you’ll reach adult age. You’ll need an adult plan to keep using Your "
        "Oracle.",
        "adult_sign_up",
        outside=(
            "In two weeks, you’ll reach adult age. You’ll need an adult plan to keep using Your "
            "Oracle."
        ),
    ),
    Kind(
        "access_paused",
        "teen_safety_access",
        "Your access",
        "Your access is paused. Please ask your parent or guardian. You can still download your "
        "data or ask for it to be deleted in Privacy & Data.",
        "privacy_data",
        outside=(
            "Your access is paused. Please ask your parent or guardian. You can still download "
            "your data or ask for it to be deleted in Privacy & Data."
        ),
    ),
    # 12.1's teen deletion notice: when the parent deletes their account, removes the teen, or
    # the teen asks for deletion (8.2, 11.4). Teen safety and access, so it reaches a teen whose
    # access is paused too. [date] is the end of the grace period.
    Kind(
        "teen_deletion_notice",
        "teen_safety_access",
        "Your account",
        "Your account and information will be deleted on [date]. You can keep using Your Oracle "
        "and download your information until then.",
        "privacy_data",
        outside=(
            "Your account and information will be deleted on [date]. You can keep using Your "
            "Oracle and download your information until then."
        ),
        needs=("date",),
    ),
    Kind(
        "teen_deletion_reminder",
        "teen_safety_access",
        "Your account",
        "Your account will be deleted tomorrow. Download your information now if you’d like a "
        "copy.",
        "privacy_data",
        outside=(
            "Your account will be deleted tomorrow. Download your information now if you’d like "
            "a copy."
        ),
    ),
)

KINDS: dict[str, Kind] = {kind.code: kind for kind in _KINDS}
