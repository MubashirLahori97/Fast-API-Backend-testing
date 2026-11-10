# R3 Conversations and 3.2 Escalation / Emergency Detection: decisions

Phase R item R3 and story 3.2 in `docs/PLAN.md`, built 2026-11-05 against the 4 Nov stories "Start or Continue a Conversation" (3.1) and "Escalation / Emergency Detection" (3.2), plus the "Message feedback and deleting conversations" item's note to refuse delete during a hold. No tests or migration yet (see the end).

## What was built

| Piece | Where |
| --- | --- |
| `age_group(date_of_birth)` and the `AgeGroup` codes | `app/core/ages.py` |
| Contract: `age_group` in `ProfileContext` and `SafetyContext`, the 4 Nov profile codes, `SafetyCheck.poison_control`, the widget kinds the backend enforces | `app/oracle/contract.py` |
| `FakeOracle`: test phrases for each safety level | `app/oracle/fake.py` |
| The widget rules (privacy notice, product links, disclosure box, consult card) | `app/conversations/widgets.py` |
| The safety path: advice texts, escalations, holds, the check-ins helper, the teen hook, the admin service functions | `app/conversations/safety.py` |
| `Escalation` model; `messages.safety_reason` and `messages.outside_us` | `app/conversations/models.py` |
| `POST /conversations/{id}/safety-choice`; hold state in the send answer, `GET /conversations/{id}` and the list; `DELETE` refused during a hold | `router.py`, `service.py`, `schemas.py` |
| "Hormone imbalance" starter | `app/conversations/starters.py` |

## R3 design choices

- **Age groups:** `under_13`, `teen` (13 up to `settings.age_of_majority`, so 13 to 17 today), `adult` (to 59), `60_plus`. Counted on Hawaii's date like `is_adult`, so `teen` ends exactly where `is_adult` starts. They replace `age_band` (`13_17`, `18_59`), and the contract's fields are renamed `age_group`. The `AgeGroup` type lives in `ages.py` and the contract imports it, so there's one list.
- **Profile codes:** `ProfileContext` passes whatever the profile stores, typed as `str`: sex `male | female | intersex | prefer_not_to_say`, gender `woman | man | non_binary | agender | not_listed | prefer_not_to_say` with the write-in on `not_listed`. `pronouns` is now `str | None` (6.1 says it may be unset).
- **Widgets** (contract constants, enforced in `widgets.py` as the reply streams, so what's saved is exactly what was streamed):
    - `privacy_notice`: the Oracle sends `{"kind": "privacy_notice"}`; the backend sets the text, so a reply can't change the approved wording.
    - `product_link`: `{"kind", "label", "url"}`. **Adults only**: dropped for anyone under the age of majority (`is_adult` on the profile's own date of birth). Also dropped without a label or an `https` URL, or with spaces or hidden characters in the URL. Only `kind`, `label` and `url` are kept.
    - `disclosure`: any the Oracle sends are dropped; the backend adds exactly one, last, to every reply with a product link (3.1 "One disclosure box at the end").
    - `consult_support`: the backend sets the label "Consult with support team".
    - Every other kind passes through unchanged, as before.
- **Starters:** "Hormone imbalance" is added for every profile, including family members (it has no name or pronoun to adapt).

## 3.2 design choices

- **Order:** the check runs on every client message as soon as it's saved (unchanged `check_message_safety`, plus the `conversations.safety_check` retry job). The send answer's `next` is `safety_hold` before anything else, so an emergency or crisis is shown before the Health Consent. After the option is picked, `next` is `health_consent` or `reply` as usual.
- **What a check that escalates does** (in the same transaction that stores the level, so only once per message, even with parallel checks):
    1. saves the story's advice as an Oracle line in the conversation (no `reply_to_id`), shown straight away;
    2. records an `Escalation`;
    3. for an emergency or crisis, that escalation is an open **hold** until `client_choice` is set;
    4. calls the teen hook.
- **The advice line is the backend's text, not the Oracle's,** so the story's wording and numbers are always right. `MessageOut.safety` marks these lines (`urgent`, `emergency`, `crisis`) so the app can style them.
- **Hold scope (question 24): per conversation**, as the story says ("The conversation can’t continue"). New conversations and switching profile aren't blocked. The list marks held conversations (`safety_hold: true`), and the Oracle sees the advice in its earlier-conversations context.
- **A message sent during a hold (question 24): saved and checked, no reply.** Nothing typed in a crisis is lost, and a new emergency in it is recorded too (its own advice line and escalation). The answer is `next: "safety_hold"` with the hold. Refusing it would leave a worse message unchecked and unrecorded.
- **Picking an option:** `POST /conversations/{id}/safety-choice` with `{client_msg_id, option}`:
    - `called_for_help` or `safe_now` for an emergency, `reached_out` or `safe_now` for a crisis. A missing or wrong option gets 422 with 3.2's "Please let me know you’re safe before we continue." (field `option`);
    - it closes **every** open hold in the conversation (the newest decides which options are valid) and records the choice and its time on each;
    - the choice is saved as the client's next message: its label as text, `{"safety_option": ...}` as the answer, checked like any message. The Oracle's next reply answers it, with the whole history: the triggering message, the advice, anything typed during the hold, and the choice;
    - not refused by the trial, the rate limits or a turned-off or deletion-requested profile: nothing may keep a client from answering the safety screen;
    - safe to repeat with the same `client_msg_id` (200); 409 `no_safety_hold` when there's nothing to answer.
- **"The Oracle got it wrong":** with no hold (urgent), the client types it and the Oracle's reply apologises. During a hold the client types it (saved, checked, no reply) and picks "I’m safe now"; the reply then sees both. The apology wording is noted in the contract for the AI team. Nothing marks a false alarm on the escalation: the reviewer judges that (Super Admin 4.1).
- **Reply step:** `prepare_reply` refuses with 409 `safety_hold` while a hold is open, including one its own re-checks just found. A reply generated while a message sent meanwhile opened a hold isn't saved (stream error `safety_hold`).
- **Delete:** refused with 409 `safety_hold` while a hold is open. A check still to come could open one, so DELETE first runs the checks of any unchecked messages (no lock held, like the reply step), then re-checks under the conversation lock. If a check can't run, it answers 503 with "We couldn’t delete this conversation just now. Please try again."
- **Urgent:** advice line plus escalation, no hold. The Oracle then replies to the message as usual (after the consent).
- **Outside the US (question 26):** `SendMessage.outside_us` (default `false`). The app sets it when the device's location shows the client is outside the US; unknown location means US numbers. Stored on the message (`messages.outside_us`) because the worker's retried check needs it too, and on the escalation. A safety choice copies it from the hold.
- **Numbers:** US advice has 911 and 988 as the story says. Poison Control is added when the check sets `SafetyCheck.poison_control` (any level, US only). Outside the US, 911, 988 and Poison Control are all replaced by "Please call your local emergency number now."
- **Escalation records** (`escalations`):
    - plain ids, no foreign keys, so no CASCADE from messages, conversations, profiles or accounts;
    - kept for `settings.escalation_retention_years` (6); Phase 10's purge must leave them;
    - no message text, reason or name: the triggering message (`message_id`), the advice line (`response_message_id`) and the check's reason (`messages.safety_reason`, health data, purged with the message) are found by id while they exist;
    - stored codes: `level` `urgent | emergency | crisis`; `profile_type` `self | family_member` (Phase 3b adds `teen`); `client_choice` `called_for_help | reached_out | safe_now` or null ("No response"); `status` `not_reviewed | reviewed`, with `reviewed_by_id` and `reviewed_at` set exactly when reviewed; `outside_us` and `poison_control` record what the advice gave.
- **Admin side (no endpoint yet):** `safety.list_escalations` (not yet reviewed first, then newest) and `safety.set_review_status` (reviewed or not yet reviewed, row locked, audited). Review notes aren't stored: see the open questions.
- **No check-ins:** `safety.check_ins_blocked(db, profile_id=..., conversation_id=None, since=None)` is true after an emergency or crisis. Phase 9 must ask it before every follow-up, check-in or reminder. Phase 5's "never during an active emergency" can use `safety.open_hold`.
- **Teens:** `safety.tell_parent_about_teen(db, escalation)` is called for every emergency and crisis, in the recording transaction, and does nothing until Phase 3b.
- **Audit events:** `escalation.recorded` (no actor, no details, so the event alone doesn't say whose health it's about), `escalation.option_chosen` (the account as actor), `escalation.reviewed` and `escalation.review_undone` (the reviewer). None carries the level or the option.
- **FakeOracle:** a message containing "test emergency", "test crisis", "test urgent" or "test poison" (emergency with Poison Control) gets that level, any case. Other messages get `fake.safety` as before.

## API changes

- `SendMessage` takes `outside_us`.
- `MessageSent.next` adds `safety_hold`, and the answer has `safety` (this message's advice: level and line) and `safety_hold`.
- `ConversationOut` has `safety_hold` (level, `message_id` of the advice line, its text, the options with labels, and the "Option not selected" reminder). During a hold `awaiting_reply` is false and `welcome_back` is null.
- `ConversationSummary` has `safety_hold: bool`. `MessageOut` has `safety` on advice lines.

## Messages not in the stories

| Message | Situation |
| --- | --- |
| "This could be a medical emergency. Please call 911 for [Name] now." | Emergency for a family member (after 3.2's "Call 911 for [Name] now.") |
| "This is something to get checked soon. Please contact [Name]’s provider within the next 24 hours." | Urgent, for a family member |
| "This could be a medical emergency. Please call your local emergency number now." | Emergency outside the US: 3.2's first sentence plus its outside-the-US message |
| "I’m really glad you told me. You don’t have to go through this alone. Please call your local emergency number now." | Crisis outside the US: 988 is a US line |
| "For a poisoning or an overdose, you can also call Poison Control at 1-800-222-1222." | Added to the US advice when the check sets `poison_control` |
| "You’ve already answered this. Let’s carry on." | `safety-choice` with no open hold (answered on another device) |
| "Please let me know you’re safe before we continue." (3.2's "Option not selected") | Also used for: a missing or wrong option, a reply asked for during a hold, and DELETE during a hold |
| Privacy notice placeholder: "These questions are optional, and you can skip any of them. The answers are used only to tailor your health education, are never sold or shared with advertisers, are encrypted, and can be edited or deleted at any time." | Before the follow-up body questions, until the attorney's text (6.1 lists what it says) |
| Disclosure placeholder: "Genesis Health Products, the company behind Your Oracle, makes and sells some of the products linked here. Some links are affiliate links, so Genesis Health may earn a commission." | The one box after product links, until the attorney's text |
| "We couldn’t find that escalation." | Admin side, an unknown escalation id (Phase A) |

Crisis advice for a family member uses the story's crisis text unchanged.

## Assumed values

| Value | Assumed | Where |
| --- | --- | --- |
| Escalation retention | 6 years | `settings.escalation_retention_years` |
| Reason length | 200 characters, kept with the message | `safety.REASON_MAX_LENGTH` |
| Product link label / URL | 100 / 2,000 characters, `https` only | `widgets.py` |
| Age groups | 13, the age of majority, and 60, on Hawaii's date | `ages.py` |

## New open questions for the BA

- **Review notes** (Super Admin 4.1): the reviewer's notes are free text that may describe the client's health, but the escalation record outlives every deletion for 6 years. Keep them with the escalation (and accept health data there), or purge them with the conversation?
- **Hold scope:** per conversation (built) or for the whole profile? With per conversation, a client can start another conversation while one is paused.
- **Family-member wording:** is "I’m safe now" right when the advocate is answering about someone else ("[Name] is safe now")? Is the crisis text right when an advocate describes someone else's crisis (question 25)?
- **Poison Control:** we add it on the check's say-so at any level. Is that "where relevant"? Should it lead for a poisoning, before 911?
- **Trial ended:** sending is locked after the trial (3.1), so a message typed then is never checked. Is the safety check expected to run even with the message box locked? **Answered in the doc's comments** (3.1, 3 Nov, Azka Tariq, for Deborah): no emergency route is added for trial-locked clients or paused teens, because it's an education app; a paused teen stays paused until the Family plan is paid. So what we built stands.

Questions 24, 25, 26, 27 and 28 in `docs/PLAN.md` are still open; the choices above are our answers until the BA replies.

## For the migration (autogenerate misses these)

- `ck_messages_safety_fields` on the **existing** `messages` table: `role = 'client' OR (safety_reason IS NULL AND NOT outside_us)`.
- Autogenerate handles the rest: the `escalations` table with its check constraints and indexes (including the partial `ix_escalations_open_holds`), and `messages.safety_reason` and `messages.outside_us` (`server_default false`, so existing rows get `false`). No seed rows or data changes.

## Left for later

- **Phase 3b:** the parent's notice in `tell_parent_about_teen`, `profile_type = 'teen'`, and dropping the consult card for a teen with their own account (`widgets.prepare_widget`).
- **Phase 9:** call `check_ins_blocked` before every follow-up.
- **Phase 10:** the purge must keep escalations for 6 years and may delete `messages.safety_reason` with the messages.
- **Phase A:** admin endpoints over `list_escalations` and `set_review_status`, search and filters, and auditing every view.
- **Support (10.1):** `create_from_conversation` already refuses escalated messages; it may also want to refuse while `safety.open_hold` is set.
- **Tests** for all of the above.
