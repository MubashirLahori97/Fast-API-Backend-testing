# R2 Profiles and family: decisions

Phase R item R2 in `docs/PLAN.md`, built 2026-11-05 against the 4 Nov stories: "Onboarding (Myself)" (2.1), "Onboarding (Family Member)" (2.2), "Switch Profiles - Global Profile Toggle" (4.2), "Add Family Member" (8.1), "Manage Family Profiles" (8.2), and the plan names and places from "Start Free Trial & Activate Subscription" (9.1). Story numbers below are the 4 Nov ones.

## What changed

- **Self intake:** asks sex at birth, gender and pronouns only (`SELF_QUESTIONS`). The date of birth is copied from `users.date_of_birth` when the self profile is created (`_create_profile`), and the intake can't change it. The R1 bridge (`date_of_birth_mismatch`) and the under-13 refusal for the self profile are gone, along with the `profile.under_13_refused` audit event.
- **Teen step:** a family member aged 13 to 17 is asked `teen_profile_choice` straight after the date of birth (new column `profiles.teen_profile_choice`). Children under 13 and adults skip it.
- **Plans:** `users.subscription_plan` is `individual` or `family` (null is the free trial). Only `family` has places: `settings.family_members_included` (3).
- **Options from the backend:** `GET /profiles/options`, served from `app/profiles/options.py`, which is also where the schemas' allowed codes come from.
- **Wording:** every intake, limit and upgrade message now uses the 4 Nov text (listed below).

## Stored codes

All in `app/profiles/options.py`, in the stories' order.

| Question | Codes |
| --- | --- |
| Relationship | `parent`, `child`, `partner`, `someone_else` (unchanged) |
| Teen Profile Choice | `own_account` (refused until Phase 3b), `managed` |
| Advocate consent | `agreed`, `parent_or_guardian`, `authorised_to_act` (unchanged) |
| Sex at birth | `male`, `female`, `intersex`, `prefer_not_to_say` |
| Gender | `woman`, `man`, `non_binary`, `agender`, `not_listed` (write-in in `gender_identity_other`), `prefer_not_to_say` |
| Pronouns | `he_him`, `she_her`, `they_them`, `other` (write-in in `pronouns_other`) (unchanged) |
| Plan | `individual`, `family` (null: free trial) |

Girl and Boy (under 13) are labels for `woman` and `man`, not codes of their own.

### Old codes to new (for the migration)

| Column | Old | New |
| --- | --- | --- |
| `profiles.gender_identity` | `other` | `not_listed` (keep `gender_identity_other`) |
| | `trans_woman` | `woman` |
| | `trans_man` | `man` |
| | `intersex` | `not_listed`, with `gender_identity_other = 'Intersex'` when it's empty |
| | `man`, `woman`, `non_binary`, `agender` | unchanged |
| `profiles.sex_at_birth` | all | unchanged (a code was added) |
| `profiles.pronouns`, `family_relationship`, `advocate_consent` | all | unchanged |
| `users.subscription_plan` | `basic` | `family` (Basic had the Family plan's 3 places) |

PLAN's R2 entry says the dev database can be reset instead; the mapping is here in case it's migrated.

## Design choices

- **One home for the options.** `options.py` holds `Choice` and `Question` dataclasses; `SexAtBirth`, `GenderIdentity` and the other `Literal` types are built from them (`Literal[*codes(...)]`), and `schemas.py` re-uses them. Adding or reordering a choice there changes both what's accepted and what `GET /profiles/options` returns.
- **`GET /profiles/options`** (signed in, behind the policy gate like every `/profiles` route) returns one entry per question, keyed by the field name sent to `PATCH /profiles/{id}/intake`:
  - `choices`: `code`, `label`, `label_under_13` (Girl and Boy for gender), `description` (1.5's "Invite your teen to create their own private Oracle account" for `own_account`) and `available` (`false` for `own_account` until Phase 3b, so the app can grey it out);
  - `write_in_choice` and `write_in_field` (`not_listed` / `gender_identity_other`, `other` / `pronouns_other`);
  - for pronouns, `default_for_gender`: `{"agender": "they_them", "not_listed": "they_them"}`.
  - Labels with a name use `[Name]`, which the app fills in. Question titles aren't served; the task asked for the choices only.
- **The app learns which labels to use** from a new `under_13` flag on `IntakeOut` and `ProfileDetails` (true only for a family member under 13).
- **Unknown codes** (an older app, a typo) get the stories' "Please choose an option to continue." instead of Pydantic's list of allowed values.
- **Teen rule:** `is_teen` and `is_under_13` in `app/profiles/service.py` use R3's `age_group` in `app/core/ages.py`, so the intake and the Oracle's age group can't disagree. It counts on Hawaii's date, the same date `is_adult` uses at sign-up, so a member doesn't move to an older group before their birthday has started at home. The ages shown in the panel and on Manage Family stay on the UTC date, as before.
- **Teen choice and Back:**
  - `teen_profile_choice` is checked against the date of birth in the same request or the saved one.
  - A new date of birth that makes the member a child or an adult clears a saved choice, so `next_question` stays right.
  - Changing the date of birth within the teen years keeps it.
  - `next_question` always returns `done` once the intake is complete, so a member who turns 13 later isn't asked.
- **`own_account` is refused** with 422 `teen_account_unavailable` and nothing is saved. Phase 3b replaces this with the privacy disclaimer, the teen's email and the invite (story 1.5), and skips steps 4 to 7.
- **The client's own date of birth** sent to the self intake is accepted when unchanged (as View & edit accepts its read-only fields) and refused when different. Accounts made before 4 Nov without a date of birth aren't special-cased: their self profile has none, and `check_can_use` (used by `UsableProfile` and the conversations package) answers "Please finish setting up this profile first." instead of letting the age band crash.
- **Family member's date of birth:** a date in the future or more than 120 calendar years back (sign-up's `OLDEST_AGE`) is refused by the service, which knows the name for 2.2's message. A value that isn't a date at all is refused by the schema, which doesn't know the name.
- **Saving failed:** the intake saves (`POST /profiles/self`, `POST /profiles/family`, `PATCH .../intake`, `POST .../intake/complete`) turn any database error into 503 `save_failed` with 2.1's "We couldn’t save your answer just now. Please try again.", without the database's text. The 8.2 actions keep "We couldn’t do that just now. Please try again."
- **Plans:**
  - `entitlements.plan()` returns `trial`, `individual` or `family`;
  - only `family` gets `settings.family_members_included` places, and the trial and Individual get 0;
  - every check still runs under the account row lock;
  - `GET /me/entitlements`'s `plan` now lists the three codes.
- **No code check constraints on `profiles`.** There were none before, and Phase 4 encrypts these columns, which would rule them out. The schemas' `Literal` types guard every write.
- **Not renamed:** every `profiles` column the conversations package reads keeps its name.

## Messages from the stories, and which one where they differ

- Question not answered (complete with a choice step missing): "Please choose an option to continue." (2.1, 2.3).
- Gender write-in, intake: "Tell me in your own words how you describe your gender." (2.1) and "Tell me in your own words how [Name] describes their gender." (2.2).
- Gender write-in, View & edit: 8.2's "Tell me in your own words how [Name] identifies." The two stories word it differently (question 31); each endpoint uses its own story's text.
- Date of birth missing or in the future: "Please enter a valid date of birth for [Name]." (2.2).
- Teen choice missing: "Please choose how you’d like to set up [Name]’s profile." (2.2, 8.1).
- Upgrade before the name is known (`POST /profiles/family`): "Adding family members is part of the Family plan. Upgrade to add someone." (4.2, 9.1, 2.4). After (`.../intake/complete`): "Adding family members is part of the Family plan. Upgrade to add [Name]." (2.2, 8.1).
- Limit reached when adding: 2.2's and 4.2's "You’ve added all the family members included in your plan. Add another member to continue.", not 8.1's "You have 3 active family members, the most your plan includes. Add another member, or turn off another family member to make room." Two stories agree on the first, and the backend can't tell which screen the request came from (question 31).
- Limit reached when turning on: 8.2's "You have 3 active family members, the most your plan includes. Add another member, or turn off another family member first.", with the configured number ("family member" when it's 1).
- Read-only fields in View & edit: "[Name]’s date of birth and sex assigned at birth can’t be changed here. If something is wrong, please contact the support team." (8.2).
- Saving failed: "We couldn’t save your answer just now. Please try again." (2.1, 2.3).

## Messages not in the stories

| Situation | Message | Code |
| --- | --- | --- |
| Self intake sent a date of birth different from sign-up's | "Your date of birth comes from sign-up, so it can’t be changed here. If something is wrong, please contact the support team." | `read_only` |
| Teen choice sent for a family member who isn't 13 to 17 | "This question is only for family members aged 13 to 17." (the upper age follows `age_of_majority`) | `teen_only` |
| `own_account` chosen, until Phase 3b | "Inviting [Name] to their own account isn’t available yet. For now, please choose to manage [Name]’s profile yourself." | `teen_account_unavailable` |
| The same, before the name is known | "Inviting a teen to their own account isn’t available yet. For now, please choose to manage their profile yourself." | `teen_account_unavailable` |
| Date of birth that isn't a date, or out of range before the name is known | "Please enter a valid date of birth." (1.1's wording) | `validation_error` / `invalid_date_of_birth` |
| Gender write-in empty before the name is known | "Tell me in your own words how they describe their gender." | `write_in_required` |
| An unknown option code | "Please choose an option to continue." (the stories' text, reused) | `validation_error` |
| Turning on a member on the trial or the Individual plan | "Family members are part of the Family plan. Upgrade to turn on [Name]’s profile." (was "family plan") | `family_plan_required` |

## Assumed values

- A teen is 13 to `age_of_majority − 1` (17), on Hawaii's date (question 22).
- A family member's date of birth more than 120 years back is a typo, as at sign-up.
- They/Them is the default only for Agender and Not listed; no other gender has a default.
- Pronouns have no "Prefer not to say" (question 23).
- The trial and the Individual plan have no family places; the Family plan has `family_members_included` (3). Paid add-ons are Phase 8.

## For the migration

- `users.ck_users_subscription_plan`: drop it, then recreate it as `subscription_plan IN ('individual', 'family')`. Migration `10e70f9b0139` sets every plan without a `subscriptions` row to NULL first (Phase 8: the column is a copy of the subscription's plan, and nobody has one yet), which covers the old `basic` too, instead of the `basic` → `family` mapping first planned here. Downgrade: `family` → `basic`, `individual` → NULL, and the old check.
- `profiles.teen_profile_choice`: new nullable `VARCHAR` column (autogenerate finds it). No check constraint, no backfill needed.
- Data: the gender codes in the mapping above.
- Data: copy each client's date of birth into their own profile, so self profiles started before R2 aren't left without one: `UPDATE profiles SET date_of_birth = users.date_of_birth FROM users WHERE profiles.account_id = users.id AND profiles.is_self AND users.date_of_birth IS NOT NULL`.

## For the conversations package (R3)

- No column was renamed. New column: `profiles.teen_profile_choice`.
- New codes reach `ProfileContext`:
  - sex at birth: `prefer_not_to_say`;
  - gender: `not_listed` and `prefer_not_to_say`, and no more `other`, `trans_woman`, `trans_man` or `intersex`;
  - the gender write-in now goes with `not_listed`.
  - `app/oracle/contract.py`'s comments still list the old codes.
- `check_can_use` now also refuses a profile without a date of birth (409 `intake_incomplete`), so the age group is never worked out from None.

## New open questions for the BA

1. Are Girl and Boy also the labels in View & edit (8.2) for a member under 13? The backend gives the app `under_13` there too, so it can.
2. Until teen accounts exist (Phase 3b), should "Teen with their own account" be shown greyed out (what `available: false` allows) or hidden?
3. Should the Teen Profile Choice be offered for every relationship, or only Child (question 35 asks the same for invites)? It's offered for any relationship now.
