# Phase A part 1: admin sign-in, Admin Management, My Profile, Audit Logs and admin notifications

Built on 5–6 Nov 2026 against Super Admin 1.1, 1.2, 7.1, 7.2, 10.1, 11.1, 12.1, 12.2 and Admin 1.1, 1.2, 1.3. Admin 7.1, 8.1, 9.1 and 9.2 are titles only in the BA's document; their Super Admin counterparts (10.1, 11.1, 12.1, 12.2) say "Admins can use this story", so those are what was built. No tests or migration yet (the parallel build's rules).

## What was built

| Piece | Where |
| --- | --- |
| Admins' sign-in rules in the shared `/auth/signin`, `/auth/verify`, `/auth/verify/resend`, `/auth/password/*` | `app/auth/service.py` |
| 15-minute inactivity sign-out and the admins' session messages | `app/auth/dependencies.py` |
| `AdminBackgroundSession` (the bell's polling doesn't count as activity) | `app/admin/dependencies.py` |
| Invite setup: `POST /admin/invitations/check`, `/accept`, `/verify`, `/verify/resend` | `app/admin/auth/` |
| Admin Management: `GET`/`POST /admin/admins`, `GET`/`PATCH /admin/admins/{admin_id}`, `POST .../deactivate`, `/reactivate`, `/resend-invite`, `/cancel-invite` | `app/admin/admins/` |
| My Profile: `GET`/`PATCH /admin/me`, `POST /admin/me/password`; Sign Out is `POST /auth/signout` | `app/admin/profile/` |
| Audit Logs: `GET /admin/audit-logs/filters`, `POST /admin/audit-logs/search`, `POST /admin/audit-logs/export` | `app/admin/audit/` |
| Admin notifications: `GET /admin/notifications`, `GET .../unread-count`, `POST .../read-all`, `POST .../{id}/read`, `GET`/`PUT /admin/notification-preferences`, and `notify_admins` | `app/admin/notifications/` |
| `scripts/create_super_admin.py` | `scripts/` |

## Design choices

### Sign-in (Super Admin 1.1 and 1.2, Admin 1.2 and 1.3)

- **Same endpoints as clients.** `users.role` decides the rules; `auth.service.is_admin` is `admin` or `super_admin`.
- **A code at every sign-in, on every device.** For admins, `sign_in` skips the trusted-device check and `_sign_in_after_code` creates no trusted device and returns no `device_token`.
- **Always a web session**, whatever `platform` says: the admin panel is a web app, and a declared `mobile` must not get a 30-day session with no idle timeout. Admin sessions last at most `web_session_max_hours` (12).
- **Inactivity:** 15 minutes (`admin_session_idle_minutes`) for admins on any platform. The message is the story's, built from the setting: "You’ve been signed out after 15 minutes of inactivity. Please sign in again." It's kept on later requests through `revoked_reason = signed_out_inactive`, as for clients.
- **Deactivated:** admins get Admin 1.2's "Your account has been deactivated. Please contact the Super Admin." at sign-in, at verify and on every request of a session ended by the deactivation (`deactivated_message(role)`).
- **Not set up (Admin 1.2):** a sign-in with an email that has no account but has an invite that's neither set up nor cancelled (expired ones included) gets 403 `account_not_set_up`, "Please set up your account using the link in your invite email." It's recorded as `auth.sign_in.failed` with reason `not_set_up`, so the per-IP limit counts it.
- **Code messages:** admins' codes have the `sign_in` purpose, whose texts are the same as the admin stories'.
- **Lock, forgot and reset password:** unchanged; the admin stories' messages are the same as the clients'. Forgot password already sends no link for an unknown or deactivated account; an Admin who hasn't set up has no account, so gets none either (Admin 1.3).
- **Emails:** admins get the admin panel's own wording and links (`app/admin/auth/emails.py`): the sign-in code ("at every sign-in", not "from a new device"), the reset link (`admin_password_reset_url#token=...`) and the password-changed confirmation.
- **Client sign-up never makes an admin:** `SignUpRequest` already refuses unknown fields such as `role`, and `_verify_sign_up` now sets `role="client"` explicitly. Admins come only from an invite; the Super Admin only from the script.

### Invitations and setup (Super Admin 7.2, Admin 1.1)

- **One row per invited Admin**, `admin_invitations`: the invite, then the account it became (`user_id`, `accepted_at`). It's also the Admin's row in Admin Management, so the listing keeps "date added" (`created_at`) and "who added them" (`invited_by_id`) after setup. Its id is the `admin_id` in the API.
- **The token:** 32 random bytes, stored as SHA-256, in the link's fragment (`admin_invite_url#token=...`), and always sent in a POST body. Valid 24 hours (`admin_invite_hours`). Resend replaces it (the old link stops working) and restarts setup; cancel closes it.
- **Setup in two steps, as Admin 1.1 says:** `accept` checks the password rules, keeps the Argon2 hash on the invite and emails a 6-digit code; `verify` with the right code creates the account (role `admin`, the invite's names and email, `email_verified_at` now, `trial_ends_at` now because the column is required), marks the invite used, clears the password and code fields, and notifies the Super Admin (`admin_set_up`). The Admin then signs in normally, with a new code. Until the code is verified the link can be used again (Admin 1.1's "closes the page before finishing"); doing so replaces the password.
- **Setup codes** live on the invite row (`code_hash`, `code_expires_at`, `code_attempts`, `code_send_count`), because a `verification_challenges` row needs an account or a pending sign-up as owner. Same rules as sign-in codes: 10 minutes, 5 tries, resend after 60 seconds, at most 5 per link. A second `accept` within 60 seconds keeps the code already sent. They're recorded as `auth.code.sent`, `auth.code.failed` (actor: the invite's id) and `auth.code.rejected`, so the per-IP limits on codes cover them.
- **One open invite per email** (a partial unique index on `email` where `accepted_at` and `cancelled_at` are null). An expired invite stays open, so the Super Admin resends it rather than inviting again.
- **Email checks at invite time:** an Admin's or the Super Admin's email, or an open invite's, gets 7.2's "An admin with this email address already exists."; a client's gets a message of its own (below), because `users.email` is unique.

### Admin Management (Super Admin 7.1)

- Super Admin only (`SuperAdminSession`): an Admin gets 403 "Only the Super Admin can do this.", a client 404.
- **Statuses:** `invite_pending`, `invite_expired`, `active`, `deactivated`. Cancelled invites are left out. The Super Admin isn't listed.
- **Listing:** newest first; search on first name, last name, full name and email (`ILIKE`, with `%` and `_` taken literally); filter by status; `limit`/`offset` with `total`. Last active is the latest `sessions.last_seen_at`.
- **Details** include `added_by`, `permissions` (7.2's list), the `actions` available now, `invite_expires_at`, and, for a deactivated Admin, `deactivated_at` and `deactivation_reason`. `deactivate_confirmation` carries 7.1's dialog text.
- **Edit:** first and last name (on the account, or on the invite before setup). `email` may be sent unchanged; a different one is refused.
- **Deactivate** needs a reason (`admin_reason_max_length`, 500): `users.status = deactivated`; every session ends now with `revoked_reason = account_deactivated`; open codes and reset links close. Nothing else changes, so the Admin's name stays on what they did. **The reason is stored in the audit event's details** (`admin.deactivated`), as Super Admin 3.2 asks for clients, and read back from there for the details screen; the audit screen shows it for `*.deactivated` and `*.reactivated` events only.
- **Reactivate:** status back to active, the sign-in lock cleared; the next sign-in needs a code as always.
- Database failures give 7.1's "We couldn’t do that just now. Please try again." (503), and 7.2's "We couldn’t send the invite just now. Please try again." for invite and resend.

### My Profile (Super Admin 12.1 and 12.2)

- `GET /admin/me`: first and last name, email, role, `signed_in_at` (this session) and `previous_sign_in_at` (the one before, null for a first sign-in), and `two_step_verification: "on"`.
- `PATCH /admin/me`: first and last name; `email` may be sent unchanged only. Audited as `admin.profile_updated` with the changed field names.
- `POST /admin/me/password` is the clients' change-password flow (identical rules and messages): this session stays, every other one ends, a confirmation is emailed.
- Sign Out is the shared `POST /auth/signout` (audited as `auth.signed_out`). The "back button" rule is the panel's (`Cache-Control: no-store` is already on every response).

### Audit Logs (Super Admin 10.1)

- **Read-only.** No endpoint changes `audit_events`; the database trigger refuses UPDATE, DELETE and TRUNCATE.
- **Filters are POSTed** (`/search`, `/export`), because a search can be a Client's name or email and URLs reach server logs.
- **Search** matches the actor's name or email, or the account or Admin invite the event is about.
- **Roles:** `client`, `teen` (a client under the age of majority, counted on Hawaii's date like `is_adult`), `admin`, `super_admin`, `system` (no actor and no IP address: jobs and scripts), and `anonymous` (a request from someone with no account, such as a sign-in with an unknown email, or an unverified sign-up).
- **Categories** (`app/admin/audit/catalog.py`): 10.1's groups `sign_in_security`, `client_accounts`, `consent`, `data`, `escalations`, `support_requests`, `knowledge_base`, `admins`, `plans`, `admin_views`, plus `subscriptions` (Clients' `billing.*` events) and `other` (client activity with no group, such as `conversation.started`). An action's category is its explicit entry, else `admin_views` for any action ending in `.viewed`, else its prefix (`auth.`, `account.`, `profile.`, `client.`, `teen.`, `consent.`, `policy.`, `health_consent.`, `deletion.`, `legal_hold.`, `escalation.`, `support.`, `knowledge.`, `content.`, `admin.`, `plan.`, `plans.`, `price.`, `billing.`, `audit.`). The other admin packages' actions fall into the right group if they follow these prefixes; `category_condition` is the same rule in SQL.
- **What an entry shows:** time, who (name, email, role), the action's label, its category, what it affected (type, id, and a name for accounts and Admin invites), device and IP address **for sign-in and security events only**, and the reason for deactivations and reactivations. Other `details` are never shown: their field names could hint at health information.
- **Admins see everything except `subscriptions`** (7.2: Admins can't see Clients' subscription details). Asking for that category gets 403.
- **Export:** CSV (`text/csv`, `audit-log-YYYYMMDD-HHMMSS.csv`), the filtered entries newest first, at most `audit_export_max_rows` (50,000); above that, 422 `export_too_large` with 10.1's message. Cells starting with `=`, `+`, `-`, `@`, tab or carriage return get a leading `'`, so a spreadsheet won't run a name as a formula. The export is recorded as `audit.exported`, with the row count and filters but not the search text, in the same transaction. A database failure gives 10.1's "We couldn’t export the audit logs. Please try again." (503). "Your audit log export has downloaded." is the panel's to show.
- Paging is `limit`/`offset` with `has_more` (no total: counting a six-year table on every page is slow).

### Admin notifications (Super Admin 11.1)

- **A separate package, not `app/notifications/`.** The clients' package is built around profiles, push, consent, plans and five-way preferences; admins have none of those, and their preferences are only email on or off per type. Separate tables: `admin_notifications` (one row per recipient) and `admin_notification_preferences`.
- **`notify_admins(db, kind, data=None, *, target_id=None, super_admin_only=False)`** in `app/admin/notifications/service.py`, also importable from `app.admin.notifications` (as `app/admin/common.py`'s `alert_admins` does). It adds one in-app notice per active Admin and the Super Admin (or the Super Admin alone), and queues the email job for each recipient who hasn't turned the type off. It doesn't commit.
- **Kinds:** `support_request` (needs `request_type`: `talk_to_support`, `consultation`, `email_change`, `knowledge_gap`), `knowledge_gap` (optional `question`, in-app only, cut to 200 characters), `deletion_request`, `deletion_deadline` (`days`, default `deletion_highlight_business_days`), `content_pending_approval` (Super Admin only), `knowledge_sync_failed`, `policy_published` (optional `policy`: `terms`, `privacy`, `health_consent`), `admin_set_up` (Super Admin only, `name`). The names match the other part's `alert_admins`.
- **No escalation kind**: 11.1 says escalations aren't notified. Client exports aren't either.
- **Emails** say only the kind's general text (no question, name or request type) and link to the admin panel. The job re-checks that the recipient is still an active admin and still wants the email.
- **Preferences:** email on by default; in-app always on; `deletion_deadlines` can't be turned off (also a database check), and is accepted in `PUT` only unchanged. Admins aren't offered `admins` (new Admin set-ups go to the Super Admin only).
- **Screens:** `support_request`, `knowledge_gap`, `deletion_request`, `content_review`, `knowledge_base`, `policy_versions`, `admin` (target: the Admin's row).

### The Super Admin

- `scripts/create_super_admin.py --email ... --first-name ... --last-name ...`; the password is asked for twice at the prompt (never on the command line or in code) and must follow the password rules. It refuses when a Super Admin exists or the email is used, and records `admin.super_admin_created` (actor: system).
- **Only one Super Admin:** a partial unique index on `users.role` where `role = 'super_admin'` (`uq_users_one_super_admin`, declared in `app/admin/auth/models.py` because `app/auth/models.py` belongs to another part of the build).
- 12.1: the Super Admin's email is changed by Tkxel; there's no endpoint.

### Stored codes

- `admin_invitations`: no status column; status is worked out from `accepted_at`, `cancelled_at`, `expires_at` and the account's `status`.
- Audit actions added: `admin.invited`, `admin.invite_resent`, `admin.invite_cancelled`, `admin.invite_accepted` (password set, code sent), `admin.invite_rejected` (an unknown, used, cancelled or expired link, or the email taken), `admin.set_up`, `admin.edited` (`fields`), `admin.deactivated` (`reason`), `admin.reactivated`, `admin.profile_updated` (`fields`), `admin.super_admin_created`, `audit.exported`; `auth.code.*` with `purpose: admin_setup`; `auth.sign_in.failed` with reason `not_set_up`.
- Job kind: `admin_notifications.email`.
- Error codes: `account_not_set_up`, `invite_expired`, `email_taken`, `setup_not_started`, `too_many_codes`, `resend_too_soon`, `code_wrong`, `code_expired`, `admin_not_found`, `email_locked`, `already_set_up`, `not_set_up`, `already_deactivated`, `already_active`, `send_failed`, `export_too_large`, `export_failed`, `cannot_turn_off`, `unknown_category`, `notification_not_found`, `super_admin_only`.

## Messages not in the stories

| Situation | Message |
| --- | --- |
| Inviting a client's email | "This email address belongs to a client account. Please use a different email address." |
| Inviting with an empty email | "Email is required." (Super Admin 1.1's) |
| Setting up when the email has meanwhile become a client account | "An account with this email address already exists. Please ask the Super Admin to send a new invite." |
| Resending a setup code before a password was set | "Please set your password first." |
| A sixth setup code on one link | "You’ve asked for too many codes. Please ask the Super Admin to send a new invite." |
| Resending a setup code within 60 seconds | "Please wait a minute before asking for a new code." (the clients') |
| Unknown or cancelled Admin | "We couldn’t find that admin." |
| Resending or cancelling an invite already set up | "[First name] has already set up their account." |
| Deactivating or reactivating before setup | "[First name] hasn’t set up their account yet. You can cancel the invite instead." |
| Deactivating twice / reactivating an active Admin | "[First name] is already deactivated." / "[First name] is already active." |
| Changing an Admin's email in Edit | "The email address can’t be changed. To use a different one, deactivate this admin and invite them again with the new address." |
| Edit saved | "[First name]’s details have been updated." |
| Changing one's own email in My Profile | "Your email address can’t be changed here." |
| A deactivation reason over 500 characters | "Please keep this to 500 characters or fewer." |
| Audit filter end before start | "Please choose an end date after the start date." |
| An Admin asking for the subscriptions category | "Only the Super Admin can do this." |
| An Admin saving the Super Admin-only preference | "This notification type isn’t available." |
| Unknown notification | "We couldn’t find that notification." |
| Notification texts (titles, bodies, emails) | in `app/admin/notifications/kinds.py` |
| Invite, setup code, sign-in code, reset and password-changed emails | in `app/admin/auth/emails.py` |

## Assumed values (all settings)

| Setting | Value | Why |
| --- | --- | --- |
| `admin_invite_hours` | 24 | 7.2, Admin 1.1 |
| `admin_session_idle_minutes` | 15 | 1.1, Admin 1.2 |
| Admin session maximum | `web_session_max_hours`, 12 | not in the stories |
| `admin_panel_url`, `admin_invite_url`, `admin_password_reset_url` | `http://localhost:5174`, `/accept-invite`, `/reset-password` | the admin panel's dev server, to agree with the frontend |
| `admin_list_page_size` / `admin_list_max_page_size` | 20 / 100 | |
| `audit_log_page_size` / `audit_log_max_page_size` | 50 / 200 | |
| `audit_export_max_rows` | 50,000 | 10.1's "Very large export" |
| `admin_notification_question_max_length` | 200 | 11.1's "with the question" |
| Account lock, codes, reset link | the clients' settings | the admin stories give the same values |

## Open questions for the BA

1. **A code at setup and again at the first sign-in.** Admin 1.1 asks for a code after the password is set, then sends the Admin to Sign In, which asks for another. Is the second one intended, or should setup sign them straight in?
2. **"Account not set up" reveals invites.** Admin 1.2's message tells anyone who types an invited email (with any password) that it has a pending admin invite. Acceptable, or should it show the general sign-in error?
3. **Client emails and admin invites.** Can an Admin's work email also be a client's account? We refuse it (one account per email); and a client who signs up with an invited address before setup blocks the invite until the Super Admin re-invites with another address.
4. **Audit log "who" for unknown visitors.** 10.1 lists Client, Teen, Admin, Super Admin and System; we added "Not signed in" for failed sign-ins with unknown emails and unverified sign-ups. OK?
5. **Admins and the audit log's billing events.** 10.1 says Admins see the same as the Super Admin; 7.2 says they can't see Clients' subscription details. We hide Clients' billing events from Admins and show plan and price changes. Right?
6. **Deactivation reasons** for Admins are kept in the audit log (like 3.2 for Clients), where they can never be deleted. Is that acceptable for free text about a staff member?
7. **Admin session length.** The stories set 15 idle minutes but no maximum; we use the web's 12 hours.
8. **Support requests and new deletion requests** still reach the team by `support_team_email` from their own jobs. Should they move to `notify_admins` (11.1's per-person emails and preferences), replacing the shared mailbox?

## For other parts of the build

- **Wiring:** the support package (new support request), the privacy package (new deletion request) and policy publishing should call `notify_admins(db, "support_request", {"request_type": kind}, target_id=...)`, `notify_admins(db, "deletion_request", target_id=...)` and `notify_admins(db, "policy_published", {"policy": kind}, target_id=...)`. `app/admin/common.py`'s `alert_admins` already reaches the other kinds.
- **`ClientSession` should refuse admin roles.** Today an Admin who accepts the client policies through `/me/policy-acceptances` could use the client endpoints (profiles, conversations) and store health data on an admin account. `app/accounts/dependencies.py` belongs to another part.
- **`users.role` check constraint** (`role IN ('client', 'admin', 'super_admin')`) belongs in `app/auth/models.py`.
- **Email uniqueness** still relies on lowercasing (PLAN, Phase 1); admin tools now write users, so the `lower(email)` unique index is due.
- **Before production:** the setup code, like every code, is plain SHA-256 (PLAN's HMAC item); and admin sessions should be checked against an IP allow-list or SSO if the team wants one.

## Added during integration

- **Admins can't use the client app:** `ClientSession` refuses any account whose role isn't `client` with 403 `clients_only`, "This part of the app is for clients." (not in the stories), so no health data can be stored on an admin account.
- **Admin alerts wired:** every new support request (`support.service._add`, any kind, carrying only its type) and every new deletion request (`privacy.service`) calls `notify_admins`.
- **`ck_admin_invitations_accepted` is now `user_id IS NULL OR accepted_at IS NOT NULL`** (was `(accepted_at IS NULL) = (user_id IS NULL)`), after the migration review: `user_id` is SET NULL when the account is deleted, which the old check refused. An accepted invite keeps its row, so the invite history survives.
