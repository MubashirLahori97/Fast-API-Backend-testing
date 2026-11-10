# Phase 3b Teen accounts: decisions

Phase 3b in `docs/PLAN.md`, built 2026-11-06 against the 5 Nov Client stories "Teen Sign Up (Parent Invite)" (1.5), "Teen Reaches the Age of Majority" (1.6), "Onboarding (Teen)" (2.3) and "Onboarding (Teen Reaching the Age of Majority)" (2.4), with the teen parts of 1.2, 2.2, 3.1, 3.2, 4.2, 8.1, 8.2, 11.3, 11.4, 12.1 and 12.2, and PLAN questions 34 to 40 and 48. Code only: no tests and no migration yet (see the end).

## What was built

| Piece | Where |
| --- | --- |
| `TeenLink` (the parent's side), `TeenAccount` (the teen's own extra details), `TeenParentNotice` (3.2's "parent told") | `app/teens/models.py` |
| `users.account_type` (`adult` or `teen`) | `app/auth/models.py` |
| The access gate | `app/teens/access.py` |
| Invites, teen sign-up, linking an existing teen account, Manage Family actions, Create My Account, the age check, the hooks, helpers for the admin panel | `app/teens/service.py` |
| Endpoints | `app/teens/router.py` |
| The daily age check job | `app/teens/jobs.py` |
| The hooks other phases left | `app/privacy/teens.py`, `app/billing/family.py`, `app/billing/entitlements.py`, `app/conversations/safety.py`, `app/support/service.py` (`is_teen_account`), `app/notifications/service.py` (`_client_conditions`) |
| The policy gate's age-of-majority refusal, `next_step`'s `adult_sign_up`, `/me`'s `account_type`, teens' empty `pending_policies`, `consent_withdrawn` for teens | `app/accounts/` |
| `own_account` accepted, the `teen_invite` step, the teen cards on Manage Family | `app/profiles/` |
| `ProfileContext.teen_own_account` | `app/oracle/contract.py` |
| The parent's emergency notice kind `teen_may_need_urgent_help` | `app/notifications/kinds.py` |

### Endpoints (all under `/api/v1`)

| Method and path | Session | What it does |
| --- | --- | --- |
| `POST /profiles/{profile_id}/teen-invite` | policy gate | 1.5: from the family draft whose Teen Profile Choice is `own_account`; `{disclaimer_accepted, email}`. 201 with the card and "Invitation sent..." |
| `POST /teen-links/{link_id}/resend-invite` | policy gate | 8.2's Resend invite (pending only) |
| `POST /teen-links/{link_id}/turn-off` | policy gate | 8.2's toggle off |
| `POST /teen-links/{link_id}/turn-on` | policy gate | 8.2's toggle on (needs a place) |
| `POST /teen-links/{link_id}/remove` | policy gate | 8.2's Remove (no data deleted) |
| `POST /teen-links/{link_id}/health-consent` | policy gate | 12.2: confirm the updated Health Consent for the teen, `{policy_version_id}` |
| `POST /teen-invites/check` | none | `{token}`: the setup screen (email locked, first name, `account_exists`) |
| `POST /teen-invites/accept` | none | 1.5's Teen Account Setup; 201 with a signed-in session, `profile_id` and the welcome |
| `POST /teen-invites/link` | signed in | 1.5's "Teen already has an account": an unlinked teen account joins the invite's family |
| `GET /me/adult-account` | signed in | 1.6's Create My Account, prefilled |
| `POST /me/adult-account` | signed in | 1.6 and 2.4: the teen account becomes an adult account in place, trial started |

Changed: `GET /profiles/family` has `invited_teens` (cards) and counts them in `family_members_used`; `GET /me` has `account_type`; `GET /me/next-step` can answer `adult_sign_up`; the intake's `next_question` can be `teen_invite`; `PATCH /profiles/{id}/intake` accepts `teen_profile_choice: own_account`; `GET /profiles/options` marks `own_account` available.

## Design choices

### A separate account

- **Marked with `users.account_type = 'teen'`**, as `docs/PLAN.md` says. Everything that asks "is this a teen with their own account?" reads it: `support.service.is_teen_account` (used by privacy, conversations' widgets, the admin side), `billing.service._check_client`, `entitlements`, the notifications sweeps, `accounts.pending_policies`. It stays `teen` after the 18th birthday until Create My Account, so an aged-out teen still gets the teen rules (no billing, no family) until they convert.
- **`teen_accounts`** holds what only a teen account has: the city from 1.5's About You, when they joined, and 1.6's bookkeeping (`reminder_scheduled_at`, `aged_out_at`). One row per teen account, deleted at conversion and with the account.
- **The parent's side is `teen_links`**: the first name and relationship the parent typed in the family intake, the invite email, the hashed token and its expiry, joined, turned off, `plan_paused_at` (notice bookkeeping only) and the Health Consent version the parent gave for the teen. Nothing about the teen's health or activity.
- **The teen's profile is on the teen's account** (`is_self`), so `OwnedProfile` keeps the parent out, and the parent's export never includes it.
- **The draft becomes the link.** 2.2's family intake asks relationship, first name and date of birth before the Teen Profile Choice. Choosing `own_account` makes `next_question` answer `teen_invite` (steps 4 to 7 are skipped). The invite endpoint deletes the draft and creates the link: the date of birth the parent typed only decided that the choice applied, and isn't kept. The teen gives their own date of birth.

### Invites (1.5)

- **Token:** `new_token()`, stored as its SHA-256 hash, in the link's `#token=` fragment (`settings.teen_invite_url`), valid `teen_invite_days` (14). A resend replaces it (the old link stops working); joining clears it (single use). Expired, used or made-up links get 1.5's "This invite has expired. Please ask your parent or guardian to send a new one." (400 `invite_expired`), audited as `teen.invite_rejected`, and the per-IP limit counts those.
- **Family plan and places:** the choice save and the invite both check the Family plan with 1.5's "Inviting your teen to their own account is part of the Family plan. Upgrade to invite [Name]." (403 `family_plan_required`). The invite then calls `entitlements.check_can_add_family_member` under the account row lock (draft, then account, as in `complete_intake`), so the add-on flow of 8.1 works unchanged (403 `family_limit_reached`, buy, retry).
- **A place from the invite:** `entitlements.family_members_used` counts every link that isn't turned off, pending or joined. Turned-off and removed links don't count.
- **The email:** `notifications.emails.teen_invite` (1.5's subject, message and Finish Sign Up), sent after the commit.
- **One link per parent and email** (`uq_teen_links_parent_email`): a second invite to the same address is 409 `already_invited`; use Resend.
- **No check at invite time** that the email already has an account: telling the parent would reveal that their teen's address is registered with a health service. The teen finds out when they open the link (question 35).

### The teen's sign-up (1.5) and onboarding (2.3)

- **No emailed code** (the link proves the address), **no policies** (none are recorded for a teen) **and no trial** (`trial_ends_at` is the creation time; `entitlements.trial_ended` is always false for teens).
- **Age and eligibility:** only 13 up to the age of majority continues. Under 13 (`under_13`) and adults (`adult_age`) are refused with messages of our own (question 22). The adult check uses `accounts.adult_in`, the 11.1 per-state hook.
- **Signed in straight away:** `auth.service._sign_in_after_code` (the step after a right code) trusts the device and starts the session, so the prototype's journey goes on to the teen basics without a second sign-in. The welcome ("Welcome to Your Oracle" and 1.5's text) comes back with it, with the teen's `profile_id`.
- **Onboarding is the existing self intake** on that profile: sex at birth, gender, pronouns (`SELF_QUESTIONS`), 2.3's messages, saved as they go. There's no "Who is this profile for?" (the profile already exists, and teens can't add family members). `next_step` resumes it after sign-in, then answers `dashboard`, which the app opens as the teen's own chat (3.1).
- **Teen already has an account:** `check` answers `account_exists`, `accept` answers 409 `email_taken` with 1.1's "An account with this email already exists. Please sign in.", and after signing in a teen account that isn't linked to anyone (removed, or the parent's account deleted) sends the token to `POST /teen-invites/link`. The invite must be for that account's email. Adults can't be linked.

### The access gate (1.5, 1.2, 8.2, 11.4, 12.2)

`app/teens/access.py` works it out on every request from the current rows, so it follows the plan, the toggle and the policies straight away, and nothing is stored to say a teen is paused. Open only while:

1. a link exists (not removed, the parent's account exists) and isn't turned off;
2. the parent's account is active, `entitlements.plan(parent) == "family"`, `accounts.consent_withdrawn(parent)` is false (revoked, or the account waiting for deletion), `accounts.pending_policies(parent)` is empty, and the link's Health Consent version is the current one;
3. the teen is under the age of majority (on Hawaii's date and the account's state, through `accounts.age_of_majority_in`).

The policy gate (`ClientSession`) refuses, after the deletion check: 403 `age_of_majority_reached` with 1.6's message, then 403 `access_paused` with the long paused message. Privacy & Data (`PrivacySession`), `/me`, `/me/next-step`, sign-out and Create My Account still work. `next_step` gives `deletion_requested`, `adult_sign_up`, `access_paused`, then the usual order. Teens never get `policy_update`: `pending_policies` is empty for them (12.2: they aren't shown the policy screen).

While a teen can't use the app:

- **Notifications:** only their `teen_safety_access` notices go (the paused notice, the age reminder); their other reminders are dropped when due (11.4: data not used for notifications while consent is withdrawn). `notifications._may_send` asks `privacy.teens.lost_access`.
- **The Oracle:** `accounts.consent_withdrawn(teen)` is true while the parent's consent is withdrawn or no parent is linked, so the conversations job doesn't send the teen's messages to the Oracle (11.4).

### Consent and the Oracle (3.1, 12.2)

- **The parent's Health Consent counts for the teen.** At the invite, the current Health Consent version is recorded on the link as the parent's consent for the teen (the disclaimer's "I understand & continue"; 1.5: "the parent gave consent"). `conversations.service.has_health_consent` asks `teens.access.parent_consent_covers` for a teen account, so the teen never sees the consent and gets `next: reply`.
- **An updated Health Consent** pauses every invited teen until the parent confirms it for that teen (`POST /teen-links/{id}/health-consent`, 12.2's "Please confirm the updated Health Consent for [Name] to continue." when it's missing or outdated). The card shows `health_consent_needed` and the status `access_paused`. The parent isn't blocked from their own use of the app by it (see the questions).
- **`ProfileContext.teen_own_account`** (new, default false) is true for a teen's own profile: education only, in private. The consult card is dropped through `is_teen_account` (10.1) and product links through the age rule already in `widgets.py`.

### Manage Family (8.1, 8.2)

- Cards in `GET /profiles/family` → `invited_teens`: id (the link's), first name, relationship, `status` (`invite_sent`, `joined`, `turned_off`, `access_paused`), `active`, `can_resend`, `health_consent_needed`, and 8.2's two confirmations with the name filled in. No health information, completion or View & edit. Invited teens never appear in the profile panel (4.2): they're not profiles.
- `access_paused` on a card means the parent's side keeps the teen out (plan ended, or an updated Health Consent waiting); it never reflects the teen's own activity.
- Turn off: the place is freed, the teen is told (`access_paused`). Turn on: needs a place (8.2's limit message from `check_can_turn_on_family_member`). Remove: the link is deleted, the place freed, the teen told; no data is deleted. Every action is audited and runs under the link lock, then the account lock (8.2's order).

### Family plan ending and restarting (11.3)

- `billing.family.pause_invited_teens` → `teens.pause_for_plan_end`: for each joined teen not turned off, sets `plan_paused_at` (so a second sync tells nobody twice), tells the parent (`teen_access_paused`, the parent's pre-5 Nov text, question 48) and the teen (`access_paused`).
- `restore_invited_teens` → `teens.restore_for_plan`: clears `plan_paused_at` and tells the parent (`teen_access_restored`). Teens keep their places while the plan has ended, so they're never left out for lack of room.

### Reaching the age of majority (1.6, 2.4)

- **The daily age check** (`teens.age_check`), started by an `@on_startup` hook and queued again for five past midnight in Hawaii each day:
  - two weeks before (`teen_age_reminder_days`), hands `age_of_majority_reminder` to `notifications.schedule` for 09:00 in Hawaii (`teen_age_reminder_hour_hawaii`), once (`reminder_scheduled_at`); a missed day is caught up within `reminder_catch_up_days`;
  - on the day, records `teen.account_stopped` once (`aged_out_at`). The gate itself works from the date of birth, so the account stops at the first request on the birthday even if the job is late.
- **29 February:** the age of majority is reached on 1 March in years without one, the same as `age_on` counts it.
- **Create My Account converts the account in place** (question 39's proposal): `account_type` becomes `adult`, the first name and state can be changed, the Terms of Service and Privacy Policy are accepted (1.1's checkbox), the 14-day trial starts, the parent's link is deleted (the place is freed) and the parent gets `teen_own_account`, the teen-only details go, and the age reminder is cancelled. The password stays (they're signed in with it); the email and date of birth are the teen account's.
- **The history never moves**, so it's never visible from two accounts and a failed "move" can't lose anything: a database failure answers 503 with 1.6's "We couldn’t move your history just now. We’ll try again shortly." and nothing changes. The answer carries 1.6's "Your history has been moved to your new account." and 2.4's "Your 14-day free trial has started. Choose a plan anytime to unlock everything.", with `next_step` `dashboard` (2.4: no onboarding again) or `intake` if the teen never finished 2.3.
- **After converting**, the adult rules apply: the trial reminders, billing, the adult Health Consent at the next message for their own profile (3.1), and 6.1's About you edits (gender and pronouns editable, date of birth and sex at birth not).

### The parent's notice about a teen's emergency or crisis (3.2)

- `safety.record_escalation` now stores `profile_type = 'teen'` for a teen account's profile, and `tell_parent_about_teen` calls `teens.tell_parent` in the same transaction: `teen_may_need_urgent_help` (emergency, 3.2's text) or `teen_may_need_support` (crisis), with `[Name]` from the link's first name, and the name-free "You have an important update from the Oracle. Please open Your Oracle." for push and email. No conversation content, level or reason anywhere.
- When it was sent, `teen_parent_notices` records the time (`parent_told_at` for Super Admin 4.1). No notice when the teen has no link, or the parent's notifications are stopped.

### Privacy & Data and the purge (11.4)

- `privacy/teens.py`'s hooks are filled: `access_paused`, `age_of_majority_reached`, `lost_access`, `parent_consent_withdrawn`, `invited_teen_names` (joined teens' first names, as the parent typed them), `pause_for_revoked_consent` (each joined teen is told), `restore_after_consent` (nothing to do: the gate sees it), `parent_account_deleted` (teens told, links deleted), `remove_from_family` (the teen's own deletion: the link goes, the parent isn't told).

## Stored codes

- `users.account_type`: `adult`, `teen`.
- Card status (computed, not stored): `invite_sent`, `joined`, `turned_off`, `access_paused`.
- `escalations.profile_type` adds `teen`.
- `next_step` adds `adult_sign_up`. Intake `next_question` adds `teen_invite`.
- Notification kind `teen_may_need_urgent_help` (category `teen_safety_access`, screen `manage_family`).
- Job `teens.age_check`.
- Audit actions (ids only, never names or emails): `teen.invited`, `teen.invite_resent`, `teen.invite_rejected`, `teen.joined` (details `existing_account` when linked after sign-in), `teen.turned_off`, `teen.turned_on`, `teen.removed`, `teen.health_consent_confirmed`, `teen.access_paused` (`reason`: `family_plan`, `consent`, `parent_account_deleted`), `teen.access_restored`, `teen.parent_told`, `teen.age_reminder_scheduled`, `teen.account_stopped`, `teen.left_family`, `teen.adult_account_created` (`history: kept_in_place`), `teen.removed_from_family`; plus `auth.signed_up` (`source: teen_invite`), `auth.email_verified`, `profile.created`.
- Error codes: `family_plan_required`, `family_limit_reached`, `teen_account`, `not_family_draft`, `teen_choice_required`, `already_invited`, `teen_link_not_found`, `already_joined`, `resend_too_soon`, `health_consent_required`, `health_consent_outdated`, `invite_expired`, `under_13`, `adult_age`, `email_taken`, `not_teen_account`, `already_linked`, `age_of_majority_reached`, `access_paused`, `not_aged_out`, `not_of_age`, `deletion_requested`, `save_failed`.

## Messages from the stories

1.5's disclaimer, email, Invitation sent, invite expired, password, passwords don't match, "Please complete this field.", paused, parent told (pre-5 Nov, question 48), reminder and age reached; 1.6's history moved, history move failed and parent notified; 2.3's through the self intake; 2.4's free trial started; 2.2's "Please choose how you’d like to set up [Name]’s profile."; 3.2's two parent notices; 8.2's confirmations and "We’ve sent [Name] a new invite."; 12.2's Health Consent for [Name] and "Thanks, you’re all set."; 1.1's first name, date of birth, state, Terms checkbox and "An account with this email already exists. Please sign in.".

## Messages not in the stories

| Situation | Message | Code |
| --- | --- | --- |
| A teen account tries to add or invite anyone | "Adding family members isn’t available on a teen account." | `teen_account` |
| Invite sent for a profile that isn't a family draft | "Please start by adding a family member, then choose Teen with their own account." | `not_family_draft` |
| Invite to an address already invited by this parent | "You’ve already invited this email address. You can send the invite again from Manage Family." | `already_invited` |
| Invite to the parent's own address | 1.5's "Please enter a valid email address for your teen." | `validation_error` |
| `complete` on a draft whose choice is `own_account` | the same 1.5 text (field `teen_invite`) | `intake_incomplete` |
| Unknown or another parent's link | "We couldn’t find that family member." | `teen_link_not_found` |
| Resend after the teen joined | "[Name] has already joined, so there’s no invite to send." | `already_joined` |
| Resend within a minute | "Please wait a minute before sending the invite again." (11.4's transfer text) | `resend_too_soon` |
| Turned off / on / removed | "[Name]’s access is turned off.", "[Name]’s access is turned on.", "[Name] has been removed from your family." | |
| Setup: under 13 | "Your Oracle accounts are for teens aged 13 and over. Please ask your parent or guardian to set up your profile for you." | `under_13` |
| Setup: already an adult | "You’ve reached adult age, so you can create your own Your Oracle account. Please sign up instead." | `adult_age` |
| Setup: a country other than the US | "Your Oracle is for U.S. users only." | `validation_error` |
| Link: the signed-in account isn't a teen's | "This invite can only be used with a teen account." | `not_teen_account` |
| Link: already linked to a family | "Your account is already linked to a Family plan." | `already_linked` |
| Linked | "You’re linked to your parent’s or guardian’s Family plan again." | |
| Create My Account for an account that isn't an aged-out teen's | "This is only for teen accounts that have reached adult age." | `not_aged_out` |
| Create My Account with a state whose age isn't reached | "You haven’t reached adult age in this state yet." | `not_of_age` |
| The parent's emergency notice by push and email | "You have an important update from the Oracle. Please open Your Oracle." (Phase 9's) | |

## Assumed values

| Setting | Value | Why |
| --- | --- | --- |
| `teen_invite_url` | `http://localhost:5173/teen-invite` | The app's setup screen; the token goes after `#` |
| `teen_invite_days` | 14 | As the transfer invite; it can be resent |
| `teen_age_reminder_days` | 14 | 1.6's "two weeks" |
| `teen_age_reminder_hour_hawaii` | 9 | Daytime everywhere in the US |

Also assumed: the parent's Health Consent for the teen is given by the invite's disclaimer (question 38); the resend throttle reuses `code_resend_seconds` (60); the aged-out teen keeps the parent's place until Create My Account (1.6 frees it "when the new adult account is created"); city is stored but unused. `.env.example` wasn't changed (not this task's file); the defaults are local-only values.

## New open questions for the BA

1. **The parent's Health Consent for the teen (question 38):** is the disclaimer's "I understand & continue" enough, or must the parent see and accept the Health Consent itself when inviting? And after an update: must the parent confirm it for each teen before continuing to the app (12.2's "before continuing"), or is pausing the teen until they do enough? Built: the second, with the confirmation on Manage Family.
2. **Aged-out teens who never create an account (question 39):** they hold the parent's place until then (1.6 frees it at account creation). Should the place be freed on the birthday instead? The parent can remove them meanwhile.
3. **Invites to an email that already has an account:** an adult's can't be linked; another family's teen can't be linked while they're linked there. The invite then waits as "Invite sent" and holds a place until the parent removes it. Should the parent be told, given that it reveals the address is registered?
4. **City (1.5's About You):** what is it for? Time zones (question 8)? It's stored on the teen account and not used.
5. **The welcome after the teen's onboarding:** 2.3 goes "straight into their own Oracle chat"; the self intake's completion line (2.1's "Thank you, [Name]. I’m so glad you’re here...") is still returned. Should teens get no line, or another?
6. **A paused teen's onboarding (question 37):** built as the 5 Nov stories read: only Privacy & Data, so a paused teen can't finish onboarding until access returns.
7. **Over-full places after a plan restarts:** teens keep their places through a plan end. If the restarted plan has fewer places than linked teens (say add-ons were dropped), nothing is turned off automatically. Should some teens be paused?
8. **First onboarding ending with a teen invite:** the parent then has no profile yet, so the next sign-in returns to "Who is this profile for?". Intended?

## For the migration (autogenerate misses these)

- **`users.ck_users_account_type`** on the existing `users` table: `account_type IN ('adult', 'teen')`. Autogenerate adds the column (`server_default 'adult'`, so existing accounts become adults) but not the check.
- **`escalations.ck_escalations_profile_type`**: drop and recreate as `profile_type IN ('self', 'family_member', 'teen')`. Downgrade: delete or map `teen` rows first.
- **New tables** `teen_links`, `teen_accounts`, `teen_parent_notices`: autogenerate creates them with their checks, unique constraints and foreign keys. Check that `teen_links.parent_account_id`, `teen_links.teen_account_id` and `teen_accounts.account_id` keep `ON DELETE CASCADE`, and `teen_links.health_consent_version_id` has none.
- No seed rows, data changes or triggers.

## For other packages

- **Admin (Phase A):** `app/admin/common.py`'s `is_teen()` should become `User.account_type == "teen"` (it still uses the date of birth, which misses aged-out teens and would count an adult whose state changed). `app.teens.service` has `admin_invited_teens(db, parent)` (fits `InvitedTeenOut`), `admin_teen_link(db, teen)` (fits `TeenLinkOut`), `parent_told_at(db, escalation_id)` (4.1's `parent_told_at`) and `dashboard_counts(db)` (2.1's joined, invite sent, access paused). A teen's own audit events have the teen as actor, for 10.1's "Teen" role label.
- **Conversations:** two small edits were needed outside this phase's files: `has_health_consent` asks the teen's link for a teen account, and `profile_context` sets `teen_own_account`. `escalations.profile_type` gains `teen` (the check in `conversations/models.py`).
- **Frontend:** read `account_type` from `/me`; `adult_sign_up` opens Create My Account; the teen setup posts the `#token` in the body; keep `device_token` from the teen sign-up; Manage Family shows `invited_teens`; `next_question: teen_invite` shows the disclaimer and the email field.
