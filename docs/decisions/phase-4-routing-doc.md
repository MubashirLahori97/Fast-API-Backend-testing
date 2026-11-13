# Phase 4 update: the question bank rebuilt to the Health Intake Routing document

Rebuilds `app/health/questions.json` and the routing code to the BA's Health Intake Routing document, third tab "Revised Intake Routing": Part 1's routing rules and Deborah's decisions 1–45, Part 2's questions by body and age, and Part 3's appendix (answer type, "Shown when", "When asked"). Earlier tabs are superseded. Built 2026-11-11, on top of `phase-4-health-profile.md` and `conversations-health-1922.md`. No tests, no migration, no commits (the build rules).

## What changed

| Piece | Where |
| --- | --- |
| The bank: 11 sections, 184 questions (was 10 and 71), version `2026-11-11`, status `routing-document` | `app/health/questions.json` |
| New bank fields: `when_asked`, `conversation_if`, `variants`, choice `show_if`, section `intro`, prefill to several codes with a `note`, kinds `time` and `history`, `body.none` | `app/health/bank.py` |
| Derived values `teen_own_login` and `body_ticked`; "None of these" routing; variants, columns, visible choices, `hidden_choice` | `app/health/routing.py` |
| `time` and `history` answers; titles follow variants | `app/health/values.py` |
| `QuestionOut.when_asked`, `columns`, `prefill_note`; `SectionOut.intro` | `app/health/schemas.py` |
| Teen own login from `users.account_type`; prefill from a multi-choice HRT type; hidden choices refused; `oracle_view`; `open_questions` keeps only what the Oracle may ask in conversation | `app/health/service.py` |
| Circle Map placeholder moved to the new checklist codes ("Breast tenderness" dropped: no checklist has it now) | `app/health/circle_map.json` |
| `HealthQuestion.when_asked`; `HealthContext.follow_up_path`, `body_route`, `organs`, `body_from_your_body`, `opening_line` (all with defaults) | `app/oracle/contract.py` |
| `health_context` fills those from one `oracle_view` read | `app/conversations/service.py` |
| "test health route" replies with the path, body route and next question it would ask | `app/oracle/fake.py` |

No endpoint was added. `GET` and `PATCH /profiles/{id}/health-profile` return the new fields. No model, setting or migration change.

## Design choices

### Routing

- **Paths are unchanged:** A (sex at birth Intersex or Prefer not to say), B (gender differs; Non-binary, Agender and Not listed included, decision 41), gender Prefer not to say, none.
- **The follow-ups at every age (decisions 15, 24, 25):** under-13s get Path A in full, answered by the advocate. Path B under-13s get "Your body" only. Path B's puberty, hormones and provider questions start at 13. Path A surgery history is asked at every age. The old "no follow-ups under 13" rule and its open questions 1 and 2 are gone.
- **"Your body" is offered to every profile in My Health** (decision 42). `conversation_if` keeps it out of `open_questions`, so the Oracle asks it in conversation only for Path A, Path B and gender Prefer not to say (decision 35). The follow-up section and its privacy notice show for everyone, because "Your body" is in it.
- **Body route:** a uterus or ovaries mean the female questions, testes or a prostate the male ones, both mean the intersex ones. A cervix alone no longer routes (Part 2: "uterus or ovaries"). "None of these" is a real answer: no organs, so general questions only, and no screenings by organ. "Prefer not to say" counts as skipped, so sex at birth decides (decision 12). With "Your body" skipped, Intersex at birth routes as intersex and Prefer not to say as general (decision 13).
- **`body_ticked`** holds only the ticked organs. `afab_periods` uses it ("Uterus" actually ticked). Screenings use `body`, which falls back to sex at birth ("Has a cervix (or female at birth)").
- **The intersex period gates:** "Do you have periods?" (18–59) and "Have you ever had periods?" (60+) are asked when sex at birth is Intersex and the route is female, or when both kinds of organs are ticked. "Which best describes you now?" and HRT follow a Yes. Teens get "Have your periods started?".
- **Hormone provider (Path B)** shows only for hormones Currently or In the past. Before, any answer but Never showed it.
- **Teens' sexual health** (`teen_sexuality_concerns`, `teen_contraception`) shows only when `teen_own_login` is "yes": the profile is the account's own, and `users.account_type` is `teen` (decision 43). `teen_puberty_blockers` is dropped; Path B's puberty and hormones questions cover blockers (decision 4).
- **Age limits:** "18+" in the document means the `adult` and `60_plus` age groups, so it follows the age of majority in `app/core/ages.py`, which wasn't changed.

### The document's questions

- **Path A, structured:** hormone history (Yes / No) → which ones (multi-select, pre-filled) → "How are they taken, and for how long?" (text: Part 3's "Select + text") → provider → context. Surgery history (Yes / No) → which ones (Part 3's 9 items) → context, which shows once the surgery question is answered.
- **Prefill:** `hormone_history` is pre-filled Yes from HRT Yes or Yes, previously. `hormone_history_which` is pre-filled from `hrt_type`: Estrogen only → Estrogen; Progesterone only → Progesterone; Combined → both; Testosterone → Testosterone. Bio-identical, Synthetic and write-ins name no hormone, so they aren't mapped. Both come with `prefill_note` "We’ve filled this in from your HRT answers. Edit if needed."
- **Path B's opening line** (decision 33) is `SectionOut.intro` on the follow-up section and `HealthContext.opening_line`, for Path B only.
- **`hrt_type` is multi-select:** Bio-identical and Synthetic can go with a hormone ("Combined" and "Bio-identical"). `ovaries_removed` is Yes / No / Partial. "Post-menopausal (natural)" keeps the code `post_menopausal`, and "Having periods" is gone. Teens see only Pre-menopausal and Pregnant or postpartum (choice `show_if`; any other choice is refused with "Please choose an option to continue.").
- **Male teens:** puberty Yes / No, then the age (codes `age_8` … `age_17`, `not_sure`), then optional details.
- **Sex at birth not given, "Your body" skipped** (general route): puberty age (teens, choice; adults, number) and "Do you have any concerns about your development?" (optional). The general route also covers "None of these".
- **Fertility for 60+ (male route)** is asked later, through a variant. Intersex 60+ get no fertility questions ("without the periods and fertility questions").
- **Symptoms:** the Hypothalamus Symptom Check as `symptom_check` (everyone, `conversation`, optional), plus the female (21) and male (19) checklists with Yes / No / N/A for adults by body. Menstrual cramps severity is a 1–10 scale after the cramps item.
- **Health checks:** dates for every adult, following `body`, with no age minimums. Colon screening, bone density and "vaccinations up to date" are removed. Occupation is asked from 13.
- **Medical history** is one `history` question (17 items, plus 3 for a female body), with Self and Family columns. Teens and children get Family only, through a variant. A ticked item can carry a short note.
- **Medicines:** `medications` stays one key for every age (5.2's visit updates rely on it), worded "Is the child taking any medications, herbs or supplements?" for under-13s. `supplements` is for 13 and over. `allergies` is now text, asked first for children.
- **Teen and child lists** follow Part 3's tables. A "x 3" row became separate questions (for example three Yes / No safety questions).

### `when_asked`

Each question has Part 3's value: `asked_first`, `asked_later`, `conversation` (every follow-up) or `onboarding` (unused here). Variants change it by age, for example the 60+ "age at last period" and fertility questions are `asked_later`. My Health gets it in `QuestionOut.when_asked`, and the Oracle in `HealthQuestion.when_asked`.

## Contradictions (newest or most specific text followed)

1. **Decision 4 vs 43 (teen sexual health):** decision 4 says the parent answers; decision 43 (Intake Spec v1.2) says only teens with their own login are asked. Followed 43. 6.1's acceptance criterion "including sexual health and puberty blocker questions" for every teen profile is out of date too.
2. **Part 2 vs Part 3, family member onboarding order:** Part 2 puts advocate consent before the date of birth, Part 3 after it. Followed Part 3. This is the profiles package's onboarding, so nothing changed here.
3. **Decision 29 (teen accounts):** it says no Wellness Plan or provider notes, then "Updated: teens also get..." Followed the update. Nothing in the bank depends on it.
4. **6.1 vs decision 42:** 6.1 shows the follow-up sections only for Path A, Path B and gender Prefer not to say. Decision 42 offers "Your body" to every client in My Health. Followed 42.
5. **Contraception** appears three times in Part 3 (periods table, fertility table, health checks). It's one question here (`contraception`, adults).
6. **Reproductive history at 60+:** Part 2's 60+ female list leaves out pregnancies and contraception; Part 3 says "Age 18+". Followed Part 3.
7. **"Age at last period" at 60+:** Part 3 shows it only after "Post-menopausal (natural)", but Part 2 asks it later at 60+, where the status question is skipped. Both are kept.
8. **Under 13, "no puberty questions" vs Path A hormone history for children:** followed Part 1, where the follow-ups still apply, answered by the advocate.

## Assumed values and wording (not in the document)

| What | Assumed |
| --- | --- |
| Path A "which hormones" choices | Estrogen, Progesterone, Testosterone, Anti-androgen, Puberty blockers, Other (write-in) |
| Intersex variation name write-in | "If you know the name of the intersex variation, you can add it here." (the document says "your", wrong for an advocate); the teen version has it too |
| `amab_hormone_method` | single choice (Part 3 marks only "Which hormones" and surgeries as multi-select) |
| Fertility factor | Male factor / Female factor |
| Breast or bottle fed | Breast / Bottle / Both |
| Milestone ages; age weaned | months (0–156; 0–60) |
| Same-sex parent's adult height | inches, 36–96 |
| Daily fluids | oz, 0–500 (teen) and 0–300 (child) |
| GPA | 0–5 |
| Cycle length; bleeding days; pads or tampons | 7–180 days; 1–30; 0–50 |
| Other number ranges | age at surgery 1–100; stopped growing 8–30; mother's menopause 20–70; pregnancies etc. 0–30; providers seen 0–100 |
| Optional (not counted) | `symptom_check`, `contraception` and `teen_drink_drive` (only if sexually active or driving), `anything_else`, the free-text details questions |
| Section titles | "Goals", "Home, growth and daily life" (children) |
| Messages | "That time doesn’t look quite right. Could you check it for me?" (`invalid_time`) |
| Other immunisations | one text, "Any other immunisations, and when?" |

## New open questions for the BA

1. Should "Your body" also be offered to under-13s outside Path A and Path B (decision 42 says "every client")? We offer it to every profile.
2. Is `hrt_type` multi-select? We assumed yes, because Bio-identical and Synthetic describe a hormone rather than replace it.
3. Should the female route include a cervix alone? Part 2 says uterus or ovaries.
4. Teen intersex wording ("I don’t understand the question"): use it for a parent-managed teen too? We do.
5. Should the Hypothalamus Symptom Check be counted in completion? We treat it as optional.

## Data step for the migration (dev data only; deletes, never edits)

Deletes `health_answers` rows that the new bank can't use: unknown keys, and kept keys whose stored value no longer fits. Nothing else is touched. `health_facts` needs nothing: only `medications` and `supplements` facts exist, and their shape is unchanged.

```sql
-- 1. Keys removed from the bank (26).
DELETE FROM health_answers WHERE question_key IN (
  'bone_density','child_birth','child_growth','child_milestones','child_safety',
  'colon_screening','conditions','cycle_regularity','diet','exercise','family_history',
  'growth_concerns','hormone_history_details','sleep_quality','support','symptoms_cycle',
  'symptoms_general','teen_home','teen_puberty_blockers','teen_safety','teen_school',
  'teen_sexual_health','teen_wellbeing','teen_worries','vaccinations','work');

-- 2. Kept keys whose kind changed.
DELETE FROM health_answers WHERE question_key IN ('allergies')
  AND jsonb_typeof(answer->'value') <> 'string';                     -- named_list -> text
DELETE FROM health_answers WHERE question_key IN ('amab_hormone_method','surgery_history')
  AND jsonb_typeof(answer->'value') <> 'string';                     -- multi -> single choice
DELETE FROM health_answers WHERE question_key = 'hrt_type'
  AND jsonb_typeof(answer->'value') <> 'array';                      -- single -> multi choice
DELETE FROM health_answers WHERE question_key IN ('pap_smear','mammogram','prostate_screening')
  AND answer->>'value' !~ '^\d{4}-\d{2}-\d{2}$';                     -- ranges -> dates
DELETE FROM health_answers WHERE question_key = 'child_school'
  AND answer->>'value' IN ('well','okay','hard','not_started');      -- choice -> text

-- 3. Kept keys whose codes changed.
DELETE FROM health_answers WHERE question_key = 'hormone_history'
  AND answer->>'value' NOT IN ('yes','no');
DELETE FROM health_answers WHERE question_key = 'ovaries_removed'
  AND answer->>'value' NOT IN ('yes','no','partial');
DELETE FROM health_answers WHERE question_key = 'periods_started'
  AND answer->>'value' NOT IN ('yes','no','describe');
DELETE FROM health_answers WHERE question_key = 'puberty_started'
  AND answer->>'value' NOT IN ('yes','no');
DELETE FROM health_answers WHERE question_key = 'reproductive_status'
  AND answer->>'value' = 'menstruating';
DELETE FROM health_answers h WHERE h.question_key = 'symptoms_female' AND EXISTS (
  SELECT 1 FROM jsonb_array_elements_text(
    coalesce(h.answer->'value'->'selected','[]') || coalesce(h.answer->'value'->'not_applicable','[]')) c
  WHERE c NOT IN ('hot_flashes','night_sweats','brain_fog','forgetfulness','mood_swings',
    'irritability','depression','rage','vaginal_dryness','poor_lubrication','urinary_urgency',
    'low_libido','clamminess','fatigue','insomnia','muscle_weakness','body_fat_change',
    'lower_exercise_tolerance','lower_stress_tolerance','illness_susceptibility','menstrual_cramps'));
DELETE FROM health_answers h WHERE h.question_key = 'symptoms_male' AND EXISTS (
  SELECT 1 FROM jsonb_array_elements_text(
    coalesce(h.answer->'value'->'selected','[]') || coalesce(h.answer->'value'->'not_applicable','[]')) c
  WHERE c NOT IN ('hot_flashes','night_sweats','mood_swings','irritability','depression','rage',
    'mental_fogginess','forgetfulness','clamminess','body_fat_change','muscle_weakness','fatigue',
    'lower_exercise_tolerance','illness_susceptibility','lower_stress_tolerance','insomnia',
    'low_sex_drive','fewer_morning_erections','reduced_erectile_firmness'));
```

Every other kept key (for example `your_body`, `medications`, `hrt_status`, `stress`, the Path B questions) keeps its codes and shape, so its rows stay. The migration's downgrade can't bring the rows back; that's acceptable for dev data.
