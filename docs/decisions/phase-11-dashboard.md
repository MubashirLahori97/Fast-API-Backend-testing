# Phase 11 Home Dashboard (4.1): decisions

Story "4.1 - View Home Dashboard" (epic Home Dashboard), with the parts of "Switch Profiles - Global Profile Toggle" (4.2), "Start Free Trial & Activate Subscription" (9.1) and "Teen Sign Up (Parent Invite)" (1.5) it refers to. Built 2026-11-06 on top of every earlier phase. Code only: no tests and no migration (none is needed).

## What was built

| Piece | Where |
| --- | --- |
| `GET /profiles/{profile_id}/dashboard?time_zone=` | `app/dashboard/router.py` |
| Building the dashboard from the other phases' functions | `app/dashboard/service.py` |
| `HomeDashboardOut` and one schema per widget (a list discriminated by `code`) | `app/dashboard/schemas.py` |
| Mounted on `/api/v1` | `app/main.py` |
| Settings `home_dashboard_*` | `app/core/config.py` |

No models, no jobs, no audit events: the dashboard only reads.

## Design choices

- **One endpoint per profile.** It returns the top bar, the trial banner or the upgrade prompt, and all nine widgets in the story's order, each with `shown`, `locked`, `title` and `locked_message`. Hidden widgets are still listed (with no data), so the order and the codes never change. The schema is named `HomeDashboardOut` because the admin panel already has a `DashboardOut`.
- **Access:** `ClientSession` (the policy gate, which also shuts out paused teens) and `UsableProfile`. A turned-off member, one whose deletion was requested, or an unfinished intake can't be the active profile, so the dashboard answers 409 (their existing codes) and the app switches to the default profile (4.2: "Active family member removed"). Another account's profile, a teen's own included, gets `OwnedProfile`'s 404. Opening the dashboard counts as activity for the web's idle timeout, like any screen the client opens.
- **Read-only.** It calls only read functions: no commit, no job, no notification, nothing marked read, no message. Only `ClientSession` touches the session's last activity, as on every endpoint.
- **Reuse, not copies.** Each widget comes from its phase's own function:
  - conversation: `conversations.service.list_conversations` (newest first, deleted ones left out, `safety_hold` from 3.2);
  - Wellness Plan: `wellness.service.get_card`; plan check-ins from `plan_row` and `active_items` with the card's own `check_in_due` rule;
  - My Visit Notes and What's next: `visits.listing.visit_notes` (one call, used by both);
  - health profile: `health.service.completion`, `last_updated_at`, `list_facts`; the reminder texts from `notifications.kinds.KINDS`; the month arithmetic from `health.reminders.add_months`;
  - top bar: `notifications.service.unread_count`;
  - My Family: `profiles.service.list_profiles`, `teens.service.cards`, `entitlements.family_members_used` and `family_members_included`;
  - plan: `entitlements.feature_access`, `check_feature`, `check_can_talk` and `trial_days_left`, never the plan column.
  - The only query of its own is the newest `visit_logs.created_at` for the profile (on `ix_visit_logs_profile_created`), for "after a logged visit".
- **Locks** are `feature_access`, and each locked widget's `locked_message` is the refusal `check_feature` gives: 9.1's "This is part of your plan. Choose a plan to unlock it." (which is 4.1's), the Family plan's prompt for My Family, and the trial-ended or subscription-ended message for the conversation. Widget to feature: conversation → `conversations`; Wellness Plan → `wellness_plan`; Complete and Update your health profile, My Health → `my_health`; What's next, My Visit Notes → `visit_notes`; My Family → `family_members`; Consult → never (10.1 doesn't gate it).
- **A locked widget carries no records:** no plan, notes, steps or facts, and the locked feature's own function isn't called (it would refuse). It keeps what draws the card: the completion percentage and the update reminder's text. The conversation is the exception: once the trial or subscription has ended it's locked, but the last conversation is still given, because past conversations stay readable (question 11).
- **What's shown:**
  - **Conversation:** always. `mode` `continue` with the last conversation's id, topic, last message time and `safety_hold`, or `ask` with "Ask me anything".
  - **Wellness Plan:** once the profile has a plan (the card isn't null). While locked (the trial, an ended subscription) it's shown greyed out, as 7.1 says, without the plan.
  - **Complete your health profile:** while the completion is under 100.
  - **Update your health profile:** after a visit logged since the health profile last changed (12.1's after-visit text), or else once 3, 6 or 12 months (`health_profile_review_months`) have passed since the last change, with the largest that has passed as [time]. It stays until the health profile changes again.
  - **What's next:** when it has a step; greyed out with no steps while My Visit Notes is locked. Steps, at most `home_dashboard_next_steps` (2): the soonest upcoming appointment with notes (5.1's "upcoming": today or later on Hawaii's date, not logged), the latest past appointment not logged yet (within `home_dashboard_log_visit_days`), and a Wellness Plan item due for a check-in. One of each kind first, in that order; places left go to more of the same kinds.
  - **My Visit Notes, My Health:** always; counts of notes and upcoming appointments, the completion and the pending facts.
  - **My Family:** only on the client's own profile and not on a teen's account. On the trial or the Individual plan it's shown locked with the Family plan's prompt. On the Family plan: finished family members as in the profile panel (turned-off ones aren't listed, members being deleted are, with that status), invited teens with the parent's name for them, relationship and status (`invite_sent`, `joined`, `turned_off`, `access_paused`), the places used and included, and `can_add` (when false, Add family member offers the add-on, 4.2).
  - **Consult with support team:** always, except on a teen's own account (10.1 refuses teens' consultations).
- **Top bar:** the greeting, the unread count, and the active profile's first name and initial. The client's own profile (a teen's too) gets "Good morning / afternoon / evening, [First Name]" by the hour where the app is: morning from 05:00, afternoon from 12:00, evening from 18:00 and through the night. A family member gets "Here’s [Name]’s space".
- **Time zone:** the backend doesn't know clients' time zones (question 8), so the app sends the device's IANA name in `time_zone` (letters, digits, `_ + - /`, up to 64 characters; anything else is a 422). An unknown name falls back to `home_dashboard_time_zone`. A time zone isn't health data, and is wider than a state, so it's fine in the URL.
- **Free trial:** `trial_banner` with the days left (`trial_days_left`) and "[X] days left in your free trial.". Once the trial or a subscription has ended: `upgrade_prompt` with `trial_ended` or `subscription_ended` (the codes the message box uses) and every widget locked.
- **Teens with their own account** get the same endpoint: `teen_account` true, no trial banner or upgrade prompt (`entitlements` gives teens no trial), My Family and Consult hidden, and nothing else locked while the parent's Family plan is active (the gate refuses the whole endpoint otherwise). `education_only` is true.
- **`education_only`** is true when the active profile is below the age of majority (a teen's own account, or a managed teen or child): the app shows no product promotion. The dashboard's own data has none anyway: the plan card has no products.
- **Family member active:** every widget reads that profile, and titles use the name ("Continue Azka’s conversation"). Steps about a family member use their pronouns ("Her notes are ready.").
- **Errors:** any database failure, including a widget's own "couldn’t load" (the plan card, My Visit Notes), becomes 503 `load_failed` with 4.1's "We couldn’t load your dashboard. Please try again.". No database text is returned or logged.

## Codes in the response (nothing is stored)

| Field | Codes |
| --- | --- |
| `widgets[].code` | `conversation`, `wellness_plan`, `complete_health_profile`, `update_health_profile`, `whats_next`, `visit_notes`, `my_health`, `my_family`, `consult_support` |
| conversation `mode` | `continue`, `ask` |
| update reminder `reason` | `months`, `visit_logged` |
| What's next `kind` | `appointment` (opens `provider_note_id`), `log_visit` (Log visit on `provider_note_id`), `plan_check_in` (`wellness_item_id`) |
| `upgrade_prompt.code` | `trial_ended`, `subscription_ended` |
| invited teen `status` | the teens package's `invite_sent`, `joined`, `turned_off`, `access_paused` |
| Error | 503 `load_failed`; the dependencies' 401/403/404/409; 422 for a malformed `time_zone` |

## Messages from the stories

- Greetings: "Good morning, [First Name]", "Good afternoon, [First Name]", "Good evening, [First Name]"; "Here’s [Name]’s space".
- "[X] days left in your free trial."
- "This is part of your plan. Choose a plan to unlock it."; "Adding family members is part of the Family plan. Upgrade to add someone."
- "It’s been [time] since we last updated your profile. Has anything changed?" (4.1's validation text, not its longer example).
- "Your Cardiology appointment is on 14 Nov. Your notes are ready."; "How did your visit go? Log it here."; "Ask me anything".
- "We couldn’t load your dashboard. Please try again."
- The trial-ended and subscription-ended messages are billing's.

## Messages not in the stories

| Message | Situation |
| --- | --- |
| "1 day left in your free trial." | The trial's last day (4.1's text with "1 days") |
| "[Name]’s [Specialty] appointment is on [14 Nov]. [His / Her / Their] notes are ready." | Upcoming appointment, family member |
| "How did [Name]’s visit go? Log it here." | Visit to log, family member |
| "Let’s check in on “[item]”. How is it going?" | A Wellness Plan item due for a check-in (4.1's example names "the sleep protocol", but items are free text) |
| "It’s been [time] since we last updated [Name]’s profile. Has anything changed?" | 12.1's family text, for a family member |
| "You’ve logged a visit. Has anything changed in your health profile?" / "You’ve logged a visit for [Name]. Has anything changed in [Name]’s profile?" | 12.1's after-visit notice, for the update reminder after a logged visit |
| "Continue [Name]’s conversation" (4.1's example), "[Name]’s Wellness Plan", "Complete [Name]’s health profile", "Update [Name]’s health profile" | Titles while a family member is active |
| "Wellness Plan", "What’s next", "My Visit Notes", "My Health", "My Family", "Consult with support team", "Ask the Oracle" | Titles (the story's widget names; the section names stay the same for a family member) |

## Assumed values (settings)

| Setting | Value |
| --- | --- |
| `home_dashboard_time_zone` | `America/New_York`, when the app sends no known time zone |
| `home_dashboard_morning_hour` / `_afternoon_hour` / `_evening_hour` | 5 / 12 / 18 |
| `home_dashboard_next_steps` | 2 ("one or two") |
| `home_dashboard_log_visit_days` | 30: older unlogged appointments aren't suggested |

## New open questions for the BA

1. **Wellness Plan during the trial:** 7.1 greys it out, but 4.1 hides the card until a plan exists, and the trial has none. Built: shown greyed out. Hidden instead?
2. **What's next during the trial:** greyed out with no steps. Should it show upcoming appointments from notes made in trial conversations (which the trial lets the client read)?
3. **Tapping a greyed-out widget:** 4.1's general message everywhere, or each feature's own (5.1's "My Visit Notes is part of your plan...", 6.1's, 7.1's "Subscribe to get your personal Wellness Plan.")? Built: 4.1's.
4. **Advocate-only clients** never have their own profile active, so 4.1's "hidden while a family member's profile is active" means they never see My Family. Intended?
5. **Update reminder:** can the client dismiss it, or does it stay until the health profile changes (built)? 4.1's example ("...Let’s make sure I have the latest.") and its validation text differ; built: the validation text.
6. **Turned-off invited teens:** 4.1 lists Invite sent, Joined and Access paused; 8.2 adds Turned off. Built: all four.
7. **Product promotion:** what counts on the dashboard? Built: no product data at all, plus `education_only`. Is Consult with support team (paid, booked outside the app) promotion for a managed teen's profile? Built: shown; hidden only on a teen's own account.
8. **Pending health facts:** not in 4.1. Built: a count on My Health. Should it also be a What's next step?
9. **Question 8 again:** the greeting uses the time zone the app sends. Should the backend keep it (it would also fix reminder times)?

## For the migration

Nothing: no models or tables.

## Left for others

- **Tests** for all of the above, and a run against a migrated database (the dev database has no Phase 4 to 9 tables yet).
- **Performance (2 seconds):** about 15 to 25 queries, plus one per invited teen. `list_conversations` reads every conversation of the profile to take the newest; a `latest_conversation` helper in the conversations package would be cheaper.
- **"Widgets update automatically":** the app reloads the dashboard after a change and on focus. If it polls, a variant on `ClientBackgroundSession` would keep polling from counting as web activity.
