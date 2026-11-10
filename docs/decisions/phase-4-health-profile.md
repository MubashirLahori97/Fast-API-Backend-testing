# Phase 4 Health profile (6.1): decisions

Story "View, Edit & Complete Health Profile" (6.1), with the body follow-up parts of "Start or Continue a Conversation" (3.1: Path A, Path B, gender Prefer not to say) and the "Trans intake questions" tab of `docs/requirements/source/user-stories-export.md`. Built 2026-11-05. No tests or migration yet (see the end).

## What was built

| Piece | Where |
| --- | --- |
| The question bank: 10 sections, 71 questions, the body routing rules | `app/health/questions.json` |
| Loading and checking the bank; the rule language | `app/health/bank.py` |
| Which sections and questions apply; the follow-up path; the body route; completion | `app/health/routing.py` |
| Checking each kind of answer, filling in names and pronouns, answers in words | `app/health/values.py` |
| `health_profiles`, `health_answers`, `health_facts` | `app/health/models.py` |
| My Health, About you edits, facts, `health_context`, `open_questions`, `propose_fact` | `app/health/service.py` |
| Review reminders | `app/health/reminders.py` |
| Endpoints | `app/health/router.py` |
| Hooks: reminders start when an intake is completed; Manage Family cards show the completion | `app/profiles/service.py` (`complete_intake`, `family_member_out`) |
| `HEALTH_FACT` widget kind | `app/oracle/contract.py` |

## Endpoints

All behind the policy gate, and all take `UsableProfile` (`OwnedProfile`'s 404 for another account's or an unknown id, plus 409 for an unfinished, turned-off or deletion-requested profile).

- `GET /profiles/{id}/health-profile`: the sections and questions that apply, each with its answer (or null: "Not answered yet" / Add), the completion and `complete`, About you, the privacy notice on the follow-up section, and the remove confirmation text.
- `PATCH /profiles/{id}/health-profile`: `{"about_you": {...}, "answers": {"key": {"value", "other"} | null}, "remove_sections": [...]}`. Answers `{health_profile, message, celebration}`.
- `GET /profiles/{id}/health-facts?conversation_id=`: pending facts.
- `PATCH /profiles/{id}/health-facts/{fact_id}`: edits a pending fact's value.
- `POST /profiles/{id}/health-facts/{fact_id}/confirm` (optional body: an edited value): saves it as the answer.
- `POST /profiles/{id}/health-facts/{fact_id}/discard`.

## Design choices

### The question bank

- **Data, not code.** `questions.json` holds every section and question: `key`, `section`, `kind`, `title` and `title_family`, the choices, `optional`, `sensitive`, `show_if`, and per-kind settings (write-in, min and max, item labels). `settings.health_question_bank_path` can point at a replacement file, so the routing document's rule set can replace it without a code change. The file is checked when the app starts (`bank.py`); a broken one stops the API.
- **Kinds:** `choice`, `multi_choice`, `text`, `number`, `date`, `scale`, plus two the story needs: `checklist` (symptoms, where each item can be ticked or marked N/A) and `named_list` (medicines, supplements and allergies, each with a name and a detail; `[]` means "None").
- **Rules** (`show_if`, on sections and questions), like the prototype's `showIf`: `in`, `not_in`, `has`, `lacks`, `min`, `max`, `answered`, and a top-level `any` for "either". A rule may use derived values (`age_group`, `age`, `sex_at_birth`, `gender_identity`, `path`, and after the "Your body" question `body` and `body_route`) and earlier questions' answers. The loader refuses a rule that names a later question, so there are no loops. Section rules use only the derived values that don't depend on answers.
- **Order matters.** Questions are worked through in the file's order, and each sees only the answers of earlier questions that apply. Answers that depend on each other can be sent in the same save.
- **Wording is a placeholder,** taken from the stories, the Trans intake tab and the design team's prototype, until the routing document and the Oracle's clinical review replace it (`"status": "placeholder"`).

### Paths and body routing

- **The follow-up path** (`routing.follow_up_path`):
    - Path A, sex at birth Intersex or Prefer not to say, comes first, whatever the gender;
    - then gender Prefer not to say (with sex at birth Male or Female);
    - then Path B, any gender that differs from sex at birth. **Non-binary, Agender and Not listed count as differing** (question 23), so they get Path B;
    - otherwise none: Man with Male, Woman with Female.
- **Path A:** intersex variation (with its name if Yes, optional) → "Your body" → hormone history (pre-filled from the HRT answer) → surgery history.
- **Path B:** "Your body" → puberty → gender-affirming hormones → provider → context, then the version for sex at birth: hormones, how taken and how long (only when hormones are Currently or In the past), surgeries, and for female at birth periods when the body has a uterus. The provider question is hidden only when hormones are Never.
- **Teens:** Path B teens get only "Your body", puberty, hormones and provider (the stories and the Trans tab). Path A teens don't get surgery history either, following the Trans tab's "No surgery questions" for teens (new question 2).
- **Under 13:** no follow-up body questions and no body and hormones section (3.1: no reproductive or puberty questions for children). New question 1.
- **Gender Prefer not to say:** "Your body" only, then the standard questions for the body.
- **"Your body"** sets `body`, the organs. Uterus, cervix or ovaries route to the female questions, testes or a prostate to the male ones, both to the intersex ones (the prototype's rule, in `questions.json`'s `body` block). When it's skipped, or answered "None of these" or "Prefer not to say", the organs are assumed from sex at birth (female: uterus, cervix, ovaries, vagina, breast tissue; male: testes, prostate, penis), so body questions follow sex at birth, as 6.1's alternate scenario says. Sex at birth Prefer not to say with "Your body" skipped gets general questions only (`body_route` `general`), as 3.1 says.
- **Screenings follow the body:** Pap smear with a cervix, mammogram with breast tissue from 40, prostate check with a prostate from 45, colon screening from 45, bone density for a female body at 60 and over.

### Answers and changes

- **Answers that stop applying are kept, not shown.** After a change (a new reproductive status, a new "Your body" answer, a new gender), the questions that now apply appear and the others are hidden. A hidden answer is kept, but isn't shown, counted, used by later rules or given to the Oracle; it comes back if the question applies again. `remove_sections` deletes a section's answers including hidden ones, so a client can still delete sensitive answers they can no longer see.
- **Any answer can be removed** (null, or an empty text), not only optional sensitive ones: it's the client's data, and the story's confirmation text fits every answer. The app shows `remove_confirmation` first.
- **A save is all or nothing.** Every refused answer is listed in `details`, with the first one's message on top.
- **An answer to a question that doesn't apply** (an app showing an old form) is refused with 422 `not_applicable`.
- **Each answer records its source:** `client`, or `conversation` with the conversation's id (set to null if that conversation is purged). Editing an answer in My Health makes it `client`.
- **About you:** for the client's own profile and family members alike, only gender identity and pronouns (and their write-ins) can change, with 8.2's write-in rules. A different date of birth or sex at birth gets 6.1's read-only message (8.2's, with the name, for a family member). Changing the gender re-routes the follow-ups in the same save. For family members, 8.2's `PATCH /profiles/{id}` still works too.
- **Names and pronouns are filled in by the backend** ("Has Azka started her periods?"), unlike `GET /profiles/options`, whose labels the app fills: this endpoint is per profile. He/Him and She/Her get his/him and her; any other pronouns get their/them.
- **Drafts:** the server saves on Save (a section) or on each step (Complete my profile). The draft while editing (6.1's non-functional requirement) and the offline queue are the app's.

### Completion

- `completion` = answered counted questions that apply × 100 ÷ counted questions that apply, **rounded down**, so 100 means everything is answered. Counted = not `optional` and not `sensitive`. The main wellness goal is optional. About you (answered at onboarding) isn't counted. A profile with no counted questions is 100.
- The celebration ("That’s everything I need. Thank you for taking the time.") is returned by the save or fact confirmation that takes the profile from below 100 to 100.
- **Age changes** need nothing extra: the questions follow the profile's age group on the day (Hawaii's date, `app/core/ages.py`), so a managed teen's adult questions appear at the age of majority and the completion drops. The "Complete your health profile" widget (4.1) is the invitation; no notification is scheduled for it.

### Free trial

- My Health (`GET` and `PATCH .../health-profile`) is refused while `entitlements.feature_access(account)["my_health"]` is locked (the trial, or an ended subscription), with 6.1's own "My Health is part of your plan. Choose a plan to unlock it." and billing's code `upgrade_required`.
- **The facts endpoints aren't locked:** saving what the Oracle learned is part of the conversation (3.1), which the trial includes. The answers are there when the client subscribes. New question 3.

### Facts from conversations

- `propose_fact(db, profile, account, question_key, value, other, conversation_id)` saves a pending fact and doesn't commit. It returns None and saves nothing for an unknown question, a value the question doesn't take, a question that doesn't apply, or the answer already saved. The Oracle's output is untrusted, so it's checked like the app's.
- **One pending fact per question and profile:** a newer proposal replaces the older one (a partial unique index and `INSERT ... ON CONFLICT`).
- **Confirm** checks the value again (the rules or the profile may have changed) and saves it with source `conversation`. Confirming again changes nothing. Confirming a discarded one is refused.
- **Discard** clears the value: the client said not to keep it. Discarding again changes nothing; discarding a saved one is refused (change it in My Health).
- **Contract:** `HEALTH_FACT = "health_fact"` in `app/oracle/contract.py` describes the widget the Oracle sends with "Would you like me to add this to your health profile?". The conversations package still has to call `propose_fact` for it and send `{"kind": "health_fact", "fact_id", "question_key"}` in its place (see "For other packages").

### The Oracle's context

- `health_context(db, profile, account)`: the answered questions that apply, in the bank's order, each with its key, section, question worded for the profile, the answer in words, the stored value, whether it's sensitive, whether it came from a conversation, and when it was updated (so the Oracle can confirm an old answer instead of asking again). Removed and hidden answers are left out, so "the Oracle stops using it" (6.1). About you is already in `ProfileContext`.
- `open_questions(db, profile, account)`: the questions that apply and aren't answered, with their codes, so the Oracle can ask them when relevant and propose facts that fit.

### Audit, locks, PHI

- **Audit:** `health_profile.updated` (target the profile, actor the account) with `source` (`client` or `conversation`), `answers_saved`, `answers_removed`, and the About you field names changed. Never the question keys or values: a key such as `afab_hormones` alone tells which body questions a person gets.
- **Locks:** saves and confirmations lock the profile row (`FOR UPDATE`) first, then the fact; edit and discard lock the fact only.
- **Saving failed:** any database error gives 503 `save_failed` with 6.1's message, without the database's text.
- **Encryption:** not done. `health_answers.answer` and `health_facts.answer` are JSONB in plain text, like the other health fields, until the Phase 4 field encryption (it needs `cryptography`, a key setting and key management, outside this task). Nothing queries inside them, so encrypting them later changes no query.

### Reminders

- `reminders.record_update(db, account, profile)` runs after every change to the health profile and when an intake is completed: it sets `health_profiles.updated_at`, cancels the profile's waiting `health_profile_review` reminders and schedules new ones `settings.health_profile_review_months` (3, 6, 12) months later, through `app.notifications.service.schedule`, with `data={"time": "3 months"}` and so on.
- `reminders.visit_logged(db, account, profile)` is for Phase 6 (5.2): it sends `health_profile_review_after_visit` straight away and doesn't move the 3, 6 and 12 month reminders.
- `service.last_updated_at(db, profile)` is for 4.1's "Update your health profile" widget (Phase 11).
- `health_profile_incomplete` isn't scheduled: its timing is open (question 9).

## Stored codes

| What | Codes |
| --- | --- |
| Kinds | `choice`, `multi_choice`, `checklist`, `text`, `number`, `scale`, `date`, `named_list` |
| Sections | `about_you`, `body_follow_ups`, `body_and_hormones`, `medications`, `lifestyle`, `symptoms`, `health_checks`, `medical_history`, `teen`, `child` |
| Follow-up path (derived) | `a`, `b`, `gender_prefer_not_to_say`, `none` |
| Body route (derived) | `female`, `male`, `intersex`, `general` |
| Organs ("Your body") | `uterus`, `cervix`, `ovaries`, `vagina`, `testes`, `prostate`, `penis`, `micropenis_macroclitoris`, `breast_tissue`, `none`, `prefer_not_to_say` |
| `health_answers.source` | `client`, `conversation` |
| `health_facts.status` | `pending`, `confirmed`, `discarded` |
| Stored answer | `{"value": ..., "other": "..."}`; checklist value `{"selected": [...], "not_applicable": [...]}`; named_list value `[{"name", "detail"}]`; date `"YYYY-MM-DD"` |
| Audit action | `health_profile.updated` |

Question keys and their choice codes are in `questions.json`.

## Messages from the stories

- Trial: "My Health is part of your plan. Choose a plan to unlock it." (6.1), not 9.1's general "This is part of your plan...".
- Read-only: "Your date of birth and sex assigned at birth can’t be changed here. If something is wrong, please contact the support team." (6.1); for a family member, 8.2's "[Name]’s date of birth...".
- Write-ins: "Tell me in your own words how you identify." / "Tell me which pronouns you’d like me to use." (6.1); for a family member, 8.2's "...how [Name] identifies." / "...for [Name]."
- "Please add the name of the medication or supplement." (medications and supplements); "That number doesn’t look quite right. Could you check it for me?" (numbers and scales); "Remove this answer? I won’t use it in your guidance any more." (`remove_confirmation`); "Thanks, I’ve updated your health profile."; "That’s everything I need. Thank you for taking the time."; "We couldn’t save your changes just now. Please try again."
- An unknown choice code: "Please choose an option to continue." (2.1's, reused).
- The privacy notice is R3's placeholder (`PRIVACY_NOTICE_TEXT` in `app/conversations/widgets.py`), until the attorney's text.
- "Leaving without saving" and "Offline" are the app's.

## Messages not in the stories

| Message | Situation | Code |
| --- | --- | --- |
| "That date doesn’t look quite right. Could you check it for me?" | A date that isn't one, is in the future or is before the date of birth | `invalid_date` |
| "Please add the name of the allergy." | An allergy without a name | `name_required` |
| "Tell me a little more in your own words." | A required write-in left empty (none of the current questions requires one) | `write_in_required` |
| "“[Label]” can’t be chosen with other answers." | "None of these", "Prefer not to say" or "I’m not sure" chosen with other options | `exclusive_choice` |
| "Please keep this list to [N] items or fewer." | More than `health_list_max_items` medicines, supplements or allergies | `too_many` |
| "Please keep this to [N] characters or fewer." (the existing wording) | A text, write-in or name too long | `too_long` |
| "Please check this answer and try again." | An answer in the wrong shape (an app bug) | `invalid_answer` |
| "We couldn’t find that question. Please refresh and try again." | An unknown question key (an older app) | `unknown_question` |
| "We couldn’t find that section. Please refresh and try again." | An unknown section in `remove_sections` | `unknown_section` |
| "This question doesn’t apply to this profile." | An answer, or a fact to confirm, for a question that doesn't apply | `not_applicable` |
| "We couldn’t find that health detail." | An unknown fact, or another profile's | `health_fact_not_found` |
| "This was already dismissed, so it can’t be saved." | Confirming or editing a discarded fact | `health_fact_discarded` |
| "This is already saved to the health profile. You can change it in My Health." | Editing or discarding a confirmed fact | `health_fact_saved` |
| Section titles: "About you", "More about your body", "Body and hormones", "Medications, supplements and allergies", "Lifestyle", "Symptoms", "Health checks", "Medical history", "Home, school and wellbeing", "Birth, growth and school" | My Health's headings (6.1 names the sections, not their titles) | |
| Every question title and label not in 3.1, 6.1 or the Trans tab | `questions.json`, placeholders | |

## Assumed values

| Value | Assumed | Where |
| --- | --- | --- |
| Typed answer, write-in or detail | 1,000 characters | `settings.health_text_max_length` |
| Medicine, supplement or allergy name | 100 characters | `settings.name_max_length` |
| Items in one list | 30 | `settings.health_list_max_items` |
| Review reminders | 3, 6 and 12 months after the last update (the stories) | `settings.health_profile_review_months` |
| Age at first period, start of puberty | 6 to 25, and not above the current age | `questions.json` |
| Age at last period | 20 to 70, and not above the current age | `questions.json` |
| Sleep | 0 to 24 hours a night | `questions.json` |
| Screening ages | mammogram 40, prostate and colon 45, bone density 60 | `questions.json` |

## For the migration (autogenerate misses nothing here)

- Three new tables, which autogenerate finds with their check constraints, the unique constraint and the partial unique index `uq_health_facts_one_pending_per_question` (`WHERE status = 'pending'`):
    - `health_profiles` (`profile_id` primary key and FK to `profiles`, CASCADE; `updated_at`, `created_at`);
    - `health_answers` (FK to `profiles` CASCADE and to `conversations` SET NULL; unique `(profile_id, question_key)`; `ck_health_answers_source`, `ck_health_answers_conversation_source`);
    - `health_facts` (the same FKs; `ck_health_facts_status`, `ck_health_facts_resolved`, `ck_health_facts_answer`).
- No change to an existing table, no trigger, no seed rows.
- Optional data step: `INSERT INTO health_profiles (profile_id, updated_at) SELECT id, intake_completed_at FROM profiles WHERE intake_completed_at IS NOT NULL`, so profiles finished before Phase 4 have a last update for 4.1. Their review reminders start at their next change; scheduling them in the migration would mean writing `jobs` rows by hand, which isn't worth it for dev data.

## For other packages

- **Conversations:** pass `health_context(...)` to the Oracle with `ProfileContext` (a new contract field, the AI team's call), and `open_questions(...)` if the AI team wants them. Handle the `health_fact` widget in `widgets.py`: call `propose_fact` with the conversation's id, replace the widget with `{"kind": "health_fact", "fact_id": ..., "question_key": ...}`, and drop it when `propose_fact` returns None. Chat-ticked symptoms (question 29) can be proposed the same way, as `symptoms_general` and the other checklist keys.
- **Phase 6 (5.2):** call `reminders.visit_logged(db, account, profile)` when a visit is logged.
- **Phase 11 (4.1):** `service.completion(db, profile)` for "Complete your health profile", `service.last_updated_at(db, profile)` for "Update your health profile", and `service.check_my_health_unlocked`.
- **Phase 3b:** a teen with their own account has their own profile on their own account, so `OwnedProfile` already keeps the parent out. Their access follows the parent's Family plan (`entitlements.feature_access` says so too).
- **Phase 10:** the export includes `health_answers` (hidden ones too) and confirmed facts; the purges delete them with the profile (CASCADE).
- **Field encryption:** `health_answers.answer` and `health_facts.answer`, with the other fields listed in `docs/PLAN.md`.

## Answers to the plan's questions (our choices until the BA replies)

- **Question 1 (routing rule set):** built as `questions.json`, which the routing document replaces; the routing in it follows 3.1, 6.1 and the Trans tab.
- **Question 23:** Non-binary, Agender and Not listed follow Path B. Girl and Boy stay labels. Option codes are the stable part; labels, order and new questions can change in the bank without an app release, but new codes need the backend's file to change too (not an app release).
- **Question 29:** symptoms are structured checklists (`checklist`, with N/A) that follow the body. The backend serves the My Health lists; the Hypothalamus Symptom Check in chat stays the conversations package's. Ticked symptoms are saved only when the client confirms them as a fact.

## New open questions for the BA

1. **Children and the body follow-ups:** an under-13 profile gets no follow-up body questions and no body and hormones section (3.1's "no reproductive or puberty questions"). Should an intersex child's advocate be asked the intersex variation and "Your body"?
2. **Path A teens:** we left out surgery history, following the Trans tab's "No surgery questions" for teens. Should they get it?
3. **Trial and saving from chat:** My Health is greyed out during the trial, but confirming "Would you like me to add this to your health profile?" in a conversation works. Is that right, or should the Oracle not offer to save during the trial?
4. **Answers that stop applying** are kept and hidden (and come back if they apply again). Should the client be told they exist, or should they be deleted after a while?
5. **Health checks:** dates for the last physical and bloodwork, but "In the last year / 1–3 years ago / ..." for screenings, since few people know those dates. Is that the right mix, and which screenings and ages does the routing document want?
6. **About you:** is the client's own About you counted in the completion percentage? We don't count it (it's answered at onboarding).
