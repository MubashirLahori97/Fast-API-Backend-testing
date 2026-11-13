# Conversations and health profile: the BA's 6 Nov 19:22 stories

Updates `app/conversations/` and `app/health/` for the 19:22 versions of "Start or Continue a Conversation" (3.1), "View Personalised Guidance Summary" (3.3, only how health details are saved and listed) and "View, Edit & Complete Health Profile" (6.1). Built 2026-11-10, on top of `phase-4-health-profile.md`, `integration-conversations.md` and `r3-conversations-and-3.2.md`. No tests or migration (the build rules).

## Health details are saved automatically (3.1, 3.3, 6.1)

- **What changed:** a `health_fact` widget used to become a *pending* fact the client confirmed ("Would you like me to add this to your health profile?"). That question is gone: the client accepted the Health Consent, so the Oracle's details are saved straight away.
- **How:** `app.health.service.save_from_conversation(db, profile, account, question_key, value, other, conversation_id)` writes the `health_answers` row with `source = 'conversation'`, the conversation's id, and `updated_at` = now. `conversations.service._save_health_details` calls it for each `health_fact` in the reply, in the reply's own transaction (each in a savepoint), then `record_conversation_saves` logs the change once (`health_profile.updated`, `source: conversation`), moves the review reminders and queues the Wellness Plan update, as a My Health save does. If the reply isn't saved, nothing is.
- **Checked like the app's answers:** an unknown question, a value the question doesn't take, a question that doesn't apply (before or after the change), or no change at all: dropped silently, with only the error's class logged. At most `max_health_facts_per_reply` (10) per reply.
- **Lists add, other answers replace.** Medicines, supplements and allergies (`named_list`) add new names after the saved ones (same name, any case, keeps the saved entry); symptoms (`checklist`) add the ticked items (and a newly ticked item stops being N/A). The story says the Oracle "saves the symptoms or medicines" and the client changes things in My Health, so an Oracle reply can never wipe a list. A list that would pass `health_list_max_items` is dropped. Other kinds replace the saved answer, like the client's own edit.
- **Locks:** when the reply has details, the profile row is locked (`FOR UPDATE`) before the conversation row, the same order as sending a message, the support request and `save_health_profile`.
- **Free trial:** saved anyway (3.3: "The health details are still saved"). My Health itself stays locked, as before.
- **No card in the chat.** The stories have no in-chat card for saved details any more, so the widget isn't streamed or stored on the reply; `fact_card` is gone. The Oracle sees what was saved in the next reply's `ProfileContext.health` (`from_conversation`).
- **"Added from our conversation on [date]" (6.1):** `AnswerOut.added_from_conversation_at` (new), set when `source` is `conversation`; the app formats the date. Editing the answer in My Health makes it `client` (it's the client's now), and removing it deletes it.
- **For the guidance summary (3.3):** `app.health.service.added_from_conversation(db, profile, account, conversation_id, since=None) -> list[AddedDetail]`, each with `key`, `section`, `question` (worded for the profile), `answer` (in words) and `added_at`, in the bank's order. Empty: the list isn't shown. Only answers still as the Oracle saved them, and only questions that apply. `since` keeps what was added after a time (for example the summary's last update). It doesn't check the trial (3.3 shows the list during the trial too). The guidance agent wires it in.
- **Removed from the conversation flow:** `_propose_facts`, `fact_card`, and the "What the Oracle noted" confirm step.
- **Kept, for 5.2 only:** pending facts and `GET /profiles/{id}/health-facts`, `PATCH .../health-facts/{fact_id}`, `POST .../confirm`, `POST .../discard`. Story 5.2 (and 6.1's "After a logged provider visit, the Oracle asks the Client before updating their health profile") still needs them: `app/visits/service.py` proposes a visit's medicine changes through `propose_fact`, unchanged. Docstrings now say so. Confirming a fact with no conversation (a visit's) now saves `source = 'client'`, so it doesn't show "Added from our conversation".

## 3.1's new rules (contract and widgets)

Most of this is the AI team's behaviour; the backend gives the Oracle the kinds and the exact texts, and enforces what it can.

| Kind | Shape | Backend rule |
| --- | --- | --- |
| `product_link` | `label`, `url`, `product_type` `genesis` / `affiliate` / `other` | Adults only, https. A missing or unknown `product_type` is stored as `affiliate`, so the box is never left off by mistake. |
| `test_link` (new) | `label`, `url`, `affiliate` (bool) | Adults only ("Products and links (adults only)"), https. Replaces test ordering. |
| `medicine_link` (new) | `label`, `url` | Every age; only `drugs.com` or its subdomains, https. |
| `label_directions` (new) | `product` `genesis_gold` / `sacred_seven` / `gen_pro`, `directions` | Adults only. The backend writes `text` = "How to take it (from the label): [directions]." and adds `product_name`. Directions up to 300 characters; a trailing period is dropped so the sentence doesn't end "..". |
| `disclosure` | `text` | One box, last, only when the reply has a `genesis` or `affiliate` product link, an affiliate test link, or label directions. Not for a medicine link, a plain test link or an `other` product. |

- **The disclosure sentence** is now the story's, word for word: "Genesis Health Products, which makes Your Oracle, also makes and sells Genesis Gold®, Sacred Seven® and Gen-Pro®." (`widgets.DISCLOSURE_TEXT`, which guidance and wellness import, so their boxes change too).
- **Contract constants** for the Oracle's reply text: `PRESCRIPTION_DOSE_REFUSAL` ("I can’t give a dose for a prescription medicine. Your provider or pharmacist can help with that.") and `TEST_ORDER_REFUSAL` ("I can’t order tests, but here’s a link where you can find out more about it."). The backend can't check reply text; `stream_reply`'s docstring lists the guardrails.
- **Label directions word for word:** the backend has no copy of the product labels (they're in the knowledge base the AI team indexes), so it can only format the sentence. See the open questions.
- **FakeOracle:** "test genesis product" (Gen-Pro® link + label directions → disclosure box), "test drugs link" (Drugs.com link, no box), "test order test" (the refusal text + a test link), "test prescription dose" (the refusal text). "test health fact" now saves the supplement straight away.

## Hypothalamus Circle Map (6.1)

- `GET /profiles/{id}/health-profile/circle-map`: the map's title, centre ("Hypothalamus"), 6.1's notice "This map shows how symptoms can connect to the hypothalamus. It isn’t a diagnosis.", its areas, each with its symptoms and `highlighted`, `highlighted_count`, `map_version` and `placeholder`.
- `GET /profiles/{id}/health-profile/circle-map/pdf`: a one-page PDF (fpdf2) to download and print: the ring of areas around the hypothalamus, areas with a highlighted symptom shaded, then each area's symptoms with the highlighted ones in bold with a bullet, and the notice. Made on request, never stored; `Cache-Control: no-store` comes from `app/main.py`.
- **Highlighting** comes from the symptom checklist answers that apply to the profile. Symptoms the Oracle learns in conversations are saved into those answers (above), which is how "from their health profile and their conversations" is met. Symptoms ticked in the chat's symptom check arrive as message text (`SendMessage`), so they count once the Oracle saves them.
- Both take `UsableProfile` and are locked during the free trial with 6.1's "My Health is part of your plan. Choose a plan to unlock it." (`upgrade_required`), like the rest of My Health. A teen's own map is on the teen's account, so the parent gets 404.
- **The map is a placeholder.** `app/health/circle_map.json` (`"status": "placeholder"`) has 7 areas and 25 symptoms the backend team made up from the symptom checklists. It is not Deborah's map. Each symptom lists the checklist items (`question_key.code`) that highlight it; the file is checked at startup against the question bank. Replace the file, or point `settings.health_circle_map_path` at Deborah's, when her map is in. The PDF says "Placeholder map: Deborah’s map will replace it." while `placeholder` is true.

## Stored codes

- `health_answers.source`: unchanged (`client`, `conversation`).
- Widget kinds: `test_link`, `medicine_link`, `label_directions` (new); `product_link.product_type` `genesis` / `affiliate` / `other`; `label_directions.product` `genesis_gold` / `sacred_seven` / `gen_pro` (`contract.GENESIS_PRODUCTS`).
- Audit: `health_profile.updated` with `source: conversation`, now written by the reply (no actor IP: there's no request object in the stream).

## Messages

From the stories: the disclosure sentence, the label directions sentence, the prescription dose and test ordering lines (3.1), and the Circle Map notice (6.1).

Not in the stories:

| Message | Situation |
| --- | --- |
| "Highlighted symptoms are in bold, marked •." | On the Circle Map PDF, above the list |
| "Placeholder map: Deborah’s map will replace it." | On the Circle Map PDF while the map file is the placeholder |
| "For [first name]" | The Circle Map PDF's subtitle |
| Area and symptom labels in `circle_map.json` | Placeholders |

## Assumed values

| Value | Assumed | Where |
| --- | --- | --- |
| Label directions length | 300 characters | `widgets.LABEL_DIRECTIONS_MAX_LENGTH` |
| Medicine link sites | drugs.com and its subdomains | `widgets.MEDICINE_LINK_HOSTS` |
| Product link with no type | treated as `affiliate` (box shown) | `widgets._product_link` |
| Circle Map file | `app/health/circle_map.json` (placeholder) | `settings.health_circle_map_path` |

## New open questions for the BA

1. **Contradiction in 3.1:** the acceptance criterion "Saving: ... when it wants to save it, then it asks the Client first" is still there, but the 19:22 text says the Oracle saves automatically (3.1's "Saving to the profile", 3.3, 6.1). We followed the newer text. Please remove or reword the old criterion. **Decided by the user on 10 Nov: follow the new text.**
2. **Lists:** we add the Oracle's medicines and symptoms to what's saved and never remove any (only the client removes, in My Health). If the client says in chat "I stopped taking X", should the Oracle take it off the list itself?
3. **Removed details coming back:** if the client removes a detail in My Health, an older message in the same conversation still says it. We ask the Oracle to save only from the latest message. Is that enough, or should a removed detail never be saved again from that conversation?
4. **Label directions word for word:** the backend can't check the directions against the label (the knowledge base is the AI team's). Should the Super Admin keep each product's label directions as their own field, so the backend can fill them in?
5. **Test links and affiliates:** are any of Deborah's test links affiliate links (which would show the disclosure box)? We support both.
6. **Drugs.com for teens and children:** 3.1 puts the Drugs.com link under "Medicines", not "Products and links (adults only)", so we allow it for every age. Is that right?
7. **Circle Map:** we need Deborah's map (areas, symptoms, and which symptoms link where) and the static graphic. Should the downloaded graphic show the client's highlights, or be her plain map?

## For the migration

Nothing to hand-add: no new tables, columns, constraints, seed rows or triggers. Pending `health_facts` rows from conversations made before this change stay pending; they can be left (they still confirm through the 5.2 endpoints) or cleared with `UPDATE health_facts SET status = 'discarded', answer = NULL, resolved_at = now() WHERE status = 'pending' AND conversation_id IS NOT NULL` (dev data only, optional).

## For other packages

- **Guidance (3.3):** call `app.health.service.added_from_conversation(db, profile, account, conversation.id)` for the list below the summary, with "Here’s what I’ve added to your health profile from our conversation. If anything isn’t right, you can change or remove it in My Health." and Review in My Health; hide it when empty.
- **Guidance and wellness:** `prepare_widget` now adds `product_type` to product links (they read only `label` and `url`, so nothing breaks), and `DISCLOSURE_TEXT` is the 19:22 sentence.
- **Dashboard (4.1):** `pending_facts` now counts only a visit's suggested changes.
