# Phase 9 Notifications (12.1) and the rest of Policy Updates (12.2): decisions

Built on 5 Nov 2026 in `app/notifications/`, `app/core/push.py` and `app/accounts/service.py` (policy publishing), against Client stories 12.1 Notifications & Reminders and 12.2 Policy Updates. No tests or migration yet (see the end).

## What was built

| Piece | Where |
| --- | --- |
| `GET /me/notifications?before=&limit=`: the notification centre, newest first, a page at a time, with the unread count | `router.py` |
| `GET /me/notifications/unread-count`: the bell | `router.py` |
| `POST /me/notifications/read-all`: mark all as read | `router.py` |
| `POST /me/notifications/{notification_id}/read`: the client tapped one; marks it read and returns where it goes | `router.py` |
| `GET` and `PUT /me/notification-preferences` | `router.py` |
| `POST /me/push-tokens`, `DELETE /me/push-tokens/{token_id}` | `router.py` |
| `notify`, `schedule`, `cancel_scheduled`: the API other phases call | `service.py` |
| One kind per 12.1 notification type, with its text | `kinds.py` |
| Lookups for the records notifications open, and the health details shown from them | `targets.py` |
| Jobs: scheduled reminders, push and email copies, the reminder sweep, policy announcements and emails | `jobs.py` |
| `PushSender` protocol, console sender (refuses production), in-memory sender for tests | `app/core/push.py` |
| `publish_policy_version` and `announce_policy_version` | `app/accounts/service.py` |
| `@on_startup` hooks in the worker (used to start the sweep) | `app/worker.py` |

## Design choices

### Channels

- **In-app** is the `notifications` row: kind, title, body, `outside_text` (what push and email say), `screen` and `target_id` (where tapping it goes), `profile_id`, `read_at` (the read flag), `created_at` (`clock_timestamp()`, so two made in one transaction sort in order).
- **Push and email** are copies, sent by the `notifications.push` and `notifications.email` jobs with the notification's id as the only payload. They never carry a name or a health detail: they say `outside_text`, which is the kind's `outside` text, or 12.1's general message "You have a new update from the Oracle" for every kind that names someone or is about health. The push's data holds only `notification_id`; the app loads the rest once it's open. A push isn't sent if the notice was already read in the app.
- **No SMS** anywhere.
- **Every notice gets an in-app row** when it's sent at all. The preference's push and email choices only add copies.

### What's stored, and where health data goes

- The title and body hold no health data. `[topic]` (a conversation's topic) and `[specialty]` (a provider note's) are left as placeholders in the stored body and filled from the linked record each time the list is shown (`targets.py`). When that record is gone or has no value, the kind's generic text is shown instead (for example "How did your appointment go?").
- First names (`[Name]`) are filled when the notice is made. A managed family member's name comes from their profile. When the profile no longer exists (8.2's "deleted" notice) or the notice is about a teen's own account, the caller passes it as `data={"name": ...}`. These rows only go to the owning account, as PLAN's PHI decision allows. Deleting a profile deletes its notifications (`ON DELETE CASCADE`); "[Name]’s data has been deleted." has no profile, so it stays, as the story needs.
- `notify` refuses any `data` key that isn't one of its placeholders, so `topic` or `specialty` can't be passed in and stored.

### Stored codes

- **Categories** (preference types, in 12.1's order): `guidance_follow_ups`, `appointments`, `wellness_plan`, `health_profile`, `inactivity` (can be turned off); `billing`, `requests_account`, `teen_safety_access` (can't).
- **Kinds** (`notifications.kind`): see the table under "Kinds for the other phases".
- **Screens** (`notifications.screen`): `conversation`, `new_conversation`, `visit_notes`, `log_visit`, `wellness_plan`, `check_in`, `health_profile`, `plans`, `billing`, `manage_family`, `my_profile`, `privacy_data`, `adult_sign_up`. The app maps each to a route.
- **Push platforms:** `ios`, `android`.
- **Job kinds:** `notifications.send` (a scheduled reminder), `notifications.push`, `notifications.email`, `notifications.sweep`, `notifications.announce_policy_version`, `notifications.policy_update_emails` (one batch), `notifications.policy_update_email` (one client).
- **Audit actions:** `policy.published` (actor, kind, version, published_at), `policy.announced` (kind, version, how many sessions ended).

### Preferences

- One row per account and type the client can turn off, only once they change it. With no row, the defaults: on, by push, and by email only if `notification_email_by_default` (off: 12.1 says email is for account, billing and request updates).
- The three locked types are always on, by push and email. `PUT` accepts them only unchanged (enabled, push and email all true), so the app can send the whole screen; anything else gets 422 `cannot_turn_off` with 12.1's "These notifications keep you safe and your account up to date, so they can’t be turned off." Their channels are fixed too, because 12.1 offers the push/email choice only for the five types it lets the client turn off.
- `PUT` changes only the types it's sent. A type turned off keeps its push and email choice for when it's turned back on. Turned on with neither push nor email, it appears in the notification centre only.
- Saved straight away with an upsert, and the same for every device. A database error gives 12.1's "We couldn’t update your preferences just now. Please try again." (503 `save_failed`); success says "Your notification preferences have been updated."
- Preference changes aren't audited: no story asks for it.

### When not to send (`notify`, and again when a scheduled reminder is due)

- Nothing for a deactivated account.
- Nothing while consent is revoked: `consent_revoked()` returns False until Phase 10 builds revoking consent. **Phase 10 must fill it in** (marked `PHASE 10`).
- Nothing about a family member whose intake isn't finished, who's turned off, or whose deletion was requested. 8.2's "reminders pause" is built as "skipped while off": reminders due during that time are dropped, and later ones go again once the member is back on.
- No follow-up or check-in about a profile that has had an emergency or crisis. `after_emergency_or_crisis` asks the conversations package's `safety.check_ins_blocked(profile_id=...)` for the profile, with no time limit; for the inactivity check-in, which has no profile, any of the account's profiles counts. `schedule` doesn't schedule such a kind at all (returns None), and a reminder scheduled before the emergency is dropped when it's due. The kinds this covers (`check_in=True`): guidance follow-up, appointment follow-up, booking follow-up, Wellness Plan check-in, the three health profile reminders, and inactivity. Appointment reminders, lab results reminders, "Wellness Plan updated" and every locked kind still go. Question 28 is still open.
- A scheduled reminder whose profile or linked record is gone isn't sent.
- The preference turned off: nothing, not even in-app.

### The notification centre

- Paged with a cursor: `before` is the last id of the previous page, `next_before` is null on the last page. `limit` defaults to 20, at most 50. Ordered by `(created_at, id)`.
- Each item has the body, the profile's id and first name (the client's own first name for their own profile; null for notices about the account), the screen, the target id, `read` and `created_at`.
- No notifications at all: the page has `message` "You’re all caught up." (12.1).
- **Opening one** (`POST .../{id}/read`) marks it read, then returns it. If its profile can't be used any more, or the linked record is gone, it answers 410 `item_unavailable` "This item is no longer available." (12.1), after marking it read.
- Another account's notification gets the same 404 as an unknown one.
- All these endpoints use `ClientSession` (the policy gate): they can show a family member's name and conversation topics.

### Push tokens

- **Stored readable, not hashed:** the provider needs the token itself to send. It's personal data (it identifies a device), so it's never returned by the API, logged (the console sender prints its last 6 characters), or put in a job payload, and it gets Phase 4's field encryption. `token_hash` (SHA-256) is unique and is what lookups use, so they keep working once `token` is encrypted.
- **Tied to the session that registered it.** Pushes go to a device while its session is active or has only timed out (`session_expired`, `signed_out_inactive`), so a phone whose 30-day mobile session ran out still gets the 30-day inactivity check-in. Anything else that ends a session (sign-out, password reset or change, a policy update, deactivation) stops its pushes until the app signs in and registers again. **The app must send its token after every sign-in.**
- Registering a token that's already stored moves it to this session and account, so a phone another account used before only gets this account's pushes. Each account keeps its newest 10 (`max_push_tokens_per_account`).
- A token the provider refuses (`InvalidPushToken`: app uninstalled, push turned off in the phone's settings) is deleted. Other failures are logged by class name. If every device failed, the job raises and the worker retries; if some got it, the rest aren't retried, so nobody gets a push twice.
- Register and remove use `CurrentSession`, not the policy gate: the app registers straight after sign-in and removes at sign-out, and neither shows health data.

### Reminders this phase sends: the trial and inactivity

- One `notifications.sweep` job runs every `reminder_sweep_seconds` (60). It saves its next run and deletes its own finished rows before doing any work, so a failure doesn't stop the chain and a run a minute doesn't fill the `jobs` table. A transaction-level advisory lock makes sure only one sweep is waiting. The worker starts the first one at startup (`@on_startup`), and starts a new one if the chain ever broke.
- **Trial ending:** `trial_ending_reminder_days` (3) before `users.trial_ends_at`, for accounts with no `subscription_plan`: "Your free trial ends in [X] days..." with X the whole days left, rounded up, and "1 day" for one.
- **Trial ended:** at `trial_ends_at`. Trials that ended while the worker was down are caught up for `reminder_catch_up_days` (7); older ones aren't, so switching this on doesn't email every old trial.
- Each is sent once per trial end date (it checks for an earlier notice of that kind since the date, with a day's slack for clock differences).
- **Inactivity:** 30 days (`inactivity_check_in_days`) after the account's last activity (the latest `sessions.last_seen_at`, or `created_at`), once per quiet spell, with the same 7-day catch-up. It's about the client, not a profile, and opens a new conversation.
- Each sweep handles at most `reminder_sweep_batch_size` (200) accounts per reminder; the rest wait for the next minute.

### Policy updates (12.2)

- `publish_policy_version(db, kind, version, title, url, published_at, *, actor_id=None, request=None)` adds the version and audits `policy.published`, then commits. `kind` is `terms`, `privacy` or `health_consent`; `published_at` must have a time zone. A version that already exists gets 409 `policy_version_exists`.
- When it takes effect (straight away, or at a later `published_at` through `notifications.announce_policy_version`), `announce_policy_version`:
    - ends every signed-in session of every client account (`sessions.revoked_at`, no `revoked_reason`, so the apps get the general "signed out" message and show the update before Sign In). Admin sessions don't end. Teens' sessions end too;
    - audits `policy.announced` with the number of sessions ended;
    - queues the emails: batches of 100 clients (`policy_email_batch_size`), each queuing one email job per client, so a failed send is retried for that client only.
- The email is 12.2's "We’ve updated our [Policy name]. You’ll be asked to review and accept it the next time you open Your Oracle." It goes to every active client who signed up before the version was published, except clients who've already accepted it and (once Phase 10 builds it) clients with revoked consent. Several versions published together send one email each.
- There's no admin endpoint: Phase A calls this, passing the admin as `actor_id`.

## Kinds for the other phases

Call `notify(db, account, kind, profile=..., target_id=..., data=...)` to send now, or `schedule(db, account, kind, run_at, profile=..., target_id=..., data=...)` for later. Both add to the caller's transaction. To move a reminder (an appointment date changes), call `cancel_scheduled(db, account, kind=..., profile=..., target_id=...)` and schedule it again. A scheduled reminder's `data` may only hold `days` and `time` (it goes into the job payload); names come from the profile when it's sent. For a kind that links to a record, add that record type's lookup to `targets.LOOKUPS` (`provider_note` gives `specialty`; `visit_log`); until then its notices always open and show the generic text.

| Kind | Sent by | Text (own profile / family member) | Opens |
| --- | --- | --- | --- |
| `guidance_follow_up` | Phase 5 (3.3), `guidance_follow_up_days` after a summary; target: the conversation | "It’s been two weeks since we talked about [topic]. How are you feeling?" / "...about [topic] for [Name]. How is [Name] feeling?" | conversation |
| `appointment_reminder` | Phase 5 (3.4); target: the provider note | "Your [specialty] appointment is coming up." / "[Name]’s [specialty] appointment is coming up." | visit_notes |
| `appointment_follow_up` | Phase 5 (3.4); target: the provider note | "How did your [specialty] appointment go?" / "How did [Name]’s appointment go?" | log_visit |
| `booking_follow_up` | Phase 5 (3.4), `booking_follow_up_days` after notes without a date | "Have you booked your appointment yet?" / "Have you booked [Name]’s appointment yet?" | visit_notes |
| `lab_results_expected` | Phase 6 (5.2); target: the visit log | "Your lab results should be ready soon. When you have them, you can type the values into a conversation." | new_conversation |
| `wellness_plan_updated` | Phase 7 (7.1) | "Your Wellness Plan has been updated." / "[Name]’s Wellness Plan has been updated." | wellness_plan |
| `wellness_plan_check_in` | Phase 7 (7.1) | "Check in with the Oracle: about 2 minutes." / "Check in with the Oracle about [Name]: about 2 minutes." | check_in |
| `health_profile_review` | Phase 4 (6.1), at `health_profile_review_months`; `data={"time": "3 months"}` | "It’s been [time] since we last updated your profile. Has anything changed?" (4.1) | health_profile |
| `health_profile_review_after_visit` | Phase 6 (5.2) | "You’ve logged a visit. Has anything changed in your health profile?" | health_profile |
| `health_profile_incomplete` | Phase 4 (6.1) | "Complete your health profile, so I can tailor my guidance to you." | health_profile |
| `inactivity_check_in` | this package's sweep | "It’s been a while. How have you been?" | new_conversation |
| `trial_ending`, `trial_ended` | this package's sweep | 9.1's texts | plans |
| `renewal_failed` | Phase 8 (11.3) | 11.3's "We couldn’t renew your subscription..." | billing |
| `family_members_turned_off`, `family_members_turned_on` | Phase 8 (11.3) | see "Messages not in the stories" | manage_family |
| `deletion_complete` | Phase 10 (8.2's purge), `data={"name": ...}`, no profile | "[Name]’s data has been deleted." (8.2) | manage_family |
| `email_changed` | Phase 10 (11.1), `data={"new_email": ...}` | 11.1's "Your email address has been changed to [new email]..." | my_profile |
| `transfer_invite_accepted` | Phase 10 (11.4), `data={"name": ...}` | see below | manage_family |
| `teen_access_paused`, `teen_access_restored` | Phase 3b / 8 (to the parent), `data={"name": teen}` | the parent's pre-5 Nov texts (PLAN question 48) | manage_family |
| `teen_may_need_support` | Phase 3b, from `safety.tell_parent_about_teen` (to the parent), `data={"name": teen}` | 3.2's "[Name] may need some support right now..." | manage_family |
| `teen_own_account` | Phase 3b (1.6, to the parent), `data={"name": teen}` | 12.1's "[Name] now has their own Your Oracle account..." | manage_family |
| `age_of_majority_reminder` | Phase 3b (1.6, to the teen), two weeks before | 1.6's "In two weeks, you’ll reach adult age..." | adult_sign_up |
| `access_paused` | Phase 3b (to the teen) | 12.1's "Your access is paused. Please ask your parent or guardian. You can still download your data or ask for it to be deleted in Privacy & Data." | privacy_data |

- **The teen invite email** (1.5) goes to someone with no account yet, so it isn't a kind: Phase 3b sends `emails.teen_invite(to, link)` with its own token in the link's `#` fragment.
- **The old-address email** for 11.1's email change, and **11.4's account deletion email**, go to addresses no account row holds by then; Phase 10 sends them with the `EmailSender` directly.
- **Import cycle:** `notifications.service` imports the `app.conversations.safety` module (not the function), so Phase 3b can import `app.notifications.service` from `safety.py` for the teen notice.

## Left for other packages

- **Conversations (12.2):** when a new Health Consent version is published, the client must accept it for their own profile before using the app, then confirm it as medical advocate for each family member and invited teen ("Please confirm the updated Health Consent for [Name] to continue."). Today `pending_policies` and the policy gate only cover the Terms and Privacy Policy, and the conversations package asks for the Health Consent per profile only when a reply is needed. That re-confirmation flow belongs to the conversations package (`health_consents`), as does deciding whether clients who never accepted one see the updated one before sign-in (question 38).
- **Phase 3b:**
    - leave teen accounts out of `_client_conditions()` in `service.py`: they have no trial, 12.1 gives them no inactivity check-in, and 12.2 doesn't email them or show them the policy screen;
    - pause invited teens until the parent accepts updated policies (the access gate already lists it);
    - send the teen notices above.
- **Phase 10:** fill in `consent_revoked()`; call `cancel_scheduled(profile=...)` when a profile is purged (the send-time check covers it anyway).
- **Auth (PLAN's Phase 1 note):** the apps will poll `GET /me/notifications/unread-count`, and `current_session` refreshes `last_seen_at` on every request, so a web page left open keeps its session past the 30-minute idle timeout. The auth package needs a way for polling requests not to count as activity (a dependency that checks the session without refreshing it, say). Not changed here: `app/auth` isn't this phase's.

## Messages not in the stories

| Message | Situation |
| --- | --- |
| "We couldn’t find that notification." | 404 for an unknown or another account's notification |
| "We couldn’t find that device." | 404 for an unknown or another account's push token |
| "This push token isn’t valid." | 422: an empty token, or one with spaces or non-ASCII characters |
| "This version of the policy has already been published." | 409 from `publish_policy_version` (admin side) |
| Titles: "Checking in", "Appointment reminder", "How did it go?", "Booking reminder", "Lab results", "Wellness Plan updated", "Check-in", "Health profile", "Free trial", "Payment issue" (11.3's status), "Family plan", "Deletion complete", "Email address changed", "Transfer accepted", "Teen access", "Important update", "Your account", "Your access" | The heading of each notice; also the email subject for kinds with their own outside text |
| Category labels: "Guidance follow-ups", "Appointments", "Wellness Plan", "Health profile", "Inactivity", "Subscription and billing", "Requests and account", "Teen safety and access" | Notification Preferences, from 12.1's wording |
| Family-member texts for guidance follow-up, booking follow-up, lab results, Wellness Plan updated and check-in, and the health profile reminders | 12.1 gives only "How did Azka’s appointment go?" |
| Generic texts: "It’s been two weeks since we last talked. How are you feeling?", "It’s been two weeks since we last talked about [Name]. How is [Name] feeling?", "Your appointment is coming up.", "[Name]’s appointment is coming up.", "How did your appointment go?" | When [topic] or [specialty] can't be shown any more |
| "Your [specialty] appointment is coming up." | 3.4's reminder before an appointment (no text in the stories) |
| "Your lab results should be ready soon. When you have them, you can type the values into a conversation." | 5.2's lab results reminder |
| "You’ve logged a visit. Has anything changed in your health profile?" | 6.1's review reminder after a logged visit |
| "Complete your health profile, so I can tailor my guidance to you." | 12.1's reminder to complete the health profile |
| "Your Family plan has ended, so your family members’ profiles are turned off. Their information is kept, and you can turn them back on by returning to the Family plan." | Family plan ends (from 11.3's downgrade text) |
| "Your Family plan is active again, and your family members’ profiles are turned back on." | Family plan restarts |
| "[Name] has accepted your invite and now looks after their own profile." | 11.4's transfer invite accepted |
| Push and email texts: "A deletion you asked for is complete.", "Your email address has been changed. Please sign in again with your new email address.", "A family member has accepted your transfer invite.", "Your teen’s access is paused because your Family plan has ended. Renew to restore it.", "Your teen’s access has been restored.", "You have an important update from the Oracle. Please open Your Oracle.", "Your teen now has their own Your Oracle account. Their place in your family plan is free again." | The name-free versions of kinds whose in-app text names someone; the important one is for the teen crisis notice |
| Email body ending "Open Your Oracle to see the details." and subject "We’ve updated our [Policy name]" | Notification and policy update emails |
| Push title "Your Oracle" | Every push |

Choices between conflicting story texts:

- The appointment follow-up uses 12.1's "How did your [specialty] appointment go?", not 5.2's "Your [specialty] appointment was on [date]. How did it go?", which also needs the appointment date (health data) in the text.
- The teen's paused notice uses 12.1's long text ending "in Privacy & Data" (PLAN: the long message everywhere; "here" doesn't fit a notification).

## Assumed values (all in `Settings`)

| Setting | Value | Why |
| --- | --- | --- |
| `trial_ending_reminder_days` | 3 | Question 9: the story gives no timing |
| `inactivity_check_in_days` | 30 | 12.1 |
| `guidance_follow_up_days`, `booking_follow_up_days`, `health_profile_review_months` | 14, 7, [3, 6, 12] | 12.1 and 6.1, for the phases that schedule them |
| `notification_email_by_default` | False | 12.1: email is for account, billing and request updates |
| `reminder_sweep_seconds` | 60 | 12.1: within 1 minute of the scheduled time |
| `reminder_catch_up_days` | 7 | How far back the sweep catches up after downtime |
| `reminder_sweep_batch_size` | 200 | Accounts per reminder per sweep run |
| `max_push_tokens_per_account` | 10 | Devices per account |
| `policy_email_batch_size` | 100 | Clients per batch of policy emails |
| `notifications_page_size`, `notifications_max_page_size` | 20, 50 | The notification centre |

## New questions for the BA

1. **Locked types' channels:** can a client choose push only or email only for billing, requests and account, and teen notices, or are those fixed at both (built fixed)?
2. **Revoked consent and policy emails:** 12.1 says every notification stops while consent is revoked, but a privacy policy change may be a notice we must send anyway. Built: no email while consent is revoked.
3. **Missed reminders while a family member is turned off:** dropped (built), or sent when they're turned back on?
4. **The teen crisis notice by push and email** (question 28): built with a name-free "You have an important update from the Oracle. Please open Your Oracle." Is that enough, given 3.2 wants the parent to act straight away?
5. **"No check-ins after an emergency or crisis"** (question 28): built as no follow-up or check-in about that profile ever again, the strictest reading. Should they resume once the client has come back and talked, or after some time?
6. **Push after a policy update:** every session ends, so devices get no pushes until the client signs in again. Fine?
7. **Titles and texts** in the table above need the BA's wording.

## Migration notes

Autogenerate should produce everything here: three new tables (`notifications`, `notification_preferences`, `push_tokens`) with their check constraints, unique constraints and foreign keys. Check in the generated file that:

- the partial index `ix_notifications_account_unread` keeps `postgresql_where=read_at IS NULL`;
- `notifications.created_at` keeps `server_default=clock_timestamp()`;
- the foreign keys keep `ON DELETE CASCADE` (`notifications.account_id`, `notifications.profile_id`, `notification_preferences.account_id`, `push_tokens.account_id`, `push_tokens.session_id`).

Nothing changes on existing tables, and there are no seed rows: the worker queues the first sweep when it starts.
