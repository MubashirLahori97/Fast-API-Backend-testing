# Senior chat API as the Oracle's replies (11 Nov)

`app/oracle/senior.py` (`SeniorChatOracle`) sends story 3.1's replies to the senior team's
dev chat API. Everything else is still `FakeOracle`. Chosen with `ORACLE_BACKEND=senior`
(default `fake`).

## It never runs in production

`get_oracle` still raises in production, whichever backend is set: the safety check (story
3.2) is still the fake's phrase check, and the senior API has no safety endpoint we can call
before the reply. The senior dev server also has no authentication, no BAA we know of, and
reports `langfuse_enabled: true` on `/api/v1/health` (traces may leave their server). Send it
test messages only.

## Design choices

- **Thread id = our conversation id** (a UUID string, which fits the senior schema: 8 to 64
  characters of `[A-Za-z0-9_-]`). `Oracle.stream_reply` takes a new keyword-only
  `conversation_id` (contract, FakeOracle and `conversations.service._generate_reply` updated);
  the fake ignores it. It's an id, never health data, so it may go in the URL.
- **What's sent each turn:** the client turns since the last Oracle turn in our history, joined
  by blank lines (more than one after a safety hold). The senior API keeps the thread's history,
  so earlier turns aren't sent again. `earlier` (other conversations) isn't sent: there's no
  field for it.
- **Context preamble:** the senior API takes only a message, so the first message of a thread
  starts with a short note built from `ProfileContext`: who the reply is for (self, family
  member with relationship and first name, or a teen on their own account), the age group,
  pronouns, and for anyone under the age of majority 3.1's rule "Education only: no product
  names, no links to products, and no dosing" (a teen's own account adds "don't interpret their
  own lab results" and "never suggest a parent will see this"). No health answers, sex at birth,
  visits or Wellness Plan: kept minimal on purpose. **A proper `context` field in the senior
  API would replace this**; the preamble is a client-written-looking string the model may
  ignore, and names in it came from a client.
- **When the preamble is sent:** before each reply we `GET /threads/{id}` and send the preamble
  unless a stored user message starts with its header line. Checked this way because the senior
  API keeps the user message of a turn that failed (seen on 11 Nov), and our history holds the
  backend's own lines (opening question, safety advice), so neither "thread has messages" nor
  our history tells reliably.
- **Events:** `token` → reply delta (the text pieces). `start`, `status` ignored. `sources`
  (knowledge base citations: title, chapter, excerpt) is kept out: the contract has no widget
  or field for citations, and the apps don't render one. `meta` (route, urgency, `products`,
  `drug_links`, `emergency_kind`, `product_disclosure`) is kept out too: products and Drugs.com
  links could map to `PRODUCT_LINK` / `MEDICINE_LINK` widgets, but that's product behaviour for
  the AI team and BA to agree. `done` ends the reply.
- **Failures → `OracleError`** (so the service's "reply_failed" path runs, the claim is
  released and the client can retry): an `error` event, a non-200 answer, any `httpx` error
  (connect, timeout), unreadable JSON, a stream that ends without `done`, a message over the
  senior limit of 4,000 characters (ours is 8,000), or the whole reply passing
  `reply_timeout_seconds` (checked on every event, status included). Error messages are fixed
  text plus at most a status code or exception class name; nothing from the request or
  response. `senior.py` logs nothing.
- **Timeouts:** `senior_chat_timeout_seconds` (30) for each network step (connect, each read
  of the stream). The contract's "3 seconds to the first piece" can't be met as-is: the senior
  API spends several seconds in triage/retrieve before its first token.
- **Deleting a conversation:** `delete_conversation` has no Oracle hook, so the senior thread
  is not deleted. `SeniorChatOracle.delete_thread(id)` exists (never raises, returns whether it
  worked) for when a hook is added. Until then a deleted conversation's text stays on the
  senior server.
- `httpx` comes in through `fastapi[standard]`; it isn't a direct dependency in
  `pyproject.toml`. Make it one (`uv add httpx`) if the senior client stays.

## Settings

`oracle_backend` (`fake` | `senior`), `senior_chat_base_url`, `senior_chat_timeout_seconds`,
in `config.py` and `.env.example`.

## What the senior API would need to replace the fake parts

1. A **safety check** endpoint (story 3.2): one message plus `SafetyContext`, answering
   `level` (none/urgent/emergency/crisis), `reason` and `poison_control` within 2 seconds,
   before any reply and before the Health Consent. Their stream already triages
   (`meta.emergency_kind`, scripted emergency route), but only inside the reply.
2. A **`context` field** on `/chat/stream` taking `ProfileContext` (who, age group, pronouns,
   health profile answered/unanswered, routing, visits, Wellness Plan, teen rules) and the
   earlier conversations, instead of the preamble.
3. **Widgets** in the stream for the contract's kinds: `health_fact`, `product_link`,
   `medicine_link`, `test_link`, `label_directions`, `support_offer`, `appointment_card`,
   `guidance_summary`, `privacy_notice`, `update_provider_notes`, tap-to-answer options.
4. **Topic** (a few words for the conversation list), **guidance summary** (3.3),
   **provider-ready notes** (3.4), **visit review** (5.2) and **Wellness Plan update** (7.1)
   endpoints returning the contract's types.
5. **Knowledge base** publish/withdraw by content id, and **knowledge gap matching**
   (Super Admin 6.2, 6.3). Today their knowledge base is their own ingestion.
6. **Authentication** between our backend and theirs, a BAA, no retention beyond what's agreed,
   and tracing (Langfuse) turned off or covered for health data.
7. A **retry-safe turn**: an idempotency key per client message, since a retried reply now adds
   the client's text to their thread a second time.
8. A larger message limit (ours is 8,000 characters, theirs 4,000).

## Open questions

- Should `meta.products` / `meta.drug_links` become `PRODUCT_LINK` / `MEDICINE_LINK` widgets
  while we wait for proper widgets?
- Should the conversation delete call `DELETE /threads/{id}` (needs a contract hook)?

## Test calls (11 Nov)

`GET /api/v1/health` answered `status: ok` (model `claude-sonnet-5-5`). Four test messages to
`/chat/stream` (two by curl, two through `SeniorChatOracle`, one with the preamble) all got
`start`, four `status` events (triage, understand, retrieve, generate) and then `error`
("Something went wrong while preparing your answer. Please try again."), with no `token`. Every
test thread was deleted (`{"deleted": ...}` / `delete_thread` → True). The token → delta path,
the preamble and the failure mapping were checked with the same event shapes through
`httpx.MockTransport`.
