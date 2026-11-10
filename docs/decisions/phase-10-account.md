# Phase 10: 11.1 View & Edit My Profile and 11.4 Revoke Consent / Delete Account: decisions

Built on 5 Nov 2026 against the 5 Nov Client stories "View & Edit My Profile" (11.1) and "Revoke Consent / Delete Account - (Export My Data)" (11.4), and Super Admin 5.1 (Email Change Requests) and 5.2 (Manage Data Deletion Requests). No tests or migration yet (see the end).

## What was built

| Piece | Where |
| --- | --- |
| `GET /me/profile`, `PATCH /me/profile`, `POST /me/email-change-request` | `app/accounts/router.py`, `service.py` |
| `change_email(db, admin, support_request_id, send)`: the team's Change email address (Phase A calls it) | `app/accounts/service.py` |
| The policy gate's new refusals, `PrivacySession`, `next-step`'s new steps, re-consent through `POST /me/policy-acceptances` | `app/accounts/dependencies.py`, `service.py` |
| `GET /me/privacy`, `GET /me/export`, `POST /me/consent/revoke`, `POST /me/deletion-request`, `POST /me/deletion-request/transfers/{transfer_id}/resend`, `POST /me/deletion-request/cancel-transfer` | `app/privacy/router.py`, `service.py` |
| `POST /profile-transfers/check`, `POST /profile-transfers/accept` (no sign-in) | `app/privacy/router.py` |
| The team's side: `start_review`, `complete_request`, `place_legal_hold`, `lift_legal_hold`, `decline_request` (no endpoints yet) | `app/privacy/service.py` |
| The export file | `app/privacy/export.py` |
| The purge, and the deleted-conversation purge | `app/privacy/purge.py` |
| Jobs: team email, purge, completion email, the privacy sweep | `app/privacy/jobs.py` |
| Phase 3b hooks for invited teens | `app/privacy/teens.py` |
| `ConsentRevocation`, `ProfileTransfer`; `DeletionRequest` extended | `app/accounts/models.py` |
| The `email_change` support request kind, with `requested_email` | `app/support/` |
| `notifications.consent_revoked()` made real | `app/notifications/service.py` |

## 11.1 View & Edit My Profile

- **`GET /me/profile`** (policy gate): first name, initial, email, date of birth, country, state and its name, `age_rules` (`adult` or `teen`), `email_change_requested` with `requested_email`, and `advocate_only`. No phone. The ZIP code (`zip_code`) is back since 6 Nov, and Edit can change it (R1c in `docs/PLAN.md`). The settings menu is the app's.
- **`advocate_only`** is true for an account past onboarding with no own profile in use: deleted through 11.4's advocate only, or only ever added family members (2.2).
- **`PATCH /me/profile`** edits `first_name` and `state`. The app may send the whole form: `email`, `date_of_birth` and `country` are accepted unchanged and refused if different (`read_only`, or the country message). An empty first name or state gets the story's message.
- **State and the age of majority:** a new state is checked against the date of birth with `age_on` and `us_today` from `app/core/ages.py`, against `accounts.service.age_of_majority_in(state)`. That returns `settings.age_of_majority` (18) for every state, because the age is 18 everywhere (question 22), so the confirmation can't be triggered today. The flow is built:
  - a state that would put an adult below its age answers 409 `teen_rules_confirmation_required` with 11.1's message (field `state`), and nothing is saved;
  - the app shows Confirm or Cancel, and Confirm sends the same edit with `confirm_teen_rules: true`;
  - a per-state table belongs in `ages.py`, so `is_adult`, `age_group` and this check follow the same ages. The Oracle's teen rules come from `age_group` on the profile's date of birth, which knows no state, so per-state ages would need the profile context to use the state too.
- **Audit:** `account.details_updated` (field names), `account.state_changed` (`from` and `to` state codes: a state isn't a HIPAA identifier), `account.age_rules_changed` (`to`).
- **Email change** (PLAN's assumed value: support only):
  - `POST /me/email-change-request` `{client_request_id, new_email}` stores a `support_requests` row of kind `email_change` with `requested_email` and an empty message;
  - it goes through support's `_add`, so the team's email job, the `support.request_sent` audit event and the 10-an-hour limit apply;
  - a resend with the same `client_request_id` answers 200;
  - refused: the current address (422), an address another account uses (409, as 11.1 asks), and a second request while one is open (409, also a partial unique index);
  - the profile shows "Email change requested" (the response's `message`) until the team acts.
- **`change_email`** (Phase A's button on the request):
  - checks the role;
  - refuses an address taken meanwhile (409; the team contacts the client);
  - changes `users.email`, ends every session, clears trusted devices, and closes open codes and reset links (`accounts.service.sign_out_everywhere`);
  - resolves the request (`support.mark_email_change_done`), audits `account.email_changed` with the admin as actor;
  - sends Phase 9's `email_changed` notice (its email copy goes to the new address), and emails the old address directly. If the notice can't go (consent revoked), the new address is emailed directly too.

## 11.4: what works in each state

`ClientSession` (the policy gate) now refuses, in this order:

1. `deletion_requested` 403, "Your account is already scheduled for deletion.": an open whole-account request;
2. `access_paused` 403 with the long paused message: `teens.access_paused` (Phase 3b);
3. `consent_revoked` 403, "Please accept our Terms of Service, Privacy Policy and Health Consent to continue.";
4. `policy_update_required` 403, as before.

`/me/next-step` returns `deletion_requested`, then `access_paused`, before `policy_update`. Privacy & Data uses `PrivacySession` (the plain signed-in session):

| State | Privacy & Data, export | Revoke consent | Delete |
| --- | --- | --- | --- |
| Consent revoked | yes | already done (200) | yes |
| Updated policies not accepted | yes | yes | yes |
| Marked for deletion | yes | 409 | 409 "already scheduled" |
| Invited teen who lost access | yes | never (403) | yes, as a Teen Deletion |

Export stays open while marked for deletion (HIPAA right of access while the data still exists); see the questions.

## 11.4 Revoke consent and re-consent

- **Revoking:** `POST /me/consent/revoke` adds a `consent_revocations` row (one open per account). Then:
  - every session ends, this one included; trusted devices stay trusted;
  - `teens.pause_for_revoked_consent` is called (Phase 3b);
  - it's audited as `consent.revoked`;
  - nothing is deleted. It's safe to repeat. A teen account gets 403.
- **While revoked:**
  - every gated endpoint refuses, so the Oracle isn't called;
  - `notifications.consent_revoked` is true, so nothing is sent, and the sweeps and policy emails skip the account;
  - scheduled reminders aren't cancelled. Any that fall due meanwhile are dropped when due, like 8.2's turned-off members.
- **Giving it again:**
  - `GET /me/pending-consents` returns the current Terms of Service, Privacy Policy and Health Consent;
  - `POST /me/policy-acceptances` must tick all three (else 422 `consent_required` with the story's text);
  - it records any new acceptances and the Health Consent for the client's own profile, closes the revocation, audits `consent.given_again`, and calls `teens.restore_after_consent`. Family members' consents stay as they were ("continue as before");
  - refused while the account is marked for deletion.
- **A deletion request also withdraws consent** for the Oracle and notifications (11.4 calls it a "Revoke Consent / Deletion Request"). `accounts.service.consent_withdrawn` and `notifications.consent_revoked` are true while a whole-account request is open. No revocation row is written, so a declined request leaves consent as it was.

## 11.4 Delete Account

`POST /me/deletion-request` `{option, transfers}`:

- **No family members:** no option needed ("everything").
- **Family members exist** (finished, not already being deleted, turned off or not): `option` is required, else 422 with "Do you want to keep your family members’ profiles?" (field `option`).
- **everything:** a `deletion_requests` row `kind=account, option=everything, status=pending`, due in 10 business days. The account is marked for deletion; every session ends; scheduled reminders are cancelled; the team is emailed. The answer is "Your request has been sent. Your information will be deleted within 10 business days." with the request.
- **advocate_only:** `kind=account, option=advocate_only, profile_id=` the client's own profile. That profile gets `deletion_requested_at`, so it can't be used, and its reminders are cancelled. The account, sessions, family members and subscription carry on.
- **transfer:** `transfers: [{profile_id, email}]`, at least one:
  - each member must be one of the client's finished family members who has reached the age of majority (the client's state's, since managed profiles have none), else 422 `not_of_age` with the story's message;
  - each email must be valid, not the client's own, and not used twice, else "Please enter a valid email address for [Name].";
  - the request is `waiting_for_transfer`; each member gets a `profile_transfers` invite (token hashed, in the link's `#` fragment, valid `transfer_invite_days`);
  - otherwise it marks the account as for everything;
  - members not chosen, and those under the age, are deleted with the account.
- **Invited teens** (Phase 3b): `GET /me/privacy` lists their first names (`invited_teens`) for the story's "[Name] has their own account..." text, and the purge calls `teens.parent_account_deleted`, which never deletes their data.
- **Already scheduled:** 409 "Your account is already scheduled for deletion." Advocate only asked again: 409 (not in the stories). A database failure: 503 "We can’t process your request at the moment. Please try again later."
- **Lock order** for whole-account work: account row, transfer invites, deletion request, profiles, the same as a cascading `DELETE FROM users`. 8.2's purge keeps 8.2's member-then-account order.

### Transfers

- **The client:** `GET /me/privacy` shows the request and its invites. `.../transfers/{id}/resend` sends a new link (the old one stops working), at most once a minute. `.../cancel-transfer` cancels unaccepted invites and sends the request to review: the remaining members are deleted with the account (Super Admin 5.2).
- **The family member:** `POST /profile-transfers/check {token}` shows their first name, date of birth, the invite email (locked) and the policies. `POST /profile-transfers/accept {token, password, confirm_password, state, policy_version_ids}` then:
  - creates their account with the invite email (verified by the link), the profile's first name and date of birth, their state, and a 14-day trial like any new client;
  - records the Terms, Privacy Policy and their own Health Consent;
  - moves the profile in full: it becomes their own (`is_self`, family-only fields cleared) with its conversations, summaries, notes and health profile;
  - removes what the old account held about it: its notifications and reminders, support requests' link to it, the old account's feedback on its conversations, and billing's paused-member row;
  - once no invite is pending, sets the request back to `pending` for the team;
  - emails the client "a family member has accepted" directly, since notifications have stopped for an account waiting for deletion, and sends the new account 1.1's "account created" email.
- **Refused:**
  - a used, cancelled, expired or made-up link: 1.3's "This link has expired. Please request a new one.";
  - a member who doesn't meet the age check in the state they give: the story's age message;
  - an email that already has an account: 409, see questions.
- **Not moved:** escalation records keep the old account's id; they're the record of what happened.

### The team's side (Super Admin 5.2, no endpoints yet)

Each function checks the role is `admin` or `super_admin`.

- `start_review`: `pending` → `in_progress`.
- `complete_request(identity_confirmed, legal_hold_checked)`:
  - refused without both checklist items ("Please complete the review checklist first."), on legal hold, waiting for transfer, completed or declined;
  - marks it `completed` (`completed_at`, `completed_by_id`) and queues the purge;
  - returns "The deletion is complete, and [First name] has been emailed." The purge runs within seconds and sends the email.
- `place_legal_hold`: `on_legal_hold`, and the client is emailed. Allowed on a completed request the purge hasn't carried out yet, which then waits. Returns 5.2's "This request is on legal hold. The Client has been told."
- `lift_legal_hold`: back to `pending`, or `waiting_for_transfer` while invites are open.
- `decline_request` (PLAN's existing "declined"): the profile's `deletion_requested_at` is cleared, open invites are cancelled.

## The purge

`privacy.purge_request` runs for a `completed` request with no `purged_at`. Anything else is left alone, so a hold placed meanwhile wins and a rerun does nothing.

| Request | Deleted | Then |
| --- | --- | --- |
| family_member (8.2) | the member's profile | 8.2's "[Name]’s data has been deleted." notice (`deletion_complete`) |
| account, advocate_only | the client's own profile; the account keeps its details (question 41) | the completion email |
| account, everything / transfer | every profile still on the account, then the account | `teens.parent_account_deleted`; the email |
| teen (Phase 3b) | the teen's account, the same way | `teens.remove_from_family`; the email |

- **A profile's purge** deletes the feedback on its messages explicitly, then its conversations (messages cascade), then the profile. The foreign keys take Health Consents, notifications, the health profile and answers, guidance summaries and provider notes (they cascade from conversations and profiles), and billing's paused-member row. Support requests and transfer invites keep their row with the profile set to null.
- **A whole account** also cancels its reminders and marks its other open requests completed (covered by this one). `DELETE FROM users` cascades the rest: sessions, devices, acceptances, support requests, subscriptions, invoices, notifications, revocations, invites.
- **Kept:** the audit log, escalation records (3.2's 6 years: plain ids, no foreign keys, so a purge never reaches them; the message text they point to goes), and the deletion request (no names or health data).
- **The completion email** ("once the deletion is complete") is its own job. For a deleted account, the purge copies the address to `deletion_requests.notify_email`, and the email job clears it once sent.
- **Deleted conversations** (question 45): the privacy sweep purges conversations deleted more than `deleted_conversation_purge_days` (7) ago, with their messages, feedback, summary and notes, a batch at a time, audited `conversation.purged`. Escalations stay. Accounts with any request on legal hold keep theirs.
- **Team emails:** each request made here queues `privacy.notify_team` at once (type, id, received and due date; no names). 8.2's removals are made in the profiles package without a job, so the sweep queues one for any request not yet notified (`team_notified_at`).
- **The sweep** runs every `privacy_sweep_minutes` (15), started by an `@on_startup` hook, like Phase 9's.

## Export

`GET /me/export` returns `your-oracle-data-YYYY-MM-DD.json` (`Content-Disposition: attachment`, `no-store` like every response). Nothing is stored or emailed. It's audited as `account.data_exported`; a database failure gets "We couldn’t download your data just now. Please try again."

- **JSON**, since the story names no format (question 12). Version 1, picked field by field.
- **In it:**
  - the account details and plan;
  - the policies accepted, and the consent history;
  - each profile the account holds: intake answers (the advocate consent too: it's the client's own statement), Health Consents and health profile answers (by question key);
  - each conversation's messages (text, tapped answers, widgets, the client's feedback), its guidance summary, and its provider-ready notes with every version.
- **Left out:**
  - invited teens: their profiles aren't the parent's account's, so they're never selected;
  - deleted conversations;
  - safety-check internals and escalations;
  - the team's notes;
  - unconfirmed health facts.
- **Visit logs and the Wellness Plan** (Phases 6 and 7) were added to `build_export` during integration: each profile gets `visit_logs` (with the Oracle's review once it's ready) and `wellness_plan` (current content, items including removed ones, and earlier versions).
- The story's "secure download link" and "availability period" (question 12) don't apply: the file is the response itself.

## Stored codes

- `deletion_requests.kind`: `family_member`, `account`, `teen`. `option` (account only): `everything`, `advocate_only`, `transfer`. `source`: `in_app`, `by_email` (Phase A). `status`: `waiting_for_transfer`, `pending`, `in_progress`, `on_legal_hold`, `completed`, `declined`.
- `profile_transfers.status`: `pending`, `accepted`, `cancelled`.
- `support_requests.kind` adds `email_change` (team label "Email Change Request").
- Jobs: `privacy.notify_team`, `privacy.purge_request`, `privacy.completion_email`, `privacy.sweep`.
- Audit actions:
  - account and consent: `account.details_updated`, `account.state_changed`, `account.age_rules_changed`, `account.email_changed`, `account.data_exported`, `consent.revoked`, `consent.given_again`;
  - deletion requests: `account.deletion_requested`, `deletion.review_started`, `deletion.completed`, `deletion.legal_hold_placed`, `deletion.legal_hold_lifted`, `deletion.declined`, `deletion.purged`, `conversation.purged`;
  - transfers: `account.transfer_invited`, `account.transfer_invite_resent`, `account.transfer_cancelled`, `account.transfer_accepted`, `account.transfers_done`;
  - also `auth.signed_up` (details `source: profile_transfer`) and `health_consent.accepted`.
  - None holds health data, names or emails.
- `next_step` adds `deletion_requested` and `access_paused`.

## Messages not in the stories

| Situation | Code | Message |
| --- | --- | --- |
| Profile saved | | "Your details have been updated." |
| Edit sends a different email | `read_only` | "Your email address is used to sign in, so it can’t be changed here. Please use Request email change." |
| Edit sends a different date of birth | `read_only` | R2's "Your date of birth comes from sign-up, so it can’t be changed here. If something is wrong, please contact the support team." |
| Edit sends another country | `validation_error` | "Your Oracle is for U.S. users only, so the country can’t be changed." |
| Unknown state code | `validation_error` | 1.1's "Please enter a valid state." (empty is 11.1's "Please choose your state.") |
| Email change to the current address | `same_email` | "This is already your email address." |
| Email change to an address in use | `email_taken` | "This email address is already used by another account." |
| Second email change while one is pending | `email_change_pending` | "You’ve already asked to change your email address. The support team will be in touch." |
| Email change sent | | "Email change requested" (11.1's profile label) |
| Team: email change already done | `already_resolved` | "This email change request has already been resolved." |
| Team: email changed | | "The email address has been changed, and the client has been told." |
| Consent revoked | | "Your consent has been revoked, and you’ve been signed out on all your devices. Your information has been kept." |
| A teen tries to revoke | `teen_cannot_revoke` | "Your parent or guardian gave consent for your account, so it can’t be revoked here." |
| advocate_only or transfer with no family members | `no_family_members` | "You don’t have any family members’ profiles to keep." |
| advocate_only with no own profile | `no_own_data` | "There’s no health information of your own to delete." |
| advocate_only asked again | `own_data_pending` | "You’ve already asked for your own health information to be deleted." |
| transfer with no members | `transfer_required` | "Please choose at least one family member to take over their profile." |
| Same member twice | `duplicate_transfer` | "Please choose each family member only once." |
| A member being deleted (8.2) | `deletion_requested` | 8.2's "[Name]’s data is being deleted, so their profile can’t be changed." |
| Unknown or another account's profile | `profile_not_found` | "We couldn’t find that profile." |
| Unknown invite (client side) | `transfer_not_found` | "We couldn’t find that invite." |
| Resend of an answered invite | `transfer_not_open` | "This invite has already been accepted or cancelled." |
| Resend within a minute | `resend_too_soon` | "Please wait a minute before sending the invite again." |
| Resent | | "We’ve sent the invite to [Name] again." |
| Cancel with nothing waiting | `no_transfer` | "There’s no transfer waiting to be cancelled." |
| Transfer cancelled | | "Your transfer has been cancelled. Your remaining family members’ profiles will be deleted with your account." |
| Invite link used, expired, cancelled or made up | `invite_expired` | 1.3's "This link has expired. Please request a new one." |
| Invite email already has an account | `email_taken` | "There’s already a Your Oracle account with this email address. Please contact the support team." |
| Transfer accepted | | "Your account is ready. Please sign in with your email address and new password." |
| Team: not an admin, unknown request | `not_allowed`, `deletion_request_not_found` | "Only the support team can do that.", "We couldn’t find that deletion request." |
| Team: complete while waiting, completed, declined | `waiting_for_transfer`, `already_completed`, `declined` | "This request is waiting for family members to accept their transfer invites.", "This request has already been completed.", "This request has been declined." |
| Team: other confirmations | | "This request is in progress.", "The legal hold has been lifted.", "This deletion request has been declined." |
| Emails | | the transfer invite, transfer accepted, deletion complete, legal hold, the team's "New deletion request: [Type]", and 11.1's two "Your email address was changed" (texts in `app/privacy/emails.py` and `app/accounts/emails.py`; no names or health data) |

## Assumed values (settings)

| Setting | Value | Why |
| --- | --- | --- |
| `transfer_invite_url` | `http://localhost:5173/accept-transfer` | The app's setup screen; the token goes after `#` |
| `transfer_invite_days` | 14 | An invite can be sent again, so a short life is safe |
| `deleted_conversation_purge_days` | 7 | Within the 10-business-day promise, with time for a legal hold |
| `privacy_sweep_minutes` | 15 | Team emails for 8.2's requests, and the deleted-conversation purge |
| `privacy_sweep_batch_size` | 100 | Rows per sweep step |

Also assumed: the transfer's age check uses the client's state (managed profiles have none) and the member's own state at acceptance; the 10 business days count from the request, even while waiting for transfers. `.env.example` wasn't changed (not this task's file): the defaults are local-only values.

## New open questions for the BA

1. **Export while marked for deletion:** 11.4 says the client "can no longer use the app", but the data still exists. Built: export still works until the purge.
2. **Transfer to an email that already has an account:** merge the profile into it, or refuse? Built: refused at acceptance, after the client was told the invite was sent; they can cancel the transfer.
3. **The transfer deadline:** do the 10 business days run from the request, or from when the last invite is accepted? How long may a request wait for transfers? Built: from the request, with no limit.
4. **The new account's trial:** does a member who takes over their profile get a free trial, or the plan they were on? Built: a new 14-day trial.
5. **Subscription on deletion:** should the subscription stop when deletion is requested, or when it's completed? Built: neither yet (PHASE 8 hook `purge.end_subscription`, see below).
6. **Revoking and trusted devices:** built to keep them, so signing in again after revoking skips the code on a known device. Should revoking clear them like an email change?
7. **Deleted conversations under review:** a client can delete a conversation with an unreviewed escalation; after 7 days the text the reviewer needs is gone (questions 27 and 45). Wait for the review?
8. **Legal hold email:** is telling the client "we're required to keep some information" acceptable for every hold, or must some holds stay confidential?
9. **Backups:** "deleted including from backups" depends on backup retention: the managed database's point-in-time backups must keep no more than the 10 business days, or the purge needs a backup-side process.
10. **Advocate only (question 41):** kept the client's date of birth and state on the account; can they create their own profile again later? Built: nothing stops a new self intake.

## For the migration (autogenerate misses these)

On the **existing** `deletion_requests` table:

- **Replace** `ck_deletion_requests_kind` with `kind IN ('family_member', 'account', 'teen')`, and `ck_deletion_requests_status` with `status IN ('waiting_for_transfer', 'pending', 'in_progress', 'on_legal_hold', 'completed', 'declined')`.
- **Add** these check constraints:
  - `ck_deletion_requests_option_kind`: `(kind = 'account') = (option IS NOT NULL)`;
  - `ck_deletion_requests_option`: `option IN ('everything', 'advocate_only', 'transfer')`;
  - `ck_deletion_requests_source`: `source IN ('in_app', 'by_email')`;
  - `ck_deletion_requests_profile`: `(profile_id IS NOT NULL) = (kind = 'family_member' OR (kind = 'account' AND option = 'advocate_only'))`;
  - `ck_deletion_requests_completed_at`: `(status = 'completed') = (completed_at IS NOT NULL)`;
  - `ck_deletion_requests_purged`: `purged_at IS NULL OR status = 'completed'`.
- **Data first**, so the checks hold on existing rows: completed rows need a `completed_at`. Dev data only has `pending` 8.2 rows; optionally set `team_notified_at = requested_at` on them so the first sweep doesn't email the team about old dev rows.
- **Indexes:** drop `uq_deletion_requests_one_pending_per_profile`, and create `uq_deletion_requests_one_open_per_profile` and `uq_deletion_requests_one_open_account`. The new names let autogenerate see them; check each keeps its `postgresql_where`.
- **New columns** (autogenerate finds them): `option`, `source` (`server_default 'in_app'`), `team_notified_at`, `legal_hold_at`, `created_by_id`, `completed_by_id`, `purged_at`, `notify_email`.

On the **existing** `support_requests` table:

- **Replace** `ck_support_requests_kind` with `kind IN ('talk_to_support', 'consultation', 'knowledge_gap', 'email_change')`.
- **Add** check constraints `ck_support_requests_requested_email` (`(kind = 'email_change') = (requested_email IS NOT NULL)`) and `ck_support_requests_email_change_source` (`kind <> 'email_change' OR source = 'form'`).
- **Autogenerate finds** the `requested_email` column and the partial unique index `uq_support_requests_one_open_email_change` (check its `postgresql_where`).

New tables `consent_revocations` and `profile_transfers`: autogenerate creates them with their checks and partial unique indexes (check the `postgresql_where`s and `ON DELETE CASCADE` / `SET NULL`). No seed rows or triggers.

## For other packages

- **Conversations:**
  - `conversations.jobs.retry_safety_check` should skip messages whose account has `accounts.service.consent_withdrawn(...)`, so the Oracle doesn't get them after revoking (the gate already blocks every endpoint);
  - `profiles.service.check_can_use` writes `f"{profile.first_name}’s data is being deleted..."`, which reads "None’s data..." for the client's own profile once advocate only is requested: it needs a self-profile wording.
- **Phase 3b:** fill in `app/privacy/teens.py`, and use `privacy.service.request_teen_deletion` (already wired: `POST /me/deletion-request` from a teen account). `support.is_teen_account` decides who's a teen until then.
- **Phase 8:** `purge.end_subscription(db, account)` must end the provider's subscription at once.
- **Phase A:** endpoints over the team functions and `accounts.service.change_email`; the deletion list (filters, deadlines highlighted within 2 business days), notes, by-email Teen Deletion creation (`source='by_email'`, `created_by_id`, the deadline from the email's date), auditing every view.
- **Phases 6 and 7:** done during integration. Their tables cascade from the profile, so `purge_profile` removes them.

## Added during integration

- **The client's own profile after an "advocate only" request:** `check_can_use` says "Your data is being deleted, so your profile can’t be used." (not in the stories). A family member's profile keeps 8.2's "[Name]’s data is being deleted, so their profile can’t be used."
