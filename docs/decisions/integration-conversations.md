# Integration: conversations with the health profile, support and admin alerts

Connects `app/conversations/` to the packages built after it: the health profile (`app/health/`, story 6.1), support requests (`app/support/`, story 10.1), admin notifications (`app/admin/notifications/`, Super Admin 11.1) and consent withdrawal (`app/accounts/`, story 11.4). Built 2026-11-05/06 against the 4 and 5 Nov stories, with `docs/decisions/phase-4-health-profile.md`, `10.1-support.md`, `r3-conversations-and-3.2.md` and `phase-5-guidance-and-notes.md`. No tests or migration (see the end).

## What was built

| Piece | Where |
| --- | --- |
| `HealthAnswer`, `HealthQuestion`, `HealthContext`, and `ProfileContext.health` | `app/oracle/contract.py` |
| Widget kinds `SUPPORT_OFFER` and `SUPPORT_REQUEST_SENT`, `SupportRequestKind`; `HEALTH_FACT` and `CONSULT_SUPPORT` notes updated; `stream_reply` docs | `app/oracle/contract.py` |
| `WIDGET_TEST_PHRASES`: "test health fact", "test knowledge gap", "test talk to someone" | `app/oracle/fake.py` |
| `health_context`, `profile_context(..., db)`, `_propose_facts`, `request_support` | `app/conversations/service.py` |
| `POST /conversations/{id}/support-request` | `app/conversations/router.py` |
| `RequestSupport`, `SupportRequestFromConversation` | `app/conversations/schemas.py` |
| Rules for support offers, health facts, the teen consult card; `fact_card`, `support_request_sent` | `app/conversations/widgets.py` |
| The admin alert hook, deliberately empty | `app/conversations/safety.py` (`alert_admin_team`) |
| The safety check job skips accounts whose consent is withdrawn | `app/conversations/jobs.py` |
| `max_health_facts_per_reply` | `app/core/config.py` |

## The health profile goes to the Oracle (stories 3.1 and 6.1)

- **One field on `ProfileContext`:** `health: HealthContext`, with `answered` (from `health_service.health_context`) and `unanswered` (from `open_questions`). We chose a `ProfileContext` field over a `stream_reply` parameter because `summarize`, `provider_notes` and the newer Oracle calls take `ProfileContext` too, so they get the health profile once their callers build it.
- **Its own types in the contract.** The contract can't import `app.health.service`, because that imports `app.conversations.widgets`, which imports the contract. So `conversations.health_context` copies each field into `HealthAnswer` and `HealthQuestion`. That also keeps "picked field by field" true.
- **Only answered, visible questions.** Removed answers, and answers kept from questions that no longer apply, aren't sent (6.1's "the Oracle stops using it"). About you stays in the existing `ProfileContext` fields.
- **Open questions are sent too.** The Oracle can't propose a `health_fact` without the question codes and choices, and it needs to know what's still open to ask "Asked later" questions only when they help.
- **`profile_context(profile, account, db=None)`.** The reply passes `db`, before the commit that comes ahead of `stream_reply`, so no transaction is open while the Oracle generates. Without `db`, `health` is empty. Guidance's two calls still leave it out (see "For other packages").
- **Not gated by the plan.** The health profile is sent during the trial too: "Never repeat" applies to every conversation, and phase 4 already lets facts be saved during the trial.
- **Health data.** It's never logged. `FakeOracle.last_context` keeps it for tests only.

## Health facts from chat

- **Held back while streaming.** `prepare_widget` checks only the shape of a `health_fact` widget: `question_key` is a string of up to 100 characters, and `other` is a string or null. Only `question_key`, `value` and `other` are kept. The widget isn't streamed while the Oracle generates, because no transaction may be open then.
- **Saved with the reply.** Under the conversation lock, in the reply's own transaction, `_propose_facts` calls `propose_fact(..., conversation_id=...)` for each proposal, each in a savepoint. A proposal that raises is skipped, and only its class name is logged; one that returns None is dropped. Each saved fact becomes `{"kind": "health_fact", "fact_id", "question_key"}`, phase 4's shape. If the reply isn't saved, its facts aren't either.
- **Order:** the streamed widgets, then the fact cards, then the one disclosure box last (3.1). The cards and the disclosure box are streamed after the commit and before `done`, so what's saved is still exactly what was streamed. When another stream saved the reply first, nothing more is streamed, and `done` carries that saved reply.
- **One card per fact.** Two proposals for the same question in one reply update the same pending fact, so only the first card is kept. At most `max_health_facts_per_reply` (10) are handled per reply: each one is a database write, and the Oracle's output is untrusted.
- **Lock order:** conversation, then the fact row (the `ON CONFLICT` update). Confirming locks the profile, then the fact, and never takes the conversation lock, so the two can't deadlock.
- **The FakeOracle:** a client message containing "test health fact" proposes `supplements`, a question that applies to every profile.

## Support from chat (story 10.1)

- **The Oracle signals with a widget.** `{"kind": "support_offer", "request_kind": "knowledge_gap" | "talk_to_support"}` goes with 10.1's offer text. The backend keeps only those two fields. It drops the offer when the message being answered wasn't found safe (`safety_level != "none"`), so the client never sees a button that 10.1 would refuse: an emergency, crisis or urgent concern gets the safety path instead.
- **The app asks with a dedicated endpoint** (our choice, over an `answer` on a message). `POST /conversations/{id}/support-request` takes `{kind, message_id}`, where `message_id` is the **Oracle reply that carries the offer**:
    - The backend checks that this reply is in the conversation and has an offer of that kind (otherwise 404 `support_offer_not_found`), so the Oracle, not the app, decides what counts as a knowledge gap.
    - The request copies the client message that the reply answers (`offer.reply_to_id`), through `create_from_conversation(..., message_id=...)`.
    - Sending happens only when the client taps. A typed "yes" isn't a send: the contract asks the Oracle to show the offer again, so consent is always explicit.
    - "No" needs no call: the conversation carries on (10.1's alternate scenario).
- **The confirmation is an Oracle line in the conversation:** 10.1's "I’ve let the support team know. They’ll get back to you by email within one business day." (`support.service.SENT_FROM_CONVERSATION`), with `{"kind": "support_request_sent", "support_request_id", "request_kind", "offer_message_id"}`. It stays in the history, the app can mark the offer as answered, and the Oracle can see it was sent. The line has no `reply_to_id`, so it changes neither `awaiting_reply` nor support's default source message.
- **One commit.** The request, its team email job, its audit event and the line are committed together, as `create_from_conversation` asks. A database error answers 503 `send_failed` with 10.1's "We couldn’t send your message just now. Please try again."
- **Safe to repeat.** Support returns the existing request for the same message and kind. The line is found again by a JSONB containment query on the request's id, under the conversation lock. A repeat answers 200; the first send answers 201.
- **Locks:** profile, then conversation, the same order as sending a message. The account row isn't locked: `complete_intake` and the purge lock profile then account, so locking the account first could deadlock. As a result, two requests at the same moment from different conversations could each pass support's hourly limit before either is saved.
- **Refusals:**
    - 409 `safety_hold` (3.2's "Please let me know you’re safe before we continue.") while an emergency or crisis hold is open, which 10.1-support.md suggested;
    - 404 for a deleted conversation;
    - and, from support itself: 409 `not_sendable`, a profile that can't be used (409), and 429 `too_many_support_requests`.
- **"Consult with support team" isn't a conversation request.** 10.1 says tapping it opens the Consult form ("What would you like help with?", mandatory), and a Consultation Request is `form`-only in `support_requests`. The card therefore opens the form, which posts to the existing `POST /profiles/{id}/support-requests` with `kind: consultation`.
- **Teens.** The consult card is now dropped for a teen with their own account (`support_service.is_teen_account`), the Phase 3b hook in `prepare_widget` (10.1: teens "don’t see Consult with support team").
- **The FakeOracle:** "test knowledge gap" and "test talk to someone" add an offer of each kind.

## Admin alerts

- **Not sent for escalations.** Super Admin 11.1: "No escalation notifications: Given an escalation is recorded, when it happens, then no notification is sent. It appears on the Dashboard and in Escalation Management." `app.admin.notifications.service.notify_admins` exists, but on purpose it has no escalation kind, so calling it would also fail.
- **The hook:** `safety.alert_admin_team(db, escalation)` runs in `record_escalation`'s transaction and does nothing. Its docstring gives the reason and the call to add if the BA changes 11.1.
- **Knowledge gaps and support requests are notified** (11.1), but that belongs where those records are made (see "For other packages"), not in conversations.

## Consent withdrawn (story 11.4)

- `retry_safety_check` returns without error, and without calling the Oracle, when `accounts.consent_withdrawn(db, account)` is true: consent is revoked, or the whole account is waiting for deletion.
- The message stays unchecked. If the client consents again, the reply step checks it before any reply. While consent is withdrawn, the policy gate already refuses every conversation endpoint.

## Stored codes

- **Widget kinds:**
    - `support_offer`, with `request_kind` `knowledge_gap` or `talk_to_support`;
    - `support_request_sent`, from the backend only (any the Oracle sends are dropped);
    - `health_fact`: the Oracle sends `question_key`, `value` and `other`; it's stored as `fact_id` and `question_key`.
- **Error codes:** `support_offer_not_found` (404), plus support's `send_failed`, `not_sendable`, `too_many_support_requests`, and `safety_hold`.

## Messages

All from the stories, apart from one reuse:

| Message | Situation | Code |
| --- | --- | --- |
| "We couldn’t find that message." (support's and feedback's existing text) | The offer is unknown, belongs to another conversation, isn't the Oracle's, or has no offer of that kind | `support_offer_not_found` |

## Assumed values

| Setting | Value | Why |
| --- | --- | --- |
| `max_health_facts_per_reply` | 10 | Each fact is a database write, and the Oracle's output is untrusted. Ten is more than one reply should ever propose. |

## New open questions for the BA

1. **Agreeing to send to support:** we send only when the client taps Yes on the offer, not when they type "yes". Is that right?
2. **Discarded facts:** the Oracle sees the health profile, but not which facts the client discarded, so it may offer the same one again in a later reply. Should a discarded fact stop that question being offered again, in that conversation or for good?
3. **Escalation alerts:** the task asked for admin alerts on escalations, but Super Admin 11.1 forbids them. We followed 11.1. Please confirm.
4. **Support offers for urgent concerns:** an urgent message still gets a reply (3.2), but we drop any support offer in it, because 10.1 sends urgent concerns down the safety path. Is that right?

## For other packages

- **Guidance (and visits and wellness, if they use `profile_context`):** call `conversations.profile_context(profile, account, db)` so summaries and notes get the health profile (the medications for 3.4's notes), then commit before the Oracle call. Today `share_summary` and `_ask_for_notes` call it without `db`, which leaves `health` empty.
- **Support:** `support.service._add` should call `notify_admins(db, "support_request", {"request_type": kind}, target_id=...)` for every request, from the forms and from conversations alike. The admin kinds file says "the support package passes its kind as request_type". Conversations doesn't call it, so that it isn't notified twice.
- **Knowledge (Super Admin 6.3):** the `knowledge_gap` admin notice ("[question]", targeting the gap) belongs where gap records are made from `knowledge_gap` support requests.

## For the migration

Nothing. There are no new tables, columns, constraints, seed rows or triggers. The confirmation line is an ordinary Oracle message (no `reply_to_id`), facts use `health_facts`, and requests use `support_requests`.
