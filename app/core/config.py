from typing import Literal

from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict


class ProviderSpecialty(BaseModel):
    """One option of story 3.4's specialty dropdown. "Other", with its write-in, is always
    offered after these (app/guidance/specialties.py)."""

    code: str  # stored with the notes; never change an existing one
    label: str  # shown in the dropdown, the notes, the reminders and the PDF's file name
    # Who the client would see, with its article, for 3.4's "From what you’ve shared, a
    # [specialty] would be a good place to start..."
    provider: str


class Settings(BaseSettings):
    """App settings, read from environment variables first and then from `.env`."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    # Any other value stops the app at startup, so a typo such as "prod" can't quietly run the
    # development stand-ins (console email, the fake Oracle) with real data.
    environment: Literal["development", "test", "production"] = "development"
    # Origins allowed to call the API from a browser. In .env, write it as JSON:
    # CORS_ORIGINS=["http://localhost:5173"]
    cors_origins: list[str] = ["http://localhost:5173"]
    email_from: str = "Your Oracle <no-reply@genesishealth.local>"
    # Where development emails go: "console" prints them in the server's log; "smtp" sends them
    # to the local test inbox (Mailpit in compose.yaml, shown at http://localhost:8025).
    email_backend: Literal["console", "smtp"] = "console"
    smtp_host: str = "127.0.0.1"
    smtp_port: int = 1025
    # The password reset email links here, with ?token=... added.
    password_reset_url: str = "http://localhost:5173/reset-password"

    # Plans (stories 8.1 and 9.1): the Family plan includes the account holder plus this many
    # family members. The Individual plan and the free trial include none.
    family_members_included: int = 3
    # Billing (stories 9.1 and 11.3). Prices are monthly, in US cents. The names and prices are
    # assumed values until the BA gives the real ones (docs/decisions/phase-8-billing.md); the
    # admin panel takes them over in Phase A. Read them through app/billing/catalog.py.
    individual_plan_name: str = "Individual"
    family_plan_name: str = "Family"
    individual_price_cents: int = 1999
    family_price_cents: int = 3999
    family_add_on_price_cents: int = 999
    billing_currency: str = "usd"
    max_add_on_members: int = 10
    # Question 13: how long access continues after a renewal payment fails.
    payment_grace_days: int = 7
    # Where the provider's hosted pages (checkout, payment method) send the client back.
    billing_return_url: str = "http://localhost:5173/billing"
    # Signs the payment provider's webhooks. The real provider needs its own secret in .env.
    payment_webhook_secret: str = "dev-only-payment-webhook-secret"
    # A signed webhook older than this is refused, so a captured one can't be replayed later.
    payment_webhook_tolerance_seconds: int = 300
    # The app emails a receipt for each payment. Turn off if the provider sends its own.
    send_receipt_emails: bool = True
    # Stories 8.2 and 11.4, Super Admin 5.2 (docs/decisions/deletion-flow-1922.md): every
    # deletion request has a grace period with full use, then the account or profile is locked
    # and the team completes it within the deadline (calendar days from the request, CCPA/CPRA).
    deletion_grace_days: int = 10
    deletion_due_days: int = 45
    # 12.1's grace period reminder ("deleted tomorrow") goes this long before the grace ends.
    deletion_grace_reminder_hours: int = 24
    # A conversation the client deleted is purged this long after (question 45).
    deleted_conversation_purge_days: int = 7
    # The privacy sweep: ends grace periods (and sends their reminders), emails the team about
    # requests ready for review and purges deleted conversations, this often and this many at
    # a time.
    privacy_sweep_minutes: int = 15
    privacy_sweep_batch_size: int = 100

    # Teens with their own account (stories 1.5 and 1.6, docs/decisions/phase-3b-teens.md). The
    # invite email links here, with #token=... added; the invite works for this many days and
    # can be sent again (which replaces the link).
    teen_invite_url: str = "http://localhost:5173/teen-invite"
    teen_invite_days: int = 14
    # 1.6: the reminder goes this many days before the age of majority, at this hour in Hawaii
    # (09:00 there is 14:00 or 15:00 on the East Coast). The daily age check runs just after
    # midnight in Hawaii, the last US state to reach each date.
    teen_age_reminder_days: int = 14
    teen_age_reminder_hour_hawaii: int = 9

    # Names and write-ins reach PDFs and the Oracle's prompts, so they're kept short.
    name_max_length: int = 100

    # Conversations (story 3.1). Assumed values until the BA confirms them (docs/PLAN.md).
    message_max_length: int = 8000
    feedback_comment_max_length: int = 2000
    # Per account, across all its profiles: every message costs a safety check and a reply.
    max_messages_per_hour: int = 60
    max_conversations_per_day: int = 20
    # The Oracle's reply: tries per message, how long one try may run, and how long a started
    # reply blocks another try (in case the first one's connection died). The claim must
    # outlast a whole try: the reply, the topic (10 seconds) and saving. Streams at once in
    # one server process, each holding a worker thread until the Oracle client is async.
    reply_max_attempts: int = 5
    reply_timeout_seconds: int = 90
    reply_claim_seconds: int = 120
    max_reply_streams: int = 20
    # A safety check that failed when its message was sent is retried by the worker, starting
    # this long after the message (story 3.2).
    safety_check_retry_seconds: int = 60
    # What the Oracle is given with each reply: the latest messages of this conversation, and
    # of the profile's most recent earlier conversations (story 3.1 sections 4 to 6).
    oracle_history_messages: int = 60
    oracle_earlier_conversations: int = 3
    oracle_earlier_messages: int = 20
    # Health details (health_fact widgets, stories 3.1 and 6.1) saved from one reply; any more
    # are dropped. Each is a database write, and the Oracle's output is untrusted
    # (docs/decisions/conversations-health-1922.md).
    max_health_facts_per_reply: int = 10
    # A conversation picked up after this long opens with the story's "Welcome back" line.
    welcome_back_after_hours: int = 12
    # Story 3.2: escalation records are kept at least this long (BAA Section 13). Phase 10's
    # purge must leave younger ones alone, whatever else it deletes.
    escalation_retention_years: int = 6

    # Guidance summaries and provider-ready notes (stories 3.3 to 3.5). Assumed values
    # (docs/decisions/phase-5-guidance-and-notes.md).
    # Story 3.4's dropdown, in its order. Options can change without an app release (3.4), so
    # in .env it's a JSON list of {"code", "label", "provider"}.
    provider_specialties: list[ProviderSpecialty] = [
        ProviderSpecialty(
            code="primary_care",
            label="Primary Care / Family Medicine",
            provider="a primary care provider",
        ),
        ProviderSpecialty(code="ob_gyn", label="OB-GYN", provider="an OB-GYN"),
        ProviderSpecialty(
            code="endocrinology", label="Endocrinology", provider="an endocrinologist"
        ),
        ProviderSpecialty(
            code="integrative_functional",
            label="Integrative / Functional Medicine",
            provider="an integrative or functional medicine provider",
        ),
        ProviderSpecialty(code="rheumatology", label="Rheumatology", provider="a rheumatologist"),
        ProviderSpecialty(code="neurology", label="Neurology", provider="a neurologist"),
        ProviderSpecialty(code="urology", label="Urology", provider="a urologist"),
        ProviderSpecialty(code="cardiology", label="Cardiology", provider="a cardiologist"),
        ProviderSpecialty(code="psychiatry", label="Psychiatry", provider="a psychiatrist"),
    ]
    # What the Oracle is given to write a summary or notes: the conversation's latest messages.
    oracle_output_history_messages: int = 200
    # One summary or notes generation at a time per record; a claim older than this belongs to
    # a request that died. The Oracle has 10 seconds for each (3.3, 3.4).
    guidance_claim_seconds: int = 60
    # Sets of notes per conversation (question 15), each costing an Oracle call.
    max_provider_notes_per_conversation: int = 10
    # Appointment dates can't be further ahead than this.
    appointment_max_years_ahead: int = 2
    # 3.4's reminder before the appointment and follow-up after it (question 9), sent at this
    # hour UTC (18:00 is 1pm Eastern and 8am in Hawaii) until question 8 gives time zones.
    appointment_reminder_days_before: int = 1
    appointment_follow_up_days_after: int = 1
    appointment_reminder_hour_utc: int = 18

    # Support requests (story 10.1). The team is emailed about each new request, with no
    # health data or client details in the email. The limits are assumed values
    # (docs/decisions/10.1-support.md).
    support_team_email: str = "support@genesishealth.local"
    support_message_max_length: int = 5000
    # Per account: every request emails the team.
    max_support_requests_per_hour: int = 10

    # Story 1.1: below this age, sign-up stops and no account is created. One age for every
    # state (docs/PLAN.md, question 22); the stories also name 19 and 21 for three states.
    age_of_majority: int = 18

    # Sign-in rules. Most are assumed values until the BA confirms them (docs/PLAN.md).
    trial_days: int = 14
    max_failed_sign_ins: int = 3
    lockout_minutes: int = 30
    code_ttl_minutes: int = 10
    code_max_attempts: int = 5
    code_resend_seconds: int = 60
    code_max_sends: int = 5
    # Per account, across all challenges, per hour. The second cap locks the account.
    max_codes_sent_per_hour: int = 10
    max_failed_codes_per_hour: int = 10
    # Wrong codes per account in 24 hours. Reaching it locks the account until the password
    # is reset: whoever is guessing already has the password (NIST 800-63B caps at 100).
    max_failed_codes_per_day: int = 30
    # A sign-up that isn't verified is deleted this long after its last code was sent.
    pending_sign_up_minutes: int = 60
    # Sign-up attempts for one email from one IP address per hour: stops one place flooding
    # someone's inbox with codes, without letting anyone else use up the owner's attempts.
    max_sign_ups_per_email_per_hour: int = 5
    reset_link_ttl_minutes: int = 60
    # Tries at a new password that equals the current one before the link closes, so a link
    # can't be used to test guesses at the current password.
    reset_link_max_failures: int = 5
    reset_request_cooldown_seconds: int = 60
    trusted_device_days: int = 30
    # Story 1.2: on the web, signed out after 30 idle minutes and after 12 hours in any case.
    # The mobile app stays signed in for up to 30 days on a trusted device; it locks itself
    # after 15 minutes in the background, which is the app's job.
    web_session_idle_minutes: int = 30
    web_session_max_hours: int = 12
    mobile_session_max_days: int = 30
    # Failed attempts allowed from one IP address across all accounts, per window.
    ip_failure_limit: int = 20
    ip_failure_window_minutes: int = 15

    # The admin panel (Phase A: Super Admin 1.1, 7.1, 7.2, 10.1, 11.1; Admin 1.1 to 1.3).
    # Assumed values are listed in docs/decisions/phase-a1-admin-access.md.
    # The admin panel's web app. Invite and reset emails link to these, with #token=... added.
    admin_panel_url: str = "http://localhost:5174"
    admin_invite_url: str = "http://localhost:5174/accept-invite"
    admin_password_reset_url: str = "http://localhost:5174/reset-password"
    # Super Admin 7.2 and Admin 1.1: an invite link works for 24 hours.
    admin_invite_hours: int = 24
    # Super Admin 1.1 and Admin 1.2: admins are signed out after 15 idle minutes. Their
    # sessions are always web sessions, so web_session_max_hours caps them too.
    admin_session_idle_minutes: int = 15
    admin_list_page_size: int = 20
    admin_list_max_page_size: int = 100
    # Super Admin 10.1: the audit log screen and its CSV export ("Very large export": ask for a
    # shorter date range above this many rows).
    audit_log_page_size: int = 50
    audit_log_max_page_size: int = 200
    audit_export_max_rows: int = 50_000
    # Super Admin 11.1: how much of a knowledge gap's question the in-app notification shows.
    admin_notification_question_max_length: int = 200

    # Notifications (story 12.1). The timings are the stories' or assumed values, which the
    # admin team will manage (docs/decisions/phase-9-notifications.md).
    notifications_page_size: int = 20
    notifications_max_page_size: int = 50
    # The types a client can turn off start on, by push; email is the channel for account,
    # billing and requests, so it's off for them until the client picks it.
    notification_email_by_default: bool = False
    inactivity_check_in_days: int = 30
    trial_ending_reminder_days: int = 3
    # For the phases that schedule their own reminders (3.3, 3.4, 6.1).
    guidance_follow_up_days: int = 14
    booking_follow_up_days: int = 7
    health_profile_review_months: list[int] = [3, 6, 12]
    # The reminder sweep (trial reminders and inactivity check-ins): how often it runs, how many
    # accounts one run handles per reminder, and how far back it catches up after downtime.
    reminder_sweep_seconds: int = 60
    reminder_sweep_batch_size: int = 200
    reminder_catch_up_days: int = 7
    # Devices per account that get pushes; registering another forgets the oldest.
    max_push_tokens_per_account: int = 10
    # Story 12.2: clients queued per batch of policy update emails.
    policy_email_batch_size: int = 100

    # The health profile (story 6.1). The question bank is app/health/questions.json unless
    # this names another file: the Health Intake Routing document's rule set can replace it
    # without a code change. The limits are assumed values, listed in
    # docs/decisions/phase-4-health-profile.md.
    health_question_bank_path: str | None = None
    health_text_max_length: int = 1000  # a typed answer, a write-in or a medicine's reason
    health_list_max_items: int = 30  # medicines, supplements or allergies in one answer
    # Story 6.1's Hypothalamus Circle Map: app/health/circle_map.json (a placeholder until
    # Deborah's map is in) unless this names another file.
    health_circle_map_path: str | None = None

    # My Visit Notes and visit logs (stories 5.1 and 5.2). Assumed values
    # (docs/decisions/phase-6-7-visits-wellness.md).
    visit_notes_search_max_length: int = 100
    # Rows in one visit log's Labs, Medicines or Next steps section.
    visit_log_max_rows: int = 30
    # 5.2's lab results reminder: this many days after the visit, for labs still pending or
    # drawn, at appointment_reminder_hour_utc.
    lab_results_reminder_days: int = 7
    # The latest logged visits given to the Oracle as context (ProfileContext.visits).
    oracle_visit_logs: int = 10

    # The Wellness Plan (story 7.1). Check-ins are sent at this hour UTC on the day an item's
    # time frame ends or it's due (question 8: time zones).
    wellness_check_in_hour_utc: int = 18
    # The Wellness Protocols library's tabs and sections are app/wellness/protocols.json unless
    # this names another file. Their content is the published Protocol items of the knowledge
    # base (Super Admin 6.1), matched by title.
    wellness_protocols_path: str | None = None
    # The product tabs' only link: the Genesis Shopify store's own pages, with nothing about the
    # client in them (SOW Appendix C). Placeholders until the store's links are known.
    wellness_shop_links: dict[str, str] = {
        "genesis-gold": "https://shop.example.com/products/genesis-gold",
        "sacred-seven": "https://shop.example.com/products/sacred-seven",
        "gen-pro": "https://shop.example.com/products/gen-pro",
    }
    # 7.1: "CALM links to the full guide on Deborah’s blog". A placeholder.
    calm_guide_url: str = "https://blog.example.com/calm"

    # The Home Dashboard (story 4.1). Assumed values (docs/decisions/phase-11-dashboard.md).
    # The greeting's time of day uses the time zone the app sends, or this one (question 8).
    home_dashboard_time_zone: str = "America/New_York"
    # "Good morning" from this hour, "Good afternoon" and "Good evening" from the next two;
    # before the morning hour it's still evening.
    home_dashboard_morning_hour: int = 5
    home_dashboard_afternoon_hour: int = 12
    home_dashboard_evening_hour: int = 18
    # What's next: at most this many steps (4.1's "one or two").
    home_dashboard_next_steps: int = 2
    # "How did your visit go? Log it here." for appointments up to this many days ago.
    home_dashboard_log_visit_days: int = 30

    # The admin panel's operations (Phase A part 2). Assumed values
    # (docs/decisions/phase-a2-admin-operations.md).
    admin_list_max_limit: int = 200  # rows per page in the admin lists
    admin_note_max_length: int = 5000  # the team's internal and review notes
    admin_reason_max_length: int = 500  # deactivation, rejection and dismissal reasons
    # Super Admin 5.2: open deletion requests due within this many calendar days are highlighted,
    # counted on the Dashboard, and reminded to the team once (11.1).
    deletion_highlight_days: int = 5
    # Super Admin 2.1's Top Health Topics: how many, and how many conversations a topic needs
    # before it's shown, so a rare topic can't point to one client.
    dashboard_topic_limit: int = 10
    dashboard_topic_min_count: int = 5
    # How often the admin sweep runs: new knowledge gaps (6.3: within 1 minute) and deletion
    # deadline reminders. Knowledge gap requests taken in per run, and the earlier gaps each new
    # question is compared with.
    admin_sweep_seconds: int = 30
    knowledge_gap_batch_size: int = 50
    knowledge_gap_match_candidates: int = 200
    # Super Admin 6.2's uploads (PDF, Word or text) and typed content.
    knowledge_upload_max_bytes: int = 20 * 1024 * 1024
    knowledge_text_max_length: int = 1_000_000
    knowledge_title_max_length: int = 200
    # Super Admin 8.1 and 8.2: what the admin panel accepts for a plan.
    plan_max_price_cents: int = 100_000
    plan_max_trial_days: int = 365
    plan_max_family_members: int = 20
    plan_max_features: int = 20
    plan_feature_max_length: int = 200
    # How long each process keeps the plan catalogue before reading billing_plans again.
    plan_catalog_cache_seconds: int = 30
    # Subscribers queued per batch of price change emails (8.1: told before it applies).
    price_change_email_batch_size: int = 100
    # Super Admin 9.2: a policy version's text, and its summary of changes shown to clients.
    policy_text_max_length: int = 200_000
    policy_summary_max_length: int = 1000


settings = Settings()
