# Deletion flow (BA's 6 Nov 19:22 stories): decisions

Built on 10 Nov 2026 against Client 11.4 Revoke Consent / Delete Account, 8.2 Manage Family Profiles (removing a member and an invited teen), 1.2 Sign In (where the client goes), 12.1 Notifications & Reminders (deletion notices), and Super Admin / Admin 5.2 Manage Data Deletion Requests, 3.1 View Client (statuses), 2.1 Dashboard (Deletion Requests card) and 11.1 / Admin 7.1 Receive Notifications. It replaces parts of `phase-10-account.md`, `phase-3b-teens.md` and `phase-a2-admin-operations.md`; where they disagree, this file wins. Code only: no tests, no migration (see the end).

## What changed

- **One timeline for every request.** Account Deletion (`account`), Family Member Deletion (`family_member`), Invited Teen Removal (`teen_removal`, new) and Teen Deletion (`teen`):
  1. acknowledged straight away (a notice with its email copy, or an email when the notice can't go);
  2. 10-day grace period, status `grace_period`, `grace_ends_at` = request + `deletion_grace_days`: full use, nothing locked, the deletion date shown, the team not notified, Complete deletion refused with 5.2's "This request can be completed after the grace period ends on [date].";
  3. the privacy sweep ends it (`privacy.service.end_grace_periods`): sets `locked_at`, status `pending` (Pending review; a request on legal hold stays on hold), cancels scheduled reminders, locks the family member's profile (`profiles.deletion_requested_at`), queues the team email and sends the admin notice `deletion_request` ("ready for review");
  4. the team completes it within `due_at` = request + `deletion_due_days` (45 calendar days); the purge deletes the data and emails the client and any teen affected.
- **Locked = past the grace period** (`accounts.service.grace_over`: `locked_at` set, or `grace_ends_at` passed, so the lock starts on time even before the sweep runs; a legal hold placed during the grace period doesn't end it early). A by-email Teen Deletion has no grace period: it's created `pending` with `locked_at` set.
- **Account Deletion deletes everyone:** the client's account, every managed member, and the accounts and data of the invited teens who joined (turned off or not). The teens are told at the start (`teen_deletion_notice`), keep full use during the grace period, and are locked with the parent (`accounts.account_deletion(..., via_parent=True)`). At completion each teen gets 11.4's "Your account has been deleted because your parent or guardian deleted their account..." email.
- **Removing an invited teen** (`POST /teen-links/{id}/remove`): the link is deleted at once (place freed, billing's count unchanged), and a teen who joined gets a `teen_removal` request (`account_id` = teen, `requested_by_id` = parent). The teen is told and keeps full use during the grace period although unlinked (`teens.access.in_removal_grace`: the access gate, `parent_consent_covers` and `parent_consent_withdrawn` treat them as covered), then is locked. A pending invite is just deleted, with no request.
- **Removing a managed member:** no longer locked at once. The card shows status `scheduled_for_deletion`, `deletion_scheduled_on` and `deletion_label` "Scheduled for deletion on [date]"; after the grace period it's `deletion_requested` (locked) as before. The member keeps their place until the deletion is done. Members being removed don't count as "someone else active" (8.2's last-member rule).
- **Sign-in routing (1.2):** `next_step` `deletion_requested` became `account_being_deleted` (locked; the app shows "Your account is being deleted, so it’s no longer available."). During the grace period the usual step comes, and `GET /me/next-step` and `GET /me/privacy` carry `deletion_notice` {`deletion_on`, `banner` "Your account is scheduled for deletion on [date].", `message`: 11.4's "Your parent or guardian has asked to delete their account..." or 8.2's "Your parent or guardian has removed you from their family plan..." for teens, else null}.
- **The gates:** `ClientSession` refuses 403 `account_being_deleted` (was 403 `deletion_requested` "already scheduled") only once locked. `PrivacySession` is now a dependency that refuses a locked account the same way (1.2: "can't use the app"); during the grace period Privacy & Data and export work. `consent_withdrawn` and `notifications.consent_revoked` are true only once locked, so notices, reminders and the Oracle carry on during the grace period. Re-consent after revoking is allowed during the grace period, refused once locked.
- **Removed (transfers at the age of majority, 11.4):** the `ProfileTransfer` model and `profile_transfers` table, `POST /profile-transfers/check` and `/accept`, `POST /me/deletion-request/transfers/{id}/resend` and `/cancel-transfer`, the `option` column and its values (`everything`, `advocate_only`, `transfer`), the `waiting_for_transfer` status, the transfer emails, the `transfer_invite_accepted` notice, and the `transfer_invite_url` / `transfer_invite_days` settings. "Stay as advocate only" is deferred, so its option and purge path are gone too; the `advocate_only` flag on `/me/profile` (2.2's clients who only added family members) stays.
- **Admin (5.2, 2.1, 3.1, 11.1):** list rows add `grace_ends_at` and `days_left` (calendar; replaces `business_days_left`), drop `option`; highlighted within `deletion_highlight_days` (5). Details add `what_will_be_deleted.invited_teens` and `grace_period_message`. `start-review` and `complete` refuse during the grace period. The Dashboard card counts requests past their grace period (open, `locked_at` set) and those within 5 days of the deadline. Client statuses `scheduled_for_deletion` and `being_deleted` replace `deletion_requested` (the account's own request only). The deadline reminder goes once, 5 days before the deadline.

## Stored codes

- `deletion_requests.kind`: `family_member`, `account`, `teen_removal`, `teen`. `status`: `grace_period`, `pending`, `in_progress`, `on_legal_hold`, `completed`, `declined`. `source`: `in_app`, `by_email`.
- New columns: `requested_by_id`, `grace_ends_at`, `grace_reminded_at`, `locked_at`. Dropped: `option`.
- Notification kinds (12.1): `deletion_acknowledged`, `member_deletion_acknowledged`, `deletion_reminder` (requests and account, can't be turned off); `teen_deletion_notice`, `teen_deletion_reminder` (teen safety and access, so paused teens get them). New placeholder `[date]` (`data={"date": ...}`). Removed `transfer_invite_accepted`.
- Admin notice `deletion_request` now means "ready for review" (sent at the end of the grace period, never during it).
- Error codes: `account_being_deleted` (403), `grace_period` (409, team), `already_scheduled` (409) kept.
- Audit actions added: `deletion.requested`, `deletion.grace_period_started`, `deletion.acknowledged`, `deletion.grace_period_ended`, `deletion.invited_teen_deleted`. Removed: `account.deletion_requested`, all `account.transfer_*`. Ids and the request type only.

## Messages not in the stories

| Situation | Text |
| --- | --- |
| `POST /me/deletion-request` answer | the banner, "Your account is scheduled for deletion on [date]." |
| Family member acknowledgement, push and email (no name) | "Your request has been received. Your family member’s profile will be deleted after [date]. You can keep using it until then." |
| Adults' grace reminder | 12.1's teen text, "Your account will be deleted tomorrow. Download your information now if you’d like a copy." |
| By-email Teen Deletion acknowledgement email | "We’ve received your request to delete your Your Oracle account and information. We’ll complete it by [date], and email you when it’s done." |
| Deletion complete email, Account Deletion | "Your Your Oracle account has been permanently deleted, as you asked, with your information and the information of everyone on your account." |
| Deletion complete email, Teen Deletion and the removed teen | "Your Your Oracle account and its information have been permanently deleted." |
| Invited Teen Removal complete, to the parent | "The account and information of the teen you removed from your family have been permanently deleted." |
| Team email subject | "Deletion request ready for review: [Type]" |
| Admin notice | "A data deletion request has finished its grace period and is ready for review." / "A data deletion request is due in [X] days." |
| Card label (8.2 gives it without a full stop) | "Scheduled for deletion on [date]" |

Dates are "December 5, 2026" on Hawaii's date (`accounts.service.long_date`), like billing's.

## Assumed values (settings)

| Setting | Value | Why |
| --- | --- | --- |
| `deletion_grace_days` | 10 | 8.2, 11.4, 5.2 |
| `deletion_due_days` | 45 | CCPA/CPRA, calendar days from the request (or the email's date) |
| `deletion_grace_reminder_hours` | 24 | 12.1's "deleted tomorrow" |
| `deletion_highlight_days` | 5 | 5.2 and 11.1 |
| `deletion_highlight_business_days` | 5 | kept only because `app/admin/notifications/service.py` reads it for the default [X] |

Removed: `deletion_business_days`, `transfer_invite_url`, `transfer_invite_days`.

## Open questions for the BA (contradictions recorded; newest text followed)

1. **1.2 grace-period routing:** "No new routing... the Client signs in as normal" versus the first check "Account in its deletion notice period: ... with a message". Built: normal routing plus `deletion_notice` (banner, and the teen messages).
2. **8.2 alternate "Invited teen removed — the teen loses access, and their data is kept"** and "the teen emails the support team" contradict the new removal flow (full use 10 days, then deleted). Built: the new flow.
3. **8.2 Advocate-Only Clients** still describe clients who deleted their own data; 11.4 defers "stay as advocate only". Built: the last-member rule applies to clients without an own profile (2.2).
4. **Cancelling a deletion during the grace period:** no story says the client can. Built: no; the team's existing Decline stays (a declined teen removal doesn't relink the teen).
5. **Revoking consent during the grace period:** built as before (refused while a deletion is open).
6. **A removed teen who joins another family during the grace period** keeps the removal request and is still deleted. Should joining cancel it?
7. **Subscription:** an Account Deletion should stop billing; app/billing is parked, so `purge.end_subscription` is still empty (and nothing stops renewals during the grace period).
8. **Who is "the Client" for an Invited Teen Removal** in the listing and the completion email? Built: the listing shows the teen's account; both the teen and the parent are emailed.
9. **Invited teens locked through the parent's deletion** show their own status in the admin client list (not "Being deleted"). Should they?
10. **Backups:** "including from backups" within 45 days depends on backup retention.

## For the migration (autogenerate misses these)

On the existing `deletion_requests` table:

- **Data first:** map old rows so the new checks hold: `status = 'waiting_for_transfer'` → `pending`; `kind = 'account' AND option = 'advocate_only'` rows → `declined` (or delete; their `profile_id` breaks `ck_deletion_requests_profile`), then clear `profile_id` on them; set `locked_at = requested_at` and `due_at = requested_at + interval '45 days'` on every open row (they were already locked under the old flow).
- **Drop** `ck_deletion_requests_option_kind`, `ck_deletion_requests_option`, then the `option` column (autogenerate drops the column, not the checks first).
- **Replace** `ck_deletion_requests_kind` (`kind IN ('family_member','account','teen_removal','teen')`), `ck_deletion_requests_status` (`status IN ('grace_period','pending','in_progress','on_legal_hold','completed','declined')`) and `ck_deletion_requests_profile` (`(profile_id IS NOT NULL) = (kind = 'family_member')`).
- **Add** `ck_deletion_requests_requested_by` (`(requested_by_id IS NOT NULL) = (kind = 'teen_removal')`) and `ck_deletion_requests_grace` (`status <> 'grace_period' OR grace_ends_at IS NOT NULL`).
- **Recreate** the partial unique indexes `uq_deletion_requests_one_open_per_profile` and `uq_deletion_requests_one_open_account` with `grace_period` in place of `waiting_for_transfer` in their `postgresql_where` (same names, so autogenerate won't see the change).
- New columns (autogenerate finds them): `requested_by_id`, `grace_ends_at`, `grace_reminded_at`, `locked_at`.

**Drop table** `profile_transfers` (autogenerate finds it; downgrade recreates it empty).

## For other packages

- `app/admin/notifications/service.py:121` should read `settings.deletion_highlight_days`; its "1 business day" fix-up no longer matches the new "[X] days" text.
- `app/admin/audit/catalog.py` needs labels for the new audit actions above (and can drop `account.deletion_requested` and the transfer ones).
- `.env.example` still has `TRANSFER_INVITE_URL` (ignored by settings; remove).
- `app/admin/clients/` family member rows still have `deletion_requested` (locked only); a "scheduled" flag could use `profiles.service.open_member_deletion`.
