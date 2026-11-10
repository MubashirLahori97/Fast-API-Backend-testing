# Phase 5 Oracle outputs: decisions

Stories "View Personalised Guidance Summary" (3.3), "Generate Provider-Ready Notes from Conversation" (3.4) and "View, Edit & Download Provider-Ready Notes" (3.5), built 2026-11-05 against the 4 Nov stories, with the R3 safety holds (`docs/decisions/r3-conversations-and-3.2.md`). No tests or migration yet (see the end).

## What was built

| Piece | Where |
| --- | --- |
| Contract: `summarize` and `provider_notes`, their dataclasses, four widget kinds, the content rules (lab values explained, never interpreted) | `app/oracle/contract.py` |
| `FakeOracle.summarize` / `provider_notes` with `FAKE_SUMMARY` and `FAKE_NOTES` | `app/oracle/fake.py` |
| `GuidanceSummary`, `ProviderNote`, `ProviderNoteVersion` | `app/guidance/models.py` |
| The rules | `app/guidance/service.py` |
| The specialty list and the appointment card | `app/guidance/specialties.py`, `settings.provider_specialties` |
| Fixed texts, sections in order, plain text, PDF, file names | `app/guidance/documents.py` |
| Reminders through `app.notifications.service.schedule` / `cancel_scheduled` | `app/guidance/reminders.py` |
| `OwnedProviderNote` | `app/guidance/dependencies.py` |
| Hooks: the appointment card and notes card widgets; cancelling reminders when a conversation is deleted | `app/conversations/widgets.py`, `app/conversations/service.py` |

## How it fits the conversation

- **The Oracle decides when, the app asks.** The Oracle's reply carries a widget, and the app calls the endpoint:
    - `guidance_summary`: the reply introduces or updates the summary (or a First Look the client asked for). The app calls `POST /conversations/{id}/guidance-summary` and shows the summary there.
    - `appointment_card`: the Oracle is ready to make notes (3.4 Scenarios A and B). The backend keeps only the card's known fields, and moves a specialty that isn't on the list to "Other" with its text (3.4). The app shows the card and calls `POST /conversations/{id}/provider-notes`.
    - `update_provider_notes`: the client asked for a change in the conversation. The app calls `POST /provider-notes/{id}/refresh`.
    - `provider_notes` (`notes_id`): the notes card in the conversation. Only the backend adds it; any the Oracle sends are dropped.
- **Gates**, the same as for a reply: a usable profile, a trial or plan (`check_can_talk`), the Health Consent, every client message safety-checked (unchecked ones are checked first, with no lock held), and no emergency or crisis hold. The gates are checked again under the conversation lock before saving, so a hold opened meanwhile, or a deleted conversation, stops the save.
- **One Oracle request at a time** per summary or set of notes: a claim (`generation_started_at`), expiring after `guidance_claim_seconds`. A second request gets 409 (`summary_in_progress`, `notes_in_progress`).
- **Oracle failures** are logged by class name only, release the claim and change nothing. An answer of the wrong shape, or with an empty required section, counts as a failure.

## Guidance summaries (3.3)

- **One per conversation** (unique `conversation_id`). `POST` writes it the first time (201) and updates it later (200). When no client message has arrived since it was written (`covers_message_id`), it's returned unchanged and the Oracle isn't asked, so calling it again costs nothing. The Oracle gets the stored summary as `previous`, to update rather than rewrite (Session 10).
- **First Look:** `stage = "first_look"`, with its own introduction and a "What I’d Still Like to Know" section from `still_needed`. The next update can make it `full`.
- **Sections:** sent as an ordered list in 3.3's order, with empty ones left out. Hypothalamic Connection appears only when the Oracle gives one.
- **Recommendations:**
    - kept only for adults (`is_adult`) when the summary is saved;
    - hidden while an emergency or crisis hold is open, together with the product note and the disclosure box;
    - each one needs a label and an https URL (the 3.1 product link check). No prices are stored.
    - 3.3's product note ("Genesis Gold® contains no hormones...") is added when a `genesis_product` is recommended.
- **Disclosure box:** one, at the end, when any recommendation is shown. **Disclaimer:** always.
- **Introduction:** 3.3's "Thank you for sharing all of that. Here’s what I’m seeing." for a full summary.
- **Follow-up:** each full summary schedules `guidance_follow_up` for `guidance_follow_up_days` (14) later and cancels the earlier one, so a conversation has at most one. `notifications.schedule` skips it after an emergency or crisis. It's scheduled for trial clients too (see the questions).
- **Free trial:** the summary is shown in full; `can_download` is false with "Subscribe to download and keep your guidance." The PDF endpoint refuses with the same message.
- **Not built here:** the "Save to my profile" checklist under the summary is Phase 4's fact extraction (`app/health`), and "New recommendations go to the top of the Wellness Plan" is Phase 7's.

## Provider-ready notes (3.4)

- **Question 15: several sets of notes per conversation**, one per appointment (a cardiologist and an endocrinologist about the same concern, say). 5.1 already lists "every set of notes ... under its conversation". There are at most `max_provider_notes_per_conversation` (10) per conversation, because each costs an Oracle call.
- **Create** takes the card plus `booking`:
    - `booked`: the card, specialty required;
    - `not_yet`: the Oracle's suggested specialty (primary care when there's none), with no provider or date;
    - `skip`: primary care, no details.

  `client_request_id` makes a retry return the same notes.
- **Outcomes:** `next` in the answer is one of:
    - `ready`: notes made. An Oracle line is added to the conversation with 3.4's "Notes ready" text, or "Not yet booked", and the notes card.
    - `more_questions`: the Oracle's question is added to the conversation, and no notes are made.
    - `clarify_specialty`: an "Other" the Oracle can't place. 3.4's "Just to check, what kind of provider is [text]?..." is added as an Oracle line, not sent as an error, because the write-in is the client's health context.
    - `unchanged`: a retry of a create that already happened.
- **What the Oracle gets:** the profile context (no date of birth), the conversation, and `NotesSpecialty` (code, name, booked). It never gets the provider's name or the date. **The backend writes the header**: first name only (the profile's own), date of birth, specialty, provider and date when known, and "Prepared by: [client], medical advocate" for a family member. It also writes "What this is", the Genesis Gold® note (adults only, when `taking_genesis_gold`), "No urgent red flags identified in this session." and the disclaimer.
- **Disclosure box** when `mentions_products` or the Genesis Gold® note is shown. Both are forced off under the age of majority.
- **Reminders** (`reminders.schedule_appointment`):
    - with a date: `appointment_reminder` the day before at 18:00 UTC (skipped if that time has passed), and `appointment_follow_up` the day after;
    - without one: `booking_follow_up` after 7 days.

  Rescheduling cancels the notes' three kinds first.

## View, edit and download (3.5)

- **Edit means appointment details only.** The brief said "edit the text, keeping the original", but 3.5 is explicit: the content is read-only, and only the specialty, provider name and date change. We followed the story. The content changes only when the Oracle rewrites it:
    - a new specialty (`specialty_changed`);
    - `refresh` after a request in the conversation (`updated_from_conversation`).

  Each rewrite is a new `ProviderNoteVersion`; every earlier one is kept, version 1 being the original. The screen shows the latest.
- **A new specialty** is saved only together with the Oracle's rewrite, so the content always matches the specialty. The Oracle line "I’ve updated your notes for your [specialty] appointment." is added. During a hold it's refused (409), and after the trial ends too (it needs the Oracle).
- **A new name or date** needs no Oracle: allowed during the trial, after it ends and during a hold. The header follows. A changed or removed date reschedules the reminders (a removed one gives the booking follow-up). A name change alone reschedules nothing, because the reminder texts don't use the name and rescheduling would push the booking follow-up back.
- **Past dates** get 3.4's message (field `appointment_date`), counted on Hawaii's date so nobody in the US is refused today. Dates more than `appointment_max_years_ahead` (2) years ahead are refused.
- **Copy text** (`GET .../text`, JSON `{text, confirmation}`) and **PDF** (`GET .../pdf?paper=letter|a4`; Print uses the same PDF) are built from the same document as the screen, so both carry the disclaimer and, when relevant, the disclosure box. Both are locked during the trial with "Subscribe to download, print and copy your provider notes." (403 `upgrade_required`), using the plan's `downloads` feature in `app/billing/entitlements.py`, which also covers teens with their own account in Phase 3b.
- **File names:**
    - notes: "Notes_[First name]_[Specialty]_[dd-Mon-yyyy].pdf", with the appointment date when known and the creation date otherwise (5.1's example uses the appointment date);
    - summaries: "Guidance-Summary_[First name]_[updated date].pdf".

  The `Content-Disposition` header has an ASCII name plus the UTF-8 one. PDFs are made per request, never stored, and sent with `no-store`.
- **Fonts:** the PDF uses the built-in Helvetica with Windows-1252, so typographic quotes and ® print, but characters outside it (for example a name in another script) print as "?". Before production, embed a Unicode font such as Noto Sans.
- **Ownership:**
    - summaries go through `OwnedConversation` and `OwnedProfile`;
    - notes go through `OwnedProviderNote`, which checks that the profile is the account's and the conversation isn't deleted, with the same 404 otherwise.

  A teen with their own account owns their profile, so the parent never sees their notes or summaries. A managed teen's are the parent's, as advocate.
- **Turned-off or deletion-requested family members:** their summaries and notes can still be viewed and downloaded (like reading past conversations). Writing, rewriting and editing are refused (`check_can_use`).
- **Question 45 (a deleted conversation):** its summary and notes answer 404, leave every list, and their reminders are cancelled (`reminders.conversation_deleted`). The rows stay until Phase 10's purge, like the messages.

## Stored codes

- `guidance_summaries.stage`: `first_look | full`.
- `provider_notes.specialty` and `provider_note_versions.specialty`: a code from `settings.provider_specialties` (`primary_care`, `ob_gyn`, `endocrinology`, `integrative_functional`, `rheumatology`, `neurology`, `urology`, `cardiology`, `psychiatry`) or `other` with `specialty_other`. Never rename a code: stored notes use it.
- `provider_note_versions.reason`: `created | specialty_changed | updated_from_conversation`.
- Recommendation `kind`: `genesis_product | partner_product | medicine | test | other`.
- Error codes:
    - `guidance_summary_not_found`, `provider_notes_not_found` (404);
    - `summary_in_progress`, `notes_in_progress`, `too_many_notes`, `safety_hold` (409);
    - `summary_failed`, `notes_failed`, `download_failed`, `safety_check_failed` (503);
    - `upgrade_required` (403);
    - `specialty_required`, `specialty_other_required`, `appointment_date_passed`, `appointment_date_too_far`, `too_long` (422).
- Audit events. Each has the account as actor and holds only ids (and a version number):
    - `guidance_summary.shared`, `guidance_summary.updated`, `guidance_summary.downloaded`;
    - `provider_notes.created`, `provider_notes.appointment_changed`, `provider_notes.specialty_changed`, `provider_notes.updated`, `provider_notes.copied`, `provider_notes.downloaded`.

## Messages not in the stories

| Message | Situation |
| --- | --- |
| "Here’s what I can say so far, from what you’ve shared." | Introduction of a First Look |
| "What I’d Still Like to Know" | First Look section for `still_needed` |
| "There’s no summary for this conversation yet." | GET or PDF before any summary |
| "I’m still working on your summary. Please wait a moment." | Second summary request while one runs |
| "I’m still working on your notes. Please wait a moment." | Second rewrite of the same notes while one runs |
| "We couldn’t find those notes." | Unknown, another account's, or a deleted conversation's notes |
| "You’ve already made a lot of notes in this conversation. Please edit the appointment on one of them instead." | Over `max_provider_notes_per_conversation` |
| "Please choose a date within the next 2 years." | Appointment date too far ahead |
| "Notes for my [Specialty] appointment" / "Notes for [Name]’s [Specialty] appointment" | Notes titles (3.5's example is the first) |
| "Your guidance summary" / "Guidance summary for [Name]" | The summary PDF's title |
| "Prepared by: [Name], medical advocate" | A family member's notes header |
| "What this is", "Lab values as I reported them", "Also request", "Disclosure" | Headings in the notes text and PDF |
| Notes disclosure placeholder: "Genesis Health Products, the company behind Your Oracle, makes and sells some of the products mentioned here. Some links are affiliate links, so Genesis Health may earn a commission." | Until the attorney's text. The summary uses R3's placeholder, since its box follows links |
| A failed summary uses 9.2's "We couldn’t do that just now. Please try again." | 3.3 has no message for it |

## Assumed values (all settings)

| Setting | Value |
| --- | --- |
| `provider_specialties` | 3.4's nine options, with each one's provider ("a cardiologist") for the "Not yet" message |
| `oracle_output_history_messages` | 200 latest messages |
| `guidance_claim_seconds` | 60 |
| `max_provider_notes_per_conversation` | 10 |
| `appointment_max_years_ahead` | 2 |
| `appointment_reminder_days_before`, `appointment_follow_up_days_after` | 1 and 1 (question 9) |
| `appointment_reminder_hour_utc` | 18 (1pm Eastern, 8am Hawaii; question 8) |
| Caps on Oracle output | 4,000 characters per paragraph, 500 per line, 20 items per list (`service.py`) |

## New open questions for the BA

- **Products after an emergency:** recommendations are hidden only while a hold is open (3.3's "during an active emergency"). Should they also stay out of a conversation that had an emergency or crisis earlier, after "I’m safe now"?
- **Follow-up during the trial:** 3.3 lists the two-week check-in under "Subscribed Client". Should trial clients get it (built: yes)?
- **Product note:** added only when a Genesis product is recommended, because its text names Genesis Gold®. Is it wanted for partner products and medicines too?
- **Family members:** 3.4's "What this is" says "my symptoms" even when the advocate prepares notes for someone else. Is there family wording?
- **File name date:** the appointment date or the day the notes were made (3.5's and 5.1's examples differ)?
- **Grammar:** "a [specialty] would be a good place to start" needs a provider ("a cardiologist") rather than the label, so each specialty in the settings has one. Is that right?
- **My Visit Notes during the trial:** 5.1 greys out the list, but these lists aren't locked, because the conversation-level views must work. Phase 6 should lock its combined list.

## For the migration (autogenerate misses these)

Nothing to add by hand: three new tables (`guidance_summaries`, `provider_notes`, `provider_note_versions`), whose check constraints, unique constraints and indexes are all on the new tables, so autogenerate writes them. No changes to existing tables, no seed rows, no data changes, no triggers.

## Left for others

- **Notifications (12.1):** `app/notifications/targets.py` needs the `provider_note` lookup, so the appointment reminders show [specialty] and are skipped for a deleted conversation's notes. Until then they show the generic text (deleted conversations' reminders are cancelled anyway). The lookup:

  ```python
  def _provider_note(db, target_id, profile_id):
      from app.guidance.models import ProviderNote
      from app.guidance.specialties import label

      note = db.get(ProviderNote, target_id)
      conversation = note and db.get(Conversation, note.conversation_id)
      if note is None or note.profile_id != profile_id or conversation.deleted_at is not None:
          return Target(exists=False)
      return Target(exists=True, details={"specialty": label(note.specialty, note.specialty_other)})
  ```

- **Phase 4:** the "Save to my profile" checklist, and the health profile in `ProfileContext` (medications for the notes).
- **Phase 6:** My Visit Notes can be built from the two list endpoints. "Log this visit" from a past date goes there.
- **Phase 7:** recommendations to the top of the Wellness Plan, and the Wellness Protocols links (`protocol`).
- **Phase 3b:** the teen's own-account download path, through `feature_access`.
- **Before production:** embed a Unicode font in the PDFs; encrypt `content` with the other health fields (Phase 4).
- **Tests** for all of the above.
