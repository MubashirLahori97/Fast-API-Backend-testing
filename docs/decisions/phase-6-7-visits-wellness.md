# Phases 6 and 7, Visit notes and the Wellness Plan: decisions

Stories "View, Download & Manage Visit Notes" (5.1), "Log Provider Visit Outcome" (5.2) and "View & Update the Wellness Plan" (7.1), built 2026-11-06 against the 4 Nov stories, on top of Phase 5 (`app/guidance/`), Phase 8 (`entitlements.feature_access`), Phase 9 (`notify`, `schedule`) and R3 (`safety.check_ins_blocked`). Code only: no tests and no migration yet (see the end).

## What was built

| Piece | Where |
| --- | --- |
| `VisitLog` | `app/visits/models.py` |
| My Visit Notes: the combined list and search (5.1) | `app/visits/listing.py` |
| Logging, editing, deleting visits; the Oracle's review job (5.2) | `app/visits/service.py`, `jobs.py` |
| `OwnedVisitLog` | `app/visits/dependencies.py` |
| `WellnessPlan`, `WellnessPlanItem`, `WellnessPlanVersion` | `app/wellness/models.py` |
| Triggers other packages call (a summary, a visit, a profile change) | `app/wellness/triggers.py` |
| The plan job: Oracle call, age rules, versions, check-ins | `app/wellness/updates.py`, `jobs.py` |
| Viewing, the card, ticking, the library, visit-deletion helpers, Oracle input | `app/wellness/service.py`, `context.py` |
| The Wellness Protocols library (data) | `app/wellness/protocols.json`, `protocols.py` |
| Contract: `review_visit`, `wellness_plan` and their dataclasses; `ProfileContext.visits` and `.wellness_plan` (defaulted, for the conversations package) | `app/oracle/contract.py`, `fake.py` |
| Hooks: plan update after a full summary; after every health profile change; `provider_note` and `visit_log` lookups | `app/guidance/service.py`, `app/health/service.py` (`_record_update`), `app/notifications/targets.py` |

## Endpoints

| Method and path | What it does |
| --- | --- |
| `GET /profiles/{id}/visit-notes` | 5.1's list |
| `POST /profiles/{id}/visit-notes/search` | 5.1's search, `{query}` in the body |
| `GET /profiles/{id}/visit-logs/form` | + Log a visit: first name and date of birth |
| `GET /provider-notes/{id}/visit-log/form` | Log visit on notes: pre-filled, with the notes read-only |
| `POST /profiles/{id}/visit-logs` | Save (201; 200 for a repeated `client_request_id`) |
| `GET /visit-logs/{id}` | A logged visit, with the review |
| `PUT /visit-logs/{id}` | Edit (the whole form) |
| `DELETE /visit-logs/{id}?plan_items=keep\|remove` | Delete (204) |
| `GET /profiles/{id}/wellness-plan` | The plan screen, or the "No plan yet" message |
| `GET /profiles/{id}/wellness-plan/card` | The dashboard and My Health card |
| `PUT /profiles/{id}/wellness-plan/items/{item_id}` | Tick or untick a To Do item (`{done}`) |
| `GET /profiles/{id}/wellness-protocols` | The library, for the profile's age |

## My Visit Notes (5.1)

- **One list** of the profile's guidance summaries, provider-ready notes and logged visits, built per request: upcoming appointments first (notes whose appointment is today or later on Hawaii's date and not yet logged), soonest first, labelled "Upcoming · Cardiology · 14 Nov"; then everything else, newest first by the card's date (a summary's `shared_at`, a note's or log's `created_at`). A passed or edited date re-sorts by itself.
- **One card per visit:** a log made for a set of notes appears on the notes' card (`visit_log_id`, Ask the Oracle and Edit instead of Log visit). A standalone log has its own card. A deleted conversation's summary and notes aren't listed (Phase 5); a log made for them is then shown as standalone.
- **Search in under 1 second:** three queries by `profile_id`, each on an index (`guidance_summaries.profile_id`, `ix_provider_notes_profile_created`, `ix_visit_logs_profile_created`), reading only the card fields (previews straight out of the JSONB with `->>`), then matching in memory: every word of the search must appear in the title, topic, specialty or provider name, ignoring case (NFKC, casefold). Hundreds of notes per profile take milliseconds. In memory because the titles and specialty labels are written by the backend (not columns), and because SQL can't search the fields once Phase 4 encrypts them. A visit log's reason counts as its topic.
- **The search text is in a POST body**, never the URL: what someone searches for can be health information, and URLs reach access logs.
- **Opening and downloading** use the existing endpoints: `GET /conversations/{id}/guidance-summary` (and its PDF), `GET /provider-notes/{id}` with its PDF, print and text, `PUT /provider-notes/{id}/appointment` for Edit appointment (3.4's messages). Logged visits have `can_download: false` and no download endpoint.
- **Free trial:** the list, search and every visit-log endpoint answer 403 `upgrade_required` (5.1's or 5.2's message). The notes stay viewable in their conversations (Phase 5).
- **Titles not in the stories:** a summary's card uses its conversation's topic, capitalised, or "Guidance summary"; a log's is "Cardiology visit" / "Azka’s Cardiology visit".

## Logging a visit (5.2)

- **Fields** follow the Provider Visit Summary template: visit date, why you went and how long, specialty (the 3.4 list plus "Other"), provider name, practice, follow-up appointment (a date), diagnosis or impression, their understanding, concerns not addressed, labs (name, who ordered it, Pending/Drawn/Resulted), medicine changes (New, Dose increased, Dose decreased, Discontinued, Continued, Added, with the new dose), Genesis Gold® and Sacred Seven® status (adults only), next steps (Routine/Schedule/Urgent) and their own notes. No uploads. Rows with no name or text are left out; up to `visit_log_max_rows` per section.
- **Mandatory:** visit date, why you went and specialty, with 5.2's messages. "In the future" is checked against the UTC date, which is ahead of every US state, so no client's today is refused.
- **Pre-filled** from notes: specialty, provider name, the reason (the notes' chief complaint), the requested labs (listed unmarked, `ordered: false`, for the client to mark), and the visit date when the appointment date isn't in the future. The notes come with the form, read-only. Standalone: first name and date of birth only.
- **Teens and children:** `show_genesis_status` is false and any status sent is dropped.
- **Saving needs no Oracle** (5.2's 3 seconds). In the same transaction it queues the review job, the Wellness Plan update, the lab results reminder and, for a new log, `health.reminders.visit_logged` (6.1's notice). For a linked note it cancels the note's `appointment_follow_up` and `booking_follow_up`. Idempotent through `client_request_id` (the profile row is locked). One log per set of notes: a second gets 409 `visit_already_logged`.
- **The response** carries 5.2's "Would you like to talk about what your provider said?" (`talk_it_through`), the urgent reminder when a next step is Urgent, and `ask_prompt`, the client's first message for a conversation about the visit.
- **The review** (`visits.review` job, `oracle.review_visit`): which of the notes' questions were answered, which requested labs were ordered, what was missed; Drugs.com links for new medicines (only https links to drugs.com are kept); interactions, shown as 5.2's "[Medicine] can interact with [existing medicine]..."; and medicine changes for the health profile, saved as **pending facts** through `health.service.propose_fact` (medications and supplements only), which the client confirms or discards in `/profiles/{id}/health-facts`. Nothing reaches the health profile without that confirmation. The review runs with no lock held; a newer save or a delete makes it do nothing; a failure marks it `failed` and the worker retries.
- **Edit** replaces the fields, raises `revision`, clears the review, and runs the review, the plan update (`visit_edited`) and the lab reminder again. The health profile notice is sent for new logs only.
- **Delete:** the GET gives `delete_confirmation` ("Delete this visit log? This can’t be undone.") and, when the log added plan items still in the plan, `plan_items_added` and 5.2's question ("1 item" for one). DELETE without `plan_items` then answers 409 `plan_items_choice_required` with the question. `remove` takes those items off the plan as a new version (`visit_deleted`); `keep` leaves them. The row is deleted (a linked note is "Not logged yet" again, and the Oracle no longer gets it), its reminders are cancelled, and `visit_log.deleted` is audited with ids and counts. Health profile answers already saved stay; pending facts stay for the client to decide. The note's appointment follow-up isn't rescheduled.
- **Lab results reminder:** `lab_results_expected` `lab_results_reminder_days` (7) after the visit date at `appointment_reminder_hour_utc`, when a lab is ordered and not resulted; none when that time has passed.
- **Drafts** ("saved as a draft while the client fills in the form") are the app's, on the device: the backend stores no half-filled health data. The "unsaved changes" text comes with the form.

## The Wellness Plan (7.1)

- **Creation and updates** go through one job, `wellness.update_plan`, with one new item: a full guidance summary (hooked in `guidance.service.share_summary`; First Looks don't count), a logged or edited visit, or a health profile change (hooked in `health.service._record_update`, so both client edits and confirmed facts count). Only a summary creates a plan; the others update an existing one. Identical waiting jobs aren't queued twice.
- **The job** checks the plan may change (subscribed, usable profile, item still there), asks `oracle.wellness_plan` with the current plan (items with ids) and only the new item, with no lock held, cleans the answer, then saves it under the plan's row lock. If another update saved first, it asks again (up to 3 times). A failure sets `update_failed_at`, which shows 7.1's "I couldn’t update your Wellness Plan just now. I’ll try again shortly.", and the worker retries.
- **Placement:** the Oracle names existing items by id to update, tick off (`done`) or remove; items without an id are added. Focus areas show newest first, To Do items in the order added. Removed items stay as rows (`removed_at`, `removed_reason`) for the history.
- **Versions:** every saved update raises `version` and adds a `WellnessPlanVersion` with the trigger, the source id, a snapshot of the whole plan and the changed ids. Only the latest is shown. Audit events `wellness_plan.created` / `.updated` hold ids, the version and the trigger.
- **Messages:** the plan shows the latest version's message: created, updated, or "...no longer having these issues" when a focus area was resolved. The client is notified (`wellness_plan_updated`) for updates, not for creation (see the questions).
- **Ticking:** To Do items only, under the item's row lock; ticking cancels the item's check-in, unticking reschedules it. Ticks are audited (`wellness_plan.item_completed`, `.item_reopened`) and aren't plan versions. "You’ve completed everything on your list. Well done!" when all are done.
- **Check-ins:** an item the Oracle gives a time frame end (`follow_up_in_days`) or due date (`due_in_days`) gets `wellness_plan_check_in` that day at `wellness_check_in_hour_utc`, through `notifications.schedule`, which skips it after an emergency or crisis (`check_ins_blocked`), for turned-off members and when the type is off. Its `target_id` is the item, so it's cancelled when the item is done or removed.
- **Card:** current focus (the newest focus area, else "Immediate dietary action"), progress dots, `check_in_due`. Null before the first plan.
- **Five Pillars:** adjustments stored per pillar; the library links are the backend's (Nutraceuticals: Genesis Gold®, plus Sacred Seven® when recommended; Diet: Healthy Four and the Insulin Resistance Diet; Activity: HIIT and Contraction-Relaxation; Sleep: Deep Sleep and the 7 Secrets; Mindset: CALM and the Healing Meditation). The Beet Test and cleanses are linked only from items. Diet without Healthy Four targets shows "Share your measurements...".
- **Age rules,** applied when saving and again when showing, below the age of majority: no products, no item about a product, no item linking a product tab or a cleanse, no Foundational Nutraceuticals pillar, no product notices; the library has no product tabs, shop links, Beet Test or Liver-Kidney Cleanse.
- **Products and links:** labels and https URLs only (the 3.1 product-link rules), never a price. When products appear (product links, an item's product, or the Nutraceuticals adjustment), the plan carries the product disclaimer and one disclosure box.
- **Safety notices** are codes from the Oracle shown as 7.1's exact texts; conflicts are To Do ids shown as "...item [X] in your plan...", X being the item's number in the list. The safety rules themselves stay in the AI guardrails (7.1).
- **Trial:** the plan, card and ticking answer 403 "Subscribe to get your personal Wellness Plan."; nothing is created or updated (checked at the trigger and in the job). The library isn't locked.
- **Library:** `protocols.json` (four tabs, sections with `key` link targets), replaceable through `wellness_protocols_path`. Content waits for Deborah's document (`content: null`). Shop links and the CALM guide URL are settings.

## Stored codes

- `visit_logs.review_status`: `pending | ready | failed`. Labs `status`: `pending | drawn | resulted`. Medicine `change`: `new | dose_increased | dose_decreased | discontinued | continued | added`. Next step `priority`: `routine | schedule | urgent`. `genesis_gold_status`, `sacred_seven_status`: `taking | started | stopped | not_taking`.
- `wellness_plan_items.kind`: `focus_area | todo`; `status`: `open | done`; `completed_by`: `client | oracle`; `source_type`: `guidance_summary | visit_log | health_profile`; `removed_reason`: `resolved | course_finished | removed | visit_deleted`.
- `wellness_plan_versions.trigger`: `guidance_summary | visit_logged | visit_edited | visit_deleted | health_profile`; `outcome`: `created | updated | resolved`.
- Pillars: `nutraceuticals | diet | activity | sleep | mindset`. Notices: `hyperthyroid_sacred_seven_first | gen_pro_dose | gender_affirming_hormones | cleanse_not_suitable`. Library keys: `genesis-gold`, `sacred-seven`, `gen-pro`, `healthy-four`, `insulin-resistance-diet`, `beet-test`, `liver-kidney-cleanse`, `hiit`, `contraction-relaxation`, `calm`, `healing-meditation`, `seven-secrets`, `deep-sleep`.
- Jobs: `visits.review` (`visit_log_id`, `revision`), `wellness.update_plan` (`profile_id`, `trigger`, `source_id`, `revision`).
- Error codes: `upgrade_required` (403); `visit_log_not_found`, `provider_notes_not_found`, `plan_item_not_found` (404); `visit_already_logged`, `plan_items_choice_required` (409); `save_failed`, `delete_failed`, `load_failed`, `item_update_failed` (503); `validation_error` (422).
- Audit: `visit_log.created`, `.updated`, `.deleted`; `wellness_plan.created`, `.updated`, `.item_completed`, `.item_reopened`. Ids, counts, versions and triggers only.

## Messages not in the stories

| Message | Situation |
| --- | --- |
| "We couldn’t find that visit log." | Unknown or another account's log |
| "You’ve already logged this visit. You can edit it instead." | A second log for the same notes |
| "Please choose what changed for this medicine." | A medicine row with a name and no change |
| "Please keep this to 100 characters or fewer." | A name or short write-in too long |
| "I’d like to talk about my [specialty] visit on [date]." / "...about [Name]’s [specialty] visit on [date]." | Ask the Oracle and Talk it through |
| "[Specialty] visit" / "[Name]’s [Specialty] visit", "Guidance summary" | Card and log titles |
| "Taking it", "Starting it", "Stopped it", "Not taking it" | Genesis Gold® / Sacred Seven® status options |
| "We couldn’t find that item in the Wellness Plan." | Unknown, removed or non-To Do item |
| "Can you tell me more about “[title]” in my / [Name]’s Wellness Plan?", "Can you explain why “[text]” is in my / [Name]’s Wellness Plan?" | Ask the Oracle on a focus area or To Do item |
| "Immediate dietary action" | The card's current focus with no focus area |
| "[Name]’s Wellness Plan" | Plan title, own profile too |
| FDA disclaimer placeholder: "These statements have not been evaluated by the Food and Drug Administration. This product is not intended to diagnose, treat, cure, or prevent any disease." | Product tabs, and the plan's product disclaimer |
| "Genesis Health Products, the company behind Your Oracle, makes and sells this product." | Product tabs' ownership disclosure |
| The plan's disclosure box uses R3's placeholder (`DISCLOSURE_TEXT`) | Until the attorney's text |
| Library section titles and parts in `protocols.json` | From 7.1's list |

## Assumed values (settings)

| Setting | Value |
| --- | --- |
| `visit_notes_search_max_length` | 100 |
| `visit_log_max_rows` | 30 rows per section |
| `lab_results_reminder_days` | 7, at `appointment_reminder_hour_utc` (18) |
| `oracle_visit_logs` | 10 latest logs in `ProfileContext.visits` |
| `wellness_check_in_hour_utc` | 18 (question 8) |
| `wellness_protocols_path` | none: `app/wellness/protocols.json` |
| `wellness_shop_links`, `calm_guide_url` | example.com placeholders |
| Caps on Oracle output (constants) | 30 items, 500 characters a line, 4,000 a paragraph, follow-ups 1 to 365 days |

## New open questions for the BA

1. **Plan created notice:** 12.1 has only "Your Wellness Plan has been updated." Should creation send a notice with 7.1's "I’ve started your Wellness Plan..." (needs a new kind)? Built: no notice; the plan shows the message.
2. **First Look summaries:** does a First Look start or update the plan? Built: full summaries only.
3. **Question 11 again:** when a trial client subscribes, is a plan built from their trial summaries? Built: no; the next full summary creates it.
4. **Follow-up appointment:** should 5.2's follow-up appointment date get an appointment reminder and an Upcoming card? Built: stored and given to the Oracle only (no notifications kind targets a visit log for it).
5. **Genesis Gold® / Sacred Seven® status options:** what are they? Built: taking, starting, stopped, not taking.
6. **When are lab results "expected"?** Built: 7 days after the visit.
7. **Deleting a log:** should pending profile facts the visit proposed be discarded, and should the note's "How did it go?" come back? Built: neither.
8. **Ticks:** recorded on the item and in the audit log, not as plan versions. Enough for 7.1's "every update is recorded"?
9. **The library during the trial:** open (built) or greyed out with the plan?
10. **Healthy Four targets (question 10):** the Oracle's output for now. If they're fixed maths, the backend should work them out from lean body mass and weight.
11. **Teens' Beet Test:** hidden with the cleanses (built). Right?

## For the migration (autogenerate misses these)

Nothing to hand-add: four new tables (`visit_logs`, `wellness_plans`, `wellness_plan_items`, `wellness_plan_versions`), whose check, unique and foreign key constraints and indexes are all on the new tables. Check that `visit_logs.provider_note_id` keeps `ON DELETE SET NULL` and the others `ON DELETE CASCADE`. No changes to existing tables, no seed rows, no data changes, no triggers.

## Left for others

- **Conversations:** done during integration: `conversations.service.profile_context(..., db)` fills `ProfileContext.visits` (`app.visits.service.oracle_visits`) and `.wellness_plan` (`app.wellness.service.oracle_plan`) for replies, so the Oracle uses the plan and follows up on due items (7.1) and stops using deleted logs (5.2). Optionally start a conversation linked to a visit or plan item; today the app sends `ask_prompt` as the first message.
- **Phase 10:** done during integration: the export (11.4) includes visit logs and the plan. Deleting a profile deletes its logs, plan, items and versions (CASCADE); the audit events stay, with ids only.
- **Phase 11:** the dashboard can call `wellness.service.get_card` and `visits.listing.visit_notes`.
- **Phase 4:** field encryption for `visit_logs` and the plan's text.
- **Phase 5:** fixed during integration: `FAKE_SUMMARY` now uses the library key "calm".
- **Tests** for all of the above.
