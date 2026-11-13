# Backend plan: Client scope

We're building the API behind the Client mobile and web apps: all 31 stories in the 12 Client epics of `docs/requirements/client-user-stories.md`. The work is split into phases 0–11, plus Phase R (rework for the BA's 4 Nov stories) and Phase 3b (teen accounts). Phase A (Admin and Super Admin) is planned for afterwards, outside the current scope. Phase 0 sets up foundations; each later phase delivers a group of stories end to end. Tick a story off when its definition of done is met.

Written 2026-10-30, and updated on 2026-11-04 for the BA's new version of the stories (see **Requirements update** below). Where the stories are unclear, this plan picks a value or behaviour and records it under **Assumed values** or **Open questions**, so we can keep building and change course once the BA answers.

## Scope

- **In:** every Client story (Epics 1–12).
- **Out for now:** the Super Admin and Admin stories, so there's no admin panel. Client actions still create the records the admin side will use later (escalations, support requests, email change requests, deletion requests, knowledge gaps), so we store them now. Settings that admins will manage (policy versions, trial length, prices, family limit, the age-of-majority table, specialties, products, reminder timings) start as seeded rows or config values.
- **Owned by the AI team:** the Oracle's behaviour. That covers prompts, the safety classifier, guidance summaries, provider notes, Wellness Plan generation, extracting facts from chat, and the knowledge base content. The backend stores everything, enforces the gates (consent, trial, age, emergency hold), builds the profile context sent to the Oracle, and calls the AI through one interface (see `app/oracle/` below).

## Architecture

### Code layout

```
app/
  main.py           FastAPI app; mounts each domain's router
  core/             settings, database session, security helpers, audit log, error format
  auth/             sign-up, sign-in, 2FA, sessions, password reset, change password
  accounts/         /me, policy acceptance, consent, export and deletion
  profiles/         profiles, health intake, family members
  health/           health profile (questions, answers, completion)
  conversations/    conversations, messages, health consent, safety, escalations
  oracle/           the contract with the AI service, plus a fake for dev and tests
  notes/            guidance summaries, provider notes, visit logs, PDFs
  wellness_plan/    Wellness Plan and Wellness Protocols
  billing/          plans, subscriptions, entitlements, payment webhooks
  support/          support and consultation requests
  notifications/    in-app notifications, reminders, devices, preferences
  worker.py         background job runner
migrations/         Alembic
tests/              pytest
```

Each domain package has `router.py` (endpoints, kept thin), `schemas.py` (Pydantic request and response models), `models.py` (tables) and `service.py` (business rules). Packages are created in the phase that first needs them. `app/models.py` imports every models module so Alembic sees all tables.

### Decisions

| Area | Decision | Why |
| --- | --- | --- |
| IDs | UUID primary keys | Ids appear in URLs; UUIDs can't be guessed or counted. |
| Times | `timestamptz` for every datetime (set on `Base`) | No time zone ambiguity. |
| Database access | Sync SQLAlchemy, one session per request via a dependency. The chat reply streams from a sync generator, which FastAPI runs in its thread pool; the request's session stays open until the stream ends. Before production the Oracle client and the stream become async (Phase 3 decisions). | Sync is simpler; FastAPI already runs sync endpoints in a thread pool. |
| Schema changes | Alembic migrations from Phase 0; `app/create_tables.py` is removed | `create_all` can't change existing tables. |
| Config | `pydantic-settings` `Settings` class read from env vars and `.env` | Durations and limits become config, so BA answers don't need code changes. |
| Passwords | Argon2id via `pwdlib` | OWASP's first choice. |
| Sessions | A random token from `secrets`, stored as a SHA-256 hash in a `sessions` table, one row per device. Sent as `Authorization: Bearer`. The web app may carry the same token in an httpOnly cookie; decide with the frontend. | The stories need per-device sign-out, plus "sign out everywhere" on password reset, email change, policy update and consent revocation. JWTs can't be revoked without a deny-list. |
| 2FA | 6-digit email codes, stored hashed, single use, expiring. A trusted device is a random device token stored hashed, cleared on sign-out (story 1.2). | Matches 1.1 and 1.2; email only, per 1.2's business rules. |
| Auth errors | One generic message for sign-in and forgot password (pending BA question 1) | OWASP; in a health app, revealing whether an email is registered is a privacy leak. |
| Error responses | `{"error": {"code": "...", "message": "...", "field": "email"}}`, using the stories' exact messages | The apps show each message under the right field. |
| Authorization | One dependency loads `{pid}` and checks it belongs to the signed-in account; every profile-scoped endpoint uses it | Family members have no login; the main risk is one account reading another's data. |
| Health data (PHI) | Never in logs, URLs, error bodies (except a family member's first name where a story's message includes it; those go only to the owning account), push or email text, or analytics. Encryption at rest from the managed database and storage, plus app-level AES-GCM (`cryptography`) for the fields the stories single out: date of birth, sex at birth, gender identity, "Your body", hormone and surgery answers. Fields the visit-notes search (5.1) needs stay searchable. | Stories 1.1, 3.1 and 7.1, and the BAA. |
| Audit log | Append-only `audit_events` (actor, action, target, IP, user agent, time, non-PHI details). Kept 6+ years, never shown in the app, no delete path. | BAA Section 13. It holds no PHI, so it can outlive data deletions. |
| Background jobs | A `jobs` table and `app/worker.py`, which claims due rows with `SELECT ... FOR UPDATE SKIP LOCKED`. Reminders are rows with a `due_at`. | Reminders, check-ins, exports and purges with no new infrastructure. Add Redis or Celery only if load demands it. |
| External services | Email, SMS, push, file storage, payments, PDF, OCR and LLM each sit behind a small interface with a fake used in dev and tests; real providers plug in later | We can build and test before vendors are chosen. Every vendor that touches PHI needs a BAA. |
| Oracle | `app/oracle/` defines the calls the backend makes: safety check, streamed reply, summary, provider notes, plan update, fact extraction. A fake returns canned results. | Lets backend and AI work in parallel; the contract is agreed with the AI team in Phase 3. |
| Files | None stored. The 4 Nov stories removed uploads, documents and labs; PDFs are made on request and not kept. | Stories 3.1, 3.5, 5.1 |
| Tests | pytest + `TestClient` against a `genesis_health_test` database in the same Docker Postgres; external services faked | Real SQL behaviour (unique constraints, transactions). |
| Lint | ruff | Fast; one tool for lint and format. |

### Assumed values

These are guesses until the BA answers. All of them live in `Settings`, so changing one is a config change.

| Setting | Assumed value | Stories |
| --- | --- | --- |
| Account lock | After 3 failed sign-ins; lasts 30 minutes or until a password reset, whichever comes first | 1.2 |
| Verification code | 6 digits, valid 10 minutes, 5 tries, resend allowed after 60 seconds; a resent code has 5 new tries, up to 5 sends per sign-in. Per account: 10 code emails an hour; 10 wrong codes in an hour lock it for 30 minutes, and 30 in a day lock it until a password reset | 1.1, 1.2 |
| Reset link | Valid 60 minutes (1.3), single use; can't reuse the current password | 1.3, 11.2 |
| Trusted device | 30 days | 1.1, 1.2 |
| Sessions | Web: 30 minutes idle, 12 hours at most. Mobile: up to 30 days on a trusted device, no idle timeout on the server (the app locks itself after 15 minutes in the background) | 1.2, 1.4 |
| Free trial | 14 days, starting when the email is verified | 1.1, 9.1 |
| Family members | Family plan: 3 active, plus paid add-ons; invited teens count from the invite; turned-off members don't count. Individual plan: none | 8.1, 9.1 |
| Age of majority | Per state (11 Nov, question 22 reversed): 19 in Alabama and Nebraska, 21 in Mississippi, 18 in every other state and DC, and 18 for an unknown or missing state. A settings table (`age_of_majority_by_state`, `AGE_OF_MAJORITY_BY_STATE`), read through `app/core/ages.age_of_majority`, counted on Hawaii's date so nobody passes before their birthday has started at home. The account's own state counts; a family member uses the account holder's (assumed, docs/decisions/state-age-of-majority.md) | 1.1, 1.5, 1.6, 2.2, 3.1, 11.1 |
| Deletion deadline | 10 business days after the request, weekends skipped (public holidays not yet) | 9.2 |
| Name | `first_name` only; no story collects a last name now | 1.1, 11.1 |
| Phone | Not collected (removed on 4 Nov; the column was dropped in R1) | 1.1, 11.1 |
| Email change | Only via a request the support team handles; not self-service | 11.1 |

## Definition of done (every story)

1. Endpoints, schemas, models and an Alembic migration.
2. Tests for the happy path, each Alternate Scenario and each Validation Rules/Errors entry the backend owns, asserting status codes and exact messages (the `test-writer` agent).
3. Audit events for everything the story says must be logged.
4. `story-checker` reports no gaps except UI-only items and plan decisions. `security-reviewer` passes for anything touching auth, sessions or PHI.
5. Ticked off below, with any new assumption added to this file.

## Requirements update (2026-11-04)

The BA's document changed a lot after the first build. `docs/requirements/client-user-stories.md` now comes from the BA's Google Doc through `scripts/sync_user_stories.py`, like the Admin files, so `git diff` shows every later change.

What changed, in short:

- **Teens:** four new stories (1.5, 1.6, 2.3, 2.4). A parent on the Family plan can invite a teen to a private account of their own. The parent can't see the teen's information.
- **Sign-up** collects date of birth, country (US only) state and ZIP code (dropped on 5 Nov, back on 6 Nov), and no phone number. Age groups follow each state's age of majority, and no account is created below it.
- **Gender options** are now Woman, Man, Non-binary, Agender, Not listed and Prefer not to say; sex at birth adds Prefer not to say. Gender sets wording and pronouns only; body questions follow sex at birth or the new "Your body" answers (Phase 4).
- **Plans:** Individual (own profile only) and Family (3 places, paid add-ons). The trial greys out most features.
- **3.2** is US-only (911, 988, Poison Control), is shown before the Health Consent, and has no follow-up or check-ins.
- **Removed:** uploads, documents and labs (old 6.1). Lab values are typed into a conversation and explained, never interpreted.
- **Renamed:** the two Healing Plan stories are one Wellness Plan story; "The Oracle's team" is "the support team"; "Your Oracle Clinician" is "Your Oracle". Hosting is Azure.
- **Messages:** many changed wording.

Story numbers changed. Decisions recorded before 4 Nov use the old numbers, and the stories' own "see story X.Y" links still do too, so look stories up by title.

| Old | New |
| --- | --- |
| 1.1–1.4 | 1.1–1.4 |
| none | 1.5 Teen Sign Up (Parent Invite); 1.6 Teen Reaches the Age of Majority |
| 2.1, 2.2 Complete Guided Health Intake | 2.1 Onboarding (Myself), 2.2 Onboarding (Family Member) |
| none | 2.3 Onboarding (Teen); 2.4 Onboarding (Teen Reaching the Age of Majority) |
| 3.1–3.5, 4.1, 4.2, 5.1, 5.2 | unchanged numbers |
| 6.1 Manage Documents & Labs | removed |
| 7.1 Health Profile | 6.1 |
| 8.1, 8.2 Healing Plan | 7.1 View & Update the Wellness Plan |
| 9.1, 9.2 Family | 8.1, 8.2 |
| 10.1 Free Trial & Subscription | 9.1 |
| 11.1 Contact The Oracle's Team or Book a Consultation | 10.1 Contact the Support Team & Consult With Support Team |
| 12.1–12.4 Profile & Account | 11.1–11.4 |
| 13.1, 13.2 Notifications, Policy Updates | 12.1, 12.2 |

The rework of what's already built is Phase R, done before 3.2 because 3.2's new rules depend on it. The teen stories are Phase 3b.

### Requirements update (2026-11-05)

A smaller update, synced on 5 Nov (the Google Doc's last edit is 4 Nov). Client changes:

- **No ZIP code any more.** Sign-up step 2 is country and state only (1.1), with "Please enter a valid state." when the state is empty or invalid. 11.1's profile shows and edits country and state only. R1 collected ZIP; R1b removed it. (6 Nov: it's back, see R1c.)
- **Teens who've lost access can still sign in** (1.2, 1.5, 8.2, 11.4, 12.2), whatever the reason: removed, turned off, Family plan ended, consent revoked, or the parent hasn't accepted updated policies. They see only Privacy & Data (export and delete), with "Your access is paused. Please ask your parent or guardian. You can still download your data or ask for it to be deleted here." Before, removed teens couldn't sign in and emailed the support team. This answers most of question 37.
- **Problems in the new text** (question 48): 12.1's notice to the *parent* that a teen's access is paused or restored now carries the teen's message; the short "Your access is paused. Please ask your parent or guardian." is still in 11.4 (next to the long one), in 12.1's notices to the teen and in 12.2; and two typos ("Teen’s access turned off (shown to the teen):" repeated inside 8.2's message, and "our access is paused" in 12.2). We'll use the long message everywhere and the old parent texts until the BA says otherwise.

Admin and Super Admin changes (out of scope for now): the client details no longer show a ZIP code, teens who've lost access request deletion in the app (an "In app" Teen Deletion), the email route is only for teens who can't sign in at all, and a parent can't ask for a teen's data to be deleted.

### Requirements update (2026-11-06)

Synced on 6 Nov (the Google Doc's last edit is 6 Nov, 06:53 UTC). Only two changes; Teen Onboarding (1.5, 2.3, 2.4, 1.6) is word for word the same, and so are the extra tabs (trans intake questions, intent matrix, tone guide). The doc's comments have no new threads since 4 Nov, and no suggested edits show in the export.

- **The ZIP code is back** (1.1, 11.1, Super Admin and Admin 3.1): sign-up step 2 asks for country, state and ZIP code, with "Please enter a valid state and ZIP code." (the old "Please enter a valid state." is still there too); Profile & Account shows and edits it, with "Please enter a valid ZIP code."; Client Details' Account section shows it. Built as R1c.
- **Super Admin Client Details shows health information** (Super Admin 3.1): "Health Information: includes health information only which would get updated as the user converse with the Oracle." The "No health information" acceptance criterion and the health profile answers in the Privacy line were removed. Not built: question 49.
- **Answered in the doc's comments** (3 Nov, Azka Tariq, for Deborah): trial-locked clients and paused teens get no emergency route, because it's an education app, and a paused teen stays paused until the Family plan is paid. An aged-out teen's history is kept at least 6 years (the BAA), and they can export it.

### Requirements update (2026-11-06, 19:22)

The BA edited the stories again at 19:22 UTC (synced in `fc4f873`). Teen Onboarding gains a Welcome & Disclaimer screen before account setup (1.1, 1.5); every deletion gets a 10-day grace period, then a lock and a 45-day deadline, and a parent's account deletion now deletes invited teens' accounts (11.4, 8.2, 1.2, 12.1, Super Admin and Admin 5.2); "stay as advocate only" is deferred and profile transfers are removed; health details from conversations save automatically (3.1, 3.3, 6.1), with a new Hypothalamus Circle Map (6.1); the Oracle gives label directions, no prescription doses and test links (3.1, 3.3, 7.1); new note and disclaimer wording (3.4, 3.5); Client Details shows the health profile read-only for Admins and the Super Admin (3.1, settling question 49); Admins lose Consent Management and the Audit Logs; the knowledge base drops sources and syncs and gains "Answer pending" (6.1–6.3). **Decided by the user on 10 Nov:** where a story still has an old line next to the new text, the new text wins: 3.1's automatic saving (not its old "Saving" acceptance criterion that asks first), 8.2's automatic deletion of a removed teen's data (not the alternate scenario where the teen emails the support team), and Admin 3.1's read-only health profile (not its old Privacy line). **Also decided on 11 Nov:** invited teens' data is deleted as the stories say (with the parent's account, on removal, and on the teen's own request); an earlier idea of keeping it was withdrawn. Built on 10 Nov (code only, migration `978c5998e7e1`); decisions and new questions are in `docs/decisions/deletion-flow-1922.md`, `conversations-health-1922.md`, `guidance-wellness-1922.md` and `admin-1922.md`. Billing is parked: ending the subscription on deletion isn't built.

### Built on 11 Nov

- **Phase 4 to the Health Intake Routing document:** 184 questions in 11 sections (was a 71-question placeholder), with the document's routing, "asked first / asked later" tags and the follow-ups for under-13s (`docs/decisions/phase-4-routing-doc.md`, migration `4f0d5376cfd5` clears answers the new bank can't use). Answers PLAN question 1, and questions 23 and 29.
- **Age of majority by state:** 19 in AL and NE, 21 in MS, 18 elsewhere (stories 1.1, 3.1, 11.1 and the routing document), reversing question 22 (`docs/decisions/state-age-of-majority.md`).
- **Stripe** as the payment provider (`docs/decisions/stripe-billing.md`, migration `5f4eef63b135`), switched on by `STRIPE_SECRET_KEY`. Answers question 2 for the web app; the iOS app's in-app purchase question stays open.
- **AI replies from the senior team's chat API** (`ORACLE_BACKEND=senior`, `docs/decisions/senior-chat-oracle.md`); every other Oracle call, including the safety check, is still the fake. On 11 Nov the senior dev server failed at its generate step on every test message, so a live reply isn't confirmed yet.

## Phases

### Build status (2026-11-06)

On 6 Nov the user asked for the whole backend to be built first, with **no new tests**: testing comes once everything is built. So every phase below from R2 on has its code (endpoints, schemas, models, services, jobs) but **not** the rest of the Definition of done: no tests, no `story-checker` or `security-reviewer` pass. Those checkboxes stay unticked until then. Existing tests are expected to fail where the stories changed (for example the plan codes and the gender codes).

Each part's design choices, stored codes, messages not in the stories, assumed values and new open questions are in its own file in `docs/decisions/`:

| Phase | Stories | Decisions | Open questions |
| --- | --- | --- | --- |
| R2 Profiles and family | 2.1, 2.2, 4.2, 8.1, 8.2, 9.1 | `r2-profiles.md` | 3 |
| R3 Conversations, 3.2 Escalation | 3.1, 3.2 | `r3-conversations-and-3.2.md` | 5 |
| Conversations wiring | 3.1 with 6.1, 10.1 | `integration-conversations.md` | 4 |
| 3b Teen accounts | 1.5, 1.6, 2.3, 2.4 and the teen parts of others | `phase-3b-teens.md` | 8 |
| 4 Health profile | 6.1 | `phase-4-health-profile.md` | 9 |
| 5 Oracle outputs | 3.3, 3.4, 3.5 | `phase-5-guidance-and-notes.md` | 7 |
| 6 and 7 Visit notes, Wellness Plan | 5.1, 5.2, 7.1 | `phase-6-7-visits-wellness.md` | 11 |
| 8 Billing | 9.1, 11.3 | `phase-8-billing.md` | 8 |
| 9 Notifications | 12.1, 12.2 | `phase-9-notifications.md` | 7 |
| 10 Account and support | 10.1, 11.1, 11.4 | `10.1-support.md`, `phase-10-account.md` | 17 |
| 11 Home dashboard | 4.1 | `phase-11-dashboard.md` | 9 |
| A1 Admin access | Super Admin 1.1, 1.2, 7.1, 7.2, 10.1, 11.1, 12.1, 12.2; Admin 1.1–1.3 | `phase-a1-admin-access.md` | 8 |
| A2 Admin operations | the other Admin and Super Admin stories | `phase-a2-admin-operations.md` | 12 |
| 6 Nov 19:22 changes | 1.2, 3.1, 3.3–3.5, 6.1, 7.1, 8.2, 11.4, 12.1; Admin and Super Admin 2.1, 3.1, 5.2, 6.1–6.3, 9.x, 10.1, 11.1 | `deletion-flow-1922.md`, `conversations-health-1922.md`, `guidance-wellness-1922.md`, `admin-1922.md` | see each file |

Each file's "Added during integration" or "done during integration" notes record what was changed when the parts were joined. The one migration for all of this is generated after the code (see the next steps below).

**Next steps, in order:**

1. **Done 6 Nov:** migration `10e70f9b0139` (`2026_11_06_1100-10e70f9b0139_client_and_admin_phases.py`) creates every new table and column, with what autogenerate misses added by hand (the checks on existing tables, the data steps, the circular knowledge key, and triggers that freeze published policy texts and keep knowledge content from being deleted). Its downgrade refuses while escalations, account or teen deletion requests, teen accounts or subscriptions exist. It was reviewed by `migration-reviewer`, run up, down and up, and `alembic check` finds no drift. A smoke run against the dev server covered sign-up to a guidance summary, and found that `python -m app.worker` had never loaded its job handlers (fixed in `app/worker.py`).
2. Tests for each story, then `story-checker` and `security-reviewer` per phase, as the Definition of done says. Fix what they find, then tick the stories here.
3. Fold the decisions files' questions into the table below once the BA has seen them.
4. R4: story numbers in code comments and `CLAUDE.md`.

### Phase 0: Foundations (done 2026-10-30)

- [x] `Settings` with `pydantic-settings`; `app/database.py` moved into `app/core/`
- [x] Alembic, with a first migration for `users`, `audit_events` and `jobs`; `app/create_tables.py` deleted
- [x] Package layout (`app/core/`, `app/auth/`); per-request database session dependency
- [x] pytest, test database and fixtures; ruff
- [x] Error format and handlers; CORS for the web app
- [x] `audit_events` table (append-only, enforced by a database trigger) and an `audit.record()` helper
- [x] Email interface with a console sender for dev and an in-memory one for tests
- [x] `jobs` table and worker with retries

Done when `uv run alembic upgrade head` builds the database from empty and `uv run pytest` passes, including a `/health` test. Both hold: the test run rebuilds its database from the migrations every time, and a test fails if the models and migrations drift apart.

### Phase 1: Accounts and sign-in (done 2026-10-30)

- [x] **1.1 Sign Up**: `POST /auth/signup` creates the account, records acceptance of the current Terms and Privacy Policy (version 1.0 is seeded by a migration), starts the trial and emails a code. `POST /auth/verify` checks the code, marks the email verified and signs the client in. `POST /auth/verify/resend` sends a new code.
- [x] **1.2 Sign In**: `POST /auth/signin` returns `signed_in` on a trusted device, otherwise `verification_required` with a code emailed; `POST /auth/verify` finishes it. Covers the 3-strike lock, deactivated accounts and the per-IP limit. `GET /me/next-step` returns `policy_update` → `upgrade` → `dashboard`; Phase 2 adds `intake`.
- [x] **1.3 Forget Password**: `POST /auth/password/forgot`, `POST /auth/password/reset/check`, `POST /auth/password/reset`. A reset unlocks the account, ends every session and clears trusted devices.
- [x] **1.4 Sign out**: `POST /auth/signout` ends this device's session and forgets the device. It also takes the `device_token`, so it still works after a timeout, and it always answers 204. Sessions time out after 30 idle minutes (since R1: web sessions only, see Phase R).
- [x] **12.2 Reset Password** (signed in): `POST /me/password`. Keeps this session and device; signs out and untrusts every other device.
- [x] **13.2 Policy Updates** (client side): `GET /policies/current` (no sign-in), `GET /me/pending-consents`, `POST /me/policy-acceptances`. Publishing new versions is admin work, later.

Decisions made while building Phase 1:

- **One verify endpoint.** Sign-up and sign-in codes both go through `POST /auth/verify`. Each challenge records its purpose (`verify_email` or `sign_in`).
- **Unverified email** (open question 6): signing in with an unverified email sends a `verify_email` code before any session exists, so `next-step` never has to handle it. (Since R1 there are no unverified accounts: the account is created at verification.)
- **Policy screen order** (open question 4): the backend supports both. Before sign-in, the app can show `GET /policies/current` against what this device last saw. Acceptance is recorded after sign-in with `POST /me/policy-acceptances`, as 13.2 requires. `next-step` returns `policy_update` for anything still pending, which catches new devices.
- **Which messages reveal the account.** Wrong password and unknown email get the same message (BA question 1): since R1, 1.2's "Incorrect email or password. Please try again." The lock message follows the story, so it shows for a locked account whatever the password. The deactivated message only appears with the right password.
- **Messages not in the stories** (R1 replaced the struck ones with the 4 Nov stories' text):
  - first name empty: "Please enter your first name." (the story says "full name"; BA question 2)
  - ~~no country code~~: the phone is gone
  - ~~current password empty~~: now 11.2's "This field is required."
  - ~~reset link used or made up~~: now 1.3's "This link has expired. Please request a new one."
  - not signed in: "Please sign in to continue."
  - code resend limits and the per-IP limit messages (listed below and in R1)
- **Apostrophes** in messages use the stories' typographic ’, so the text matches the stories exactly.
- **Password reuse** (open question 7): only the current password is checked.
- **Per-IP limit:** 20 events in 15 minutes from one IP, counted from the audit log. It applies separately to sign-ups, failed sign-ins, failed codes, reset requests and failed resets. In production, uvicorn must run with `--proxy-headers` and `--forwarded-allow-ips` set to the load balancer's exact address (never `*`), or every client will share the proxy's IP.
- **Email timing:** emails go out after the response (FastAPI background tasks, the `EmailLater` dependency). A failing provider can't break the request, and response times don't reveal whether an account exists. Codes and reset tokens are secrets, so they don't go through job payloads.
- **Guessing limits**, added after the security review:
    - each code allows 5 tries (since R1 a resend starts a new count, as 1.1 and 1.2 now say);
    - 10 wrong codes on one account in an hour locks the account (R1 adds 30 in a day, which locks it until a password reset);
    - at most 10 code emails per account per hour;
    - 3 wrong current passwords on `/me/password` within 30 minutes end that session;
    - every counter row is read with `SELECT ... FOR UPDATE`, so parallel requests can't each read the old value. (The per-IP limits count audit rows without a lock; see R1's "Before production".)
- **Unverified accounts:** signing up again with an email whose account was never verified replaces that account's sign-up details (since R1: first name, date of birth and state), password, policy acceptances and trial. Without this, anyone could hold an email they don't own. (Since R1 the same rule applies to pending sign-ups instead: there are no unverified accounts.)
- **Trusted devices and timeouts:** an idle timeout ends the session but keeps the device trusted, because story 1.2 says 2FA isn't needed at every sign-in. An explicit sign-out forgets the device.
- **Password changes:** a reset or change closes every open code and reset link.
- **Reset links** carry the token after `#` (`/reset-password#token=...`), so it never reaches a server log or a Referer header. The web app reads it from `location.hash`.
- **Production switches:** `ENVIRONMENT=production` hides `/docs` and refuses the console email sender. Every response has `Cache-Control: no-store`.
- ~~**12.2's rules message** leaves out "lowercase"~~: the 4 Nov stories share one rules message, with "lowercase" (R1).
- **More messages not in the stories:**
    - forgot password: "If an account exists for this email, we’ve sent a link to reset your password."
    - reset done: "Your password has been reset. Please sign in."
    - link check: "This reset link is valid."
    - any 500: "Something went wrong. Please try again."
    - code limits: "You’ve asked for too many codes. Please wait an hour and try again." and "Please wait a minute before asking for a new code."; and "Please sign in again to get a new code." for a closed challenge or, since R1, one that has used its 5 sends
    - per-IP limit: "Too many attempts. Please wait a few minutes and try again."

Deferred from the Phase 1 reviews (2026-10-30), each with the phase it's due in:

- **Sign-up details are stored in plain text** (story 1.1 NFR; the phone until R1, now `users.date_of_birth` and `state`). Phase 4 adds the field-encryption helper (AES-GCM, key from settings or a KMS) and encrypts `users.date_of_birth` along with the profile fields. `pending_sign_ups` holds the same fields for at most about an hour; encrypt them too if the helper makes it cheap.
- **Policy gate on the server:** `next-step` only tells the app what to show. Phase 2's first health endpoint adds a dependency that returns 403 `policy_update_required` while policies are pending. Phase 3 asks for the Health Consent per profile when a reply is needed, which also covers an updated version. Asking for it straight after sign-in when a new version is published is 13.2's, in Phase 9.
- **Policy texts:** the seeded 1.0 versions have no URL yet; the texts come from The Oracle's team.
- **Codes are stored as plain SHA-256**, which anyone with database access could reverse. Switch to HMAC with a server secret once secrets management exists, before production.
- **Before production:** set the trusted-proxy config, group IPv6 addresses by /64, put an edge or WAF rate limit in front, and give the app's database role INSERT and SELECT only on `audit_events`. Run migrations as a separate owner role.
- **Accepted for now, pending BA question 1:**
    - sign-up's "already exists" message and the lock message both reveal that an email is registered;
    - anyone who knows an email can lock that account with 3 wrong passwords.
- **Sign-up records the policy versions current at submit time**, not the ones the client saw. Add `policy_version_ids` to sign-up if the BA wants it strict.
- **Email uniqueness** relies on the app lowercasing emails. Add a `lower(email)` unique index before admin tools write users.
- **Inactivity timeout:** once the apps poll (Phase 9), only requests the client made should refresh `last_seen_at`.
- **Web token storage** (httpOnly cookie or app storage) is a decision for the frontend team.

### Phase 2: Profiles and family

- [x] Server-side policy gate: `ClientSession` (`app/accounts/dependencies.py`) returns 403 `policy_update_required` while policies are pending. Every profile endpoint uses it, and every later health endpoint must too.
- [x] **2.1 Health Intake – Myself**:
    - `POST /profiles/self` is step 1, "For myself".
    - `PATCH /profiles/{profile_id}/intake` saves one step; the Back button sends an earlier answer again.
    - `GET /profiles/{profile_id}/intake` returns the answers so far and `next_question`.
    - `POST /profiles/{profile_id}/intake/complete` returns the Oracle's greeting with the first name.
    - `GET /me/next-step` now returns `intake` with the `profile_id` to resume (story 1.2).
- [x] **2.2 Health Intake – Family Member**:
    - `POST /profiles/family` starts the draft, or resumes the unfinished one, and checks the plan has room.
    - The 7 steps are saved through the same `PATCH /profiles/{profile_id}/intake`.
    - `POST .../intake/complete` checks the plan again, returns the member's `profile_id` for the app to make active, and gives the "I’m glad you’re here for [Name]" greeting.
    - `DELETE /profiles/{profile_id}` cancels an unfinished intake and leaves no profile behind.
    - The advocate consent's time is recorded, and the option chosen stays out of the audit log.
- [x] **4.2 Switch Profiles**:
    - `GET /profiles` is the profile panel: the client's own profile first, then family members (relationship, age, whether the intake is finished, and `status`). Turned-off members are left out. `OwnedProfile` checks each `{profile_id}`.
    - Advocate-only accounts work: their finished profiles are all family members.
    - The default profile (`default_profile` in `app/profiles/service.py`) is the client's own profile, or the first active family member for advocate-only clients. `/me/next-step` returns it with `dashboard`. The 9.2 actions return it as `default_profile_id`, for the app to switch to when the active member is turned off.
    - Switching itself happens in the apps. The server refuses turned-off and deletion-requested members where a profile gets used: in Phase 3 (conversations) and later phases.

Decisions made while building 2.1:

- **Stored codes:**
    - sex at birth: `male`, `female`, `intersex`
    - gender identity: `man`, `woman`, `trans_woman`, `trans_man`, `intersex`, `non_binary`, `agender`, `other`, with a write-in for `other`
    - pronouns: `he_him`, `she_her`, `they_them`, `other`, with a write-in for `other`

    Story 2.1's lists are used until the routing document settles the canonical lists (open question 1).
- **A future date of birth** gets "Please choose a date that isn’t in the future." (the story only says the picker can't choose one).
- **Under 13:** the date is refused with the story's message, and the account stays as it is until open question 5 is answered.
- **After completion**, `PATCH .../intake` answers 409 "Your intake is already complete. You can update these details in My Health." Edits after that belong to story 7.1 (Phase 4), where date of birth and sex at birth can't be changed.
- **Who needs the intake:** an account needs it until at least one profile has completed one. That leaves room for advocate-only clients, who only add family members (story 2.2).
- **Another account's profile** gets the same 404 as a profile that doesn't exist.
- **Messages not in the stories:**
    - "Please answer this question to continue." (completing with a step unanswered; the field names the step)
    - "We couldn’t find that profile."
    - "Please review and accept the updated policies to continue." (the policy gate)
- **"Today"** for the future-date and under-13 checks is the UTC date. That's within a day of the client's own date; revisit if open question 8 adds a time zone.
- **Audit:**
    - each saved step records `profile.intake_answered` with the field names only;
    - creation and completion are recorded;
    - an under-13 refusal records `profile.under_13_refused` with no date, so those accounts can be found once open question 5 is answered.
- **Locking:** saving a step and completing both lock the profile row first, so a save can't land after completion.

Carried forward from the 2.1 review:

- ~~**2.2** must handle switching the step-1 choice, and give family profiles their own required steps.~~ Done in 2.2; see below.
- **Phase 3:** conversation endpoints must require a completed intake for the profile (a dependency like the policy gate), so a client who stopped at the under-13 refusal can't chat anyway.
- **Phase 4:** encrypt every field about the person: date of birth, sex at birth, gender identity, pronouns and both write-ins, plus a family member's first name, relationship and advocate consent (story 2.2: family members' details must be encrypted at rest). This goes further than the PHI decision above, which names only some of them.
- [x] **9.1 Add Family Member**: every entry point uses `POST /profiles/family`. The limit counts only active members, and the trial lock is built (`app/billing/entitlements.py`, `GET /me/entitlements`). The intake is 2.2's. Upgrading to a higher plan and the payment failure are Phase 8.

Decisions made while building 2.2:

- **Plan stand-in:** `users.subscription_plan` is null on the free trial and `"basic"` once subscribed. Basic includes `FAMILY_MEMBERS_INCLUDED` = 3 family members. Family members are locked during the trial (story 10.1), so a trial client gets the upgrade message, including at their very first intake. Phase 8 replaces the stand-in with real subscriptions. Until then, set the column by hand to try family features.
- **Stored codes:**
    - relationship: `parent`, `child`, `partner`, `someone_else`
    - advocate consent: `agreed`, `parent_or_guardian`, `authorised_to_act`
    - "Man/Boy" and "Woman/Girl" use the same `man` and `woman` codes as 2.1
- **What counts toward the limit:** only finished family profiles. One unfinished family draft at a time; starting again resumes it. The plan is checked when a draft starts and again when it completes.
- **Upgrade message:** before the name is known it says "Upgrade to add them."; at completion it names the member.
- **Switching at step 1:** until an account has finished any intake, choosing "For myself" discards an unfinished family draft, and the other way round, so there is only ever one intake to resume.
- **First name** is trimmed and given a capital first letter when saved.
- **Family-only questions** sent for the client's own profile get 422 "This question is only for family members."
- **Cancelling** a finished profile gets 409 "This profile is already set up. You can remove it from Manage Family." (removal is 9.2).
- **Messages where the stories disagree:**
    - limit reached: 2.2's "You’ve added all the family members included in your plan. Add another member to continue." is used, not 9.1's "You have 3 active family members, the most your plan includes…";
    - trial lock: 2.2's "Adding family members is part of the family plan…" is used, not 10.1's general "This is part of the Basic plan. Subscribe to unlock it."

    Both are for the BA (alongside open question 3).
- **Changing who the member is** (relationship, first name or date of birth) after step 4 clears the advocate consent and asks step 4 again, so the consent always matches the person.
- **Database checks:** `users.subscription_plan` can only be null or `basic`; a profile's consent option and its time are set together; and an account has at most one unfinished family draft.
- **Write-in messages** say "they"/"them" if the name isn't known yet.

Carried forward from the 2.2 reviews:

- ~~**9.2:** turning a member back on must re-run the limit check under the account lock, and `family_members_used` must leave out turned-off members.~~ Done in 9.2.
- **Phase 8:** buying an add-on or a higher plan must re-run the limit check under the account lock.
- **Before production:**
    - Error reporting (an error tracker or gateway logs) must never capture `AppError.message` or response bodies, which can contain a family member's name.
    - Add per-account limits on profile writes (counting recent `profile.*` audit events), so a script can't grow the 6-year audit table without limit.
- **Before names reach PDFs or Oracle prompts** (Phases 3 and 5): cap `first_name` and the write-ins at a sensible length (100), and reject control characters.
- [x] **9.2 Manage Family Profiles**:
    - `GET /profiles/family` is the Manage Family screen: places in use ("2 of 3 active family members") and a card for each finished member, turned off or not.
    - `GET /profiles/{profile_id}` and `PATCH /profiles/{profile_id}` are View & edit.
    - `POST /profiles/{profile_id}/turn-off` and `/turn-on` toggle a member. Turning on needs a free place.
    - `POST /profiles/{profile_id}/deletion-request` is Remove: the typed first name confirms it, and a `deletion_requests` row is stored for the team.
    - Every edit, toggle and request is audited.
    - Later phases: health profile completion % on the cards (Phase 4), pausing and resuming reminders (Phase 9), and the team's review, the purge and the "deleted" notification (Phase 10).

Decisions made while building 9.2:

- **Turned off:** `profiles.turned_off_at`. The member is hidden from the panel, can't be used, and doesn't count toward the limit. They stay on Manage Family and can still be viewed and edited. Only finished family members can be turned off; the database refuses it for the client's own profile.
- **Deletion requested:** `profiles.deletion_requested_at` plus a `deletion_requests` row (account, profile, `pending`, `due_at`), kept without foreign keys so it outlives the purge. As the story says, the member keeps their place and stays in the panel until the deletion is completed. Meanwhile they can't be edited or toggled (409), and Phase 3 must refuse new conversations for them. To free the place straight away, the client turns the member off first. Question 18 asks the BA.
- **A declined request** (Phase 10 or admin): set the row to `declined` and clear `deletion_requested_at`; the member is back as they were.
- **Changing the relationship** in View & edit needs the advocate consent again in the same request (2.2's step 4 and its message). This keeps the consent matching who the member is, as the 2.2 decision above does. A first-name change keeps the consent; it's usually a correction. The story doesn't mention consent here, so this is question 19.
- **Read-only fields:** date of birth and sex at birth are accepted unchanged, so the app can send the whole form, and refused with the story's message if they differ.
- **Write-ins** can be sent on their own while the saved choice is "Other". The audit log lists a write-in as its choice (`gender_identity`), so it never shows that someone described their own gender.
- **Advocate-only rule:** a member can't be turned off or removed when no other finished, active profile without a deletion request is left on the account. A client whose own profile is finished always passes.
- **Remove confirmation:** the typed name is compared ignoring case and surrounding spaces.
- **Unfinished drafts** aren't shown on Manage Family; Add family member resumes them.
- **Messages not in the stories:**
    - "[Name]’s profile is turned on." (turn-on succeeded)
    - "Family members are part of the family plan. Upgrade to turn on [Name]’s profile." (turning on during the trial)
    - "[Name]’s data is being deleted, so their profile can’t be changed." (any change to a deletion-requested member)
    - "This can only be done for a family member." (a 9.2 action on the client's own profile)
    - "Please finish adding this family member first." (a 9.2 action on an unfinished draft)
    - The limit message uses the configured number and says "family member" when it's 1.

    These and the story's messages include the member's first name. They go only to the owning account, as the PHI decision above allows.
- **Locks:** the 9.2 actions lock the member, check it, then lock the account, the same order `complete_intake` uses. The engine pins READ COMMITTED, which the after-lock counts rely on.
- **Database errors** anywhere in a 9.2 action give the story's "We couldn’t do that just now. Please try again." (503), without logging the error text.

Carried forward from the 9.2 reviews:

- **Phase 3:** a dependency for profile-scoped endpoints that refuses turned-off and deletion-requested members (`_refuse_if_not_in_use` in `app/profiles/service.py` has the rule and messages).
- **Phase 10:**
    - The purge marks the `deletion_requests` row `completed`, notifies the client ("[Name]’s data has been deleted."), and audits it.
    - Pick one lock order for whole-account work before building it. A cascading `DELETE FROM users` locks the user row before the profiles, the reverse of the 9.2 actions.
- **Before production:**
    - Don't enable Remove until the team is told about new deletion requests (an email job or the admin queue) and has a runbook for the 10-business-day deadline.
    - Postgres puts a row's values in constraint errors ("Failing row contains ..."), and `hide_parameters` doesn't hide them. Server logs for unexpected errors must not include the database error text.
    - Public holidays in `due_at`.

### Phase R: Rework for the 4 Nov stories (next)

Built code that the new stories contradict.

- [x] **R1 Sign-up, sign-in and passwords** (1.1–1.4, 11.2, 12.2; done 2026-11-04). `POST /auth/signup/check` is new; `POST /auth/signup`, `/auth/signin`, `/auth/verify`, `/auth/verify/resend`, `/auth/password/*`, `/me` and `/me/password` changed. Migration `87cdf5c2c16a`.
    - **Sign-up:**
        - Remove the phone number: the field, its validation, the column and `phonenumbers`.
        - Add date of birth, country (US only) and state to the request and to `users` (ZIP too, until R1b).
        - Refuse anyone under the age of majority before anything is saved, with a check endpoint for the app's step 2.
    - **Age of majority:** per state since 11 Nov (`app/core/ages.py`, question 22): the selected state decides the age at sign-up. The `age_group` helper moved to R3, its first user.
    - **Trial and codes:**
        - The trial starts when the email is verified.
        - A resent code starts a new count of wrong attempts, still capped by the hourly limits.
    - **Sessions by platform:**
        - Web: 30 minutes idle, 12 hours at most. Mobile: up to 30 days on a trusted device.
        - Inactivity gets 1.2's message; the maximum age keeps 1.4's.
    - **Reset link:** valid 60 minutes, and one message for an expired, used or unknown link.
    - **New wording:**
        - messages: the sign-in error, deactivated, email taken, password rules, passwords don't match, reused password, empty fields, and the wrong-code and expired-code messages chosen by purpose (question 31);
        - "Terms of Service" as the policy's title;
        - "Your Oracle" and "the support team" in emails.

    Decisions made while building R1:

    - **Age check:**
        - `is_adult` counts on Hawaii's date (UTC−10, the last US state to reach a date), so nobody passes before their 18th birthday has started where they live.
        - `POST /auth/signup/check` takes steps 1–2 (date of birth, country, state), ignores any other field, saves nothing and answers 204 or the same 422 errors as sign-up, including `under_age`. Sign-up runs the same check again before touching the database.
        - Refusals aren't logged yet (question 32).
    - **Sign-up details:**
        - The 50 states and DC only.
        - A date of birth more than 120 calendar years back is a typo.
        - `country` accepts only "US" (also a database check); anything else gets Pydantic's "Input should be 'US'", since no story has a message (question 31).
        - The `last_name` column stays, but sign-up no longer takes it (question 32).
    - **Messages not in the stories** (question 31):
        - empty email on sign-up and forgot password: "Email is required.";
        - empty confirm password on sign-up and reset: "The passwords don’t match.";
        - the per-challenge resend cap: "Please sign in again to get a new code." (a sign-up's code: "Please sign up again to get a new code.");
        - the self intake's date of birth differing from sign-up's: "Please enter the date of birth you gave when you signed up." (until R2 drops the question).
    - **Code messages by purpose:**
        - sign-up codes use 1.1's wrong and expired texts, sign-in codes use 1.2's;
        - a made-up challenge id gets 1.2's;
        - the wrong code that uses up the 5th try gets the expired text, because only a new code helps.
    - **Resends:**
        - a resent code gets 5 new tries, as 1.1 and 1.2 now say;
        - guessing stays capped by 5 sends per challenge, 10 code emails an hour, the 10-an-hour wrong-code lock, and a new 30-a-day lock that only a password reset (or a change from a signed-in device) ends (`locked_until` is set to 9999-12-31);
        - a locked account is refused before the code is compared;
        - only real wrong guesses (`auth.code.failed`, the account as actor) count towards the account's locks, and only those since the last password reset or change (`users.password_changed_at`). Codes refused before comparing (unknown, closed, expired, locked) are `auth.code.rejected`, with the account as target, and only the per-IP limit counts them, so an old challenge id can't push someone's account towards a lock;
        - ~~**accepted risk:** someone could guess codes on an email's unverified account into the until-reset lock~~: gone, because there are no unverified accounts (see "Account created at verification" below). Sign-up attempts have no lock at all.
    - **Locks are taken user row first,** then their codes and reset links, in every flow (`verify` and `reset_password` re-read the challenge or link under the lock), so two requests for one account can't deadlock.
    - **Reset links** close after 5 tries at a new password equal to the current one (`reset_link_max_failures`), so a link can't test guesses at the current password.
    - **A password change** from a signed-in device also ends a lock: it proves the current password on a live session.
    - **Account created at verification** (story 1.1: "when they verify the code, then their account is created"; changed 4 Nov after comparing with the team's API):
        - `POST /auth/signup` saves the form in `pending_sign_ups`, not `users`, and emails the code. **Every sign-up is its own attempt**, with its own row and code, even for the same email. (A first version kept one row per email; the security review showed anyone could then keep the real owner from signing up, by signing up again to close their code or by setting off the email's lock, with no account to reset.)
        - The right code creates the account with that attempt's id, records the policy versions shown on the form, starts the 14-day trial, and deletes every attempt for the email. Its used code moves to the account (so reusing it gets 1.1's "Please request a new code."); the other attempts' codes are kept with no owner, closed, so they answer the same and a resend says "Please sign up again to get a new code." (not in the stories).
        - An attempt is deleted 60 minutes after its last code (`pending_sign_up_minutes`; a resend pushes it back) by the `auth.purge_pending_sign_up` job, which deletes every expired attempt each time it runs. So the date of birth and state of someone who never verifies aren't kept (question 43).
        - **Limits, chosen so that nobody can block someone else's sign-up:** 5 tries a code and 5 codes per attempt; at most 5 attempts an hour for one email from one IP address (`max_sign_ups_per_email_per_hour`; then "You’ve asked for too many codes...", nothing saved), so one place can't flood an inbox; and the per-IP limit of 20 wrong or refused codes per 15 minutes. There's no per-email lock: anyone could set it off, and the owner couldn't get past it.
        - **Accepted risk:** someone using many IP addresses could, over a long time, guess a code and create an account on an email they don't own. One IPv4 address (or IPv6 /64) gets at most about 80 wrong codes an hour; even odds need about 690,000 guesses, roughly 8,700 IP-hours (about 9 hours with 1,000 rented addresses), and every 5 guesses emails the owner a code. The account would carry the guesser's name, date of birth and state. Mitigations: verifying emails the owner "An account with Your Oracle has just been created..." with a pointer to Forgot password; the owner's reset signs everyone else out and forgets their devices. Still open: a link with a long token in the code email would close this entirely (question 46), and the owner can't yet correct the date of birth after taking an account back (question 47). Any later flow that trusts a verified email (1.5 invites, billing) must keep this in mind.
        - The per-IP limits now carry the defence, so: an IPv6 address counts as its /64 (`audit.client_ip`, also what the audit log stores); in production a request with no client address is refused (503) rather than skipping the limits; resends count towards the per-IP limit on code emails (20 per 15 minutes); parallel sign-ups for one email from one place are counted one at a time (an advisory lock).
        - **Still possible:** someone on the owner's own public IP (shared Wi-Fi, an office, carrier NAT) can use up that IP's limits for an hour; changing network gets round it. Inbox flooding has no ceiling across many IP addresses (25 code emails an hour per address per IP); a per-address cap would let anyone block the owner again, so it's left to the edge limits and a global send budget before production.
        - The new account's wrong-code counts start at creation (`password_changed_at` is set then).
        - The old migration deleted accounts left unverified (dev data only), and `users.email_verified_at` is required.
    - **Web or mobile** (question 33):
        - The app declares `platform` at sign-in and verify; the default is `web`.
        - A request with an `Origin` or `Sec-Fetch-Mode` header is always `web`, whatever it declares: browsers add these headers and page scripts can't remove them.
        - A trusted device keeps the platform it passed 2FA with, and sign-ins from its token use that.
        - Mobile sessions last up to 30 days but never past the device's trust; they have no server idle timeout, because the app's 15-minute background lock is the app's job.
        - Web sessions last 12 hours, with 30 minutes idle. The migration capped open sessions at 12 hours.
    - **Session messages:** `sessions.revoked_reason` keeps 1.2's inactivity message, 1.4's expiry message and the deactivated message on every later request, not just the first. Once a deactivated account is reactivated, its old sessions get the general "signed out" message instead.
    - **Sign-out** ignores a device token from a different account than the session's, and records `auth.signed_out` only when it ended a session or forgot a device.
    - **`/me`** no longer returns the date of birth or state: it answers before the policy gate. Story 11.1 will serve them behind it.
    - **Policy acceptance errors** carry one `details` entry per unticked policy (`AppError` now takes `details`).
    - **Email enumeration:**
        - sign-up's 409 is recorded as `auth.sign_up.refused` and counts towards the per-IP sign-up limit;
        - a reset that reuses the current password is recorded as `auth.password_reset.failed` and counts towards the reset limit;
        - signing up again with the same email starts a new attempt and leaves the others alone.
    - **Audit events added:**
        - `auth.code.limited` (the code-email cap);
        - `auth.code.rejected` (codes refused before comparing; this used to be `auth.code.failed`);
        - `auth.sign_up.refused`;
        - `auth.signed_out` when only the device token matched;
        - `platform` and `until_reset` in the sign-in and lock details.
    - **Self intake bridge:** until R2 copies the date of birth from sign-up, a self intake can't save a date of birth different from the account's. That keeps the Oracle's age band and "every account holder is an adult" true.

    Carried forward from the R1 reviews:

    - ~~**Phase 3b / R2:** an unverified account made before 4 Nov~~ and ~~**Phase 10:** purge unverified accounts~~: done, by creating accounts at verification.
    - **Known, left as is:**
        - `/auth/verify/resend` on a sign-in code doesn't check for a lock or a deactivated account, so it can email codes that verify will refuse (within the hourly cap). Refuse it there if the BA wants.
        - If the worker is down, expired sign-up attempts wait for it; the next purge job deletes them all.
        - A sign-up that starts while another attempt for the same email is being verified can leave an attempt for an email that now has an account. Verifying it answers "already exists", and it's purged within the hour.
    - **Before production:** `password_changed_at` comes from the app server's clock and audit times from the database's, so the servers must keep their clocks in sync (NTP).
    - **Before production (sign-up attempts):**
        - the trusted-proxy settings (Phase 1) are required, not hardening: behind an untrusted load balancer every client shares one IP, and the per email-and-IP cap and the per-IP limits would then block everyone;
        - the per-IP limits count, then insert, without a lock, so a burst of parallel requests can get past them by about the number of database connections; put an edge rate limit in front;
        - refused requests each add an audit row (`auth.rate_limited`, `auth.code.limited`); the edge limit also keeps those down;
        - a global code-email budget with alerts, and rate-limit keys that treat Gmail's dots and `+tags` as one address;
        - `pending_sign_ups.date_of_birth` is encrypted in Phase 4 with the other fields.
    - **Before production:**
        - the dropped `users.phone`, `users.zip_code` and `pending_sign_ups.zip_code` values stay in table files and backups until rows are rewritten; run `VACUUM FULL users, pending_sign_ups` if any real values were ever stored;
        - confirm the mobile app's HTTP client sends no `Origin` header (a Capacitor or Ionic webview does, and would get web sessions);
        - App Attest / Play Integrity if declared platforms need to be trusted.
- [x] **R1b Remove the ZIP code** (5 Nov stories, 1.1 and 11.1; done 2026-11-05, migration `2289dc4e401c`). A request that still sends `zip_code` gets 422, as for any unknown field (`/auth/signup/check` ignores it, as it ignores the other form fields):
    - drop `zip_code` from the sign-up request, `/auth/signup/check`, `pending_sign_ups` and `users`, in a migration that also deletes the stored values (dev data only);
    - the state message becomes "Please enter a valid state." (it was "Please enter a valid state and ZIP code.");
    - update the tests and `docs/PLAN.md`'s ZIP mentions (R1's decisions, Phase 4's encryption list, questions 8 and 47).
- [x] **R1c Bring the ZIP code back** (6 Nov stories, 1.1, 11.1, Super Admin and Admin 3.1; code built 2026-11-06, migration `b2d3f1f768bf`; tests not updated yet):
    - `zip_code` on the sign-up request and `/auth/signup/check` (step 2), on `pending_sign_ups` (NOT NULL) and `users` (nullable: accounts made between 5 and 6 Nov, teens' own accounts and transferred profiles' accounts have none, and the client can add it with Edit);
    - five digits or ZIP+4, spaces taken out, stored as typed. Every US ZIP code has five digits; what differs by state is the first three (the USPS prefix), so the ZIP code must belong to the state chosen (`app/core/zip_codes.py`, `zip_in_state`): a table of each state's prefixes, plus the few ZIP codes that use a neighbouring state's prefix (Fishers Island NY 06390, Texarkana AR 75502 and others). Checked against an undated min-and-max-by-state reference page on 6 Nov; a Census ZIP-to-state file would confirm it (question 32). Unused prefixes inside a state's range pass, so a real ZIP code is never refused;
    - sign-up and `/auth/signup/check`: a missing or invalid ZIP code, or one from another state, gets "Please enter a valid state and ZIP code." (field `zip_code`), and a missing or invalid state still gets "Please enter a valid state." (field `state`), since the story keeps both;
    - Profile & Account (`GET`/`PATCH /me/profile`): shows `zip_code`; an empty, null or invalid one gets "Please enter a valid ZIP code.", and so does one that doesn't belong to the state the client will have after saving (422 `zip_code_not_in_state`): changing only the state re-checks the ZIP code on file, so the app asks for the new state's ZIP code too. Accounts with no ZIP code can change the state alone. The ZIP code doesn't change the age rules. The audit event lists the field name only;
    - Client Details' Account section (`zip_code`, for Admins and the Super Admin) and Export My Data's account details.
- [x] **Two small additions from the second comparison with the team's API** (5 Nov):
    - every code response (sign-up, sign-in, resend) has `resend_after_seconds`, how long until "Resend code" works (60, from `code_resend_seconds`), so the app's countdown follows the server;
    - `/me` returns the account's `role` (always `client` until Phase A).
    - Not taken, on purpose: a 6-digit code to reset a password (1.3 has a link only, and a code can be guessed); checking the reset link with `GET ?token=` (the token would reach server logs); one call that saves the message and streams the reply (ours saves and safety-checks first, shows the Health Consent in between, and retries safely); `status` and `sources` stream events (no story asks for them; add when the Oracle provides citations); a single onboarding without a profile (the 4 Nov stories need one per profile).
- [x] **Routes under `/api/v1`** (4 Nov, to match the team's API): every endpoint, `/health` included, is under `/api/v1`; `/docs` and `/openapi.json` stay at the root. Paths in this file are written without the prefix. A breaking change to an endpoint would go under `/api/v2`, so older app versions keep working.
- [x] **Message feedback and deleting conversations** (4 Nov, asked for by the user after comparing with the team's API; not in the 4 Nov stories, questions 44 and 45):
    - `PUT /conversations/{id}/messages/{message_id}/feedback`: a thumbs up or down (`up` or `down`) on one of the Oracle's replies, with an optional comment (2,000 characters). Giving it again replaces it; `DELETE` takes it back. Each message in `GET /conversations/{id}` shows its `feedback`. The comment is health data: never logged or audited (the audit event says only the rating and whether there's a comment). Nobody reads the feedback yet; the Admin stories don't mention it.
    - `DELETE /conversations/{id}`: the conversation disappears from the client's lists and lookups at once (404 afterwards), and the Oracle stops using it as an earlier conversation. Its messages are kept (`conversations.deleted_at`) until Phase 10's purge, because 3.2's escalation records may have to be kept for 6 years (question 27). Its messages still count towards the rate limits, and their safety checks still run. It works for a turned-off family member too (deleting isn't using the profile); a database failure says "We couldn’t delete this conversation just now. Please try again." (5.2's wording, adapted). The app should confirm first, for example "Delete this conversation? This can’t be undone." (5.2's wording, adapted); it shouldn't say "permanently". A reply still streaming when the conversation is deleted isn't saved.
    - Feedback that's sent again unchanged writes nothing.
    - **For later phases:**
        - **3.2:** refuse `DELETE` while an emergency or crisis hold is open on the conversation, or deleting it would get round the hold. Escalation records must not be deleted along with messages or conversations (no CASCADE foreign key to them, like `deletion_requests`).
        - **Phase 5:** summaries and provider notes made from a deleted conversation: delete them with it, or keep them and hide "Back to conversation", as 5.2 does for visit logs.
        - **Phase 10:** the export and the purge cover feedback comments and conversations marked deleted (they're still held). A thumbs-down is not 3.2's "The Oracle got it wrong" path, and the app mustn't offer it as one.
    - "We couldn’t find that message." for a message that isn't one of the Oracle's in that conversation (not in the stories).
- [ ] **R2 Profiles and family** (2.1, 2.2, 4.2, 8.1, 8.2, 9.1):
    - **Self intake:**
        - Drop date of birth: it comes from sign-up and is copied into the self profile, which can't change it.
        - Remove the under-13 refusal.
    - **New codes:**
        - Sex at birth adds `prefer_not_to_say`.
        - Gender becomes `woman`, `man`, `non_binary`, `agender`, `not_listed` (with a write-in), `prefer_not_to_say`.
        - The gender write-in goes with `not_listed`; the pronoun write-in stays with `other`.
        - Existing rows are dev data only, so the dev database is reset rather than migrated.
    - **Teen step:**
        - The family intake asks `teen_profile_choice` (`own_account` or `managed`) after the date of birth, for teens only.
        - `own_account` is refused until Phase 3b.
        - A teen is 13 to 17 (question 22).
    - **Plans:**
        - `individual` (no family members) and `family` (3 places) replace `basic`.
        - "Family plan" is written with a capital F, and "Upgrade to add someone." is used when no name is known.
    - **New wording:** "Please choose an option to continue.", the date-of-birth and teen-choice messages, the gender write-ins, the limit messages, and "contact the support team".
    - **Option lists from the backend:** codes, labels, and They/Them pre-selected for Agender and Not listed, so they can change without an app release.
- [ ] **R3 Conversations** (3.1):
    - **Contract codes:** the age bands renamed `under_13`, `teen`, `adult`, `60_plus` (teen means 13 to 17), and the new codes in `ProfileContext`. Add the `age_group(date_of_birth)` helper to `app/core/ages.py` (moved from R1) and use it in place of `age_band` in `app/conversations/service.py`.
    - **Safety order:** an emergency or crisis is shown before the Health Consent (built with 3.2).
    - **New widgets:** the privacy notice, disclosure box, product links (adults only) and "Consult with support team".
    - **Starters:** add "Hormone imbalance".
    - Uploads stay out: the stories removed them.
- [ ] **R4 Story numbers** in code comments and `CLAUDE.md` follow the new numbering.

### Phase 3: Conversations and safety

- [ ] Agree the `app/oracle/` contract with the AI team. The backend's proposal is `app/oracle/contract.py` (see the 3.1 decisions below).
- [x] Profile context for the Oracle (`profile_context` in `app/conversations/service.py`): first name, the advocate's first name, relationship, age band, sex at birth, gender identity and pronouns with their write-ins. Picked field by field; no date of birth, and never the advocate consent option.
- [x] Conversation endpoints require a usable profile: intake complete, not turned off, no deletion request (`UsableProfile` in `app/profiles/dependencies.py`).
- [x] **3.1 Start or Continue a Conversation**:
    - `GET /profiles/{profile_id}/conversations/new` gives the opening question and starter questions.
    - `POST /profiles/{profile_id}/conversations` starts a conversation with its first message.
    - `POST /conversations/{conversation_id}/messages` adds a message.
    - `POST /conversations/{conversation_id}/reply` streams the Oracle's reply as server-sent events.
    - `GET /conversations/{conversation_id}` returns the full history, and `GET /profiles/{profile_id}/conversations` the list.
    - `GET` and `POST /profiles/{profile_id}/health-consent` read and accept the Health Consent.
    - Uploads in chat wait for Phase 6. Saving details to the health profile is Phase 4. The Oracle's behaviour (routing, never repeating, interactions, lean body mass, cards, guardrails) is the AI team's.

Decisions made while building 3.1:

- **Two steps per message.** Sending saves the message and runs the safety check, then answers with `next`: `reply`, or `health_consent` to show the consent first. The reply is a separate request that streams server-sent events: `delta` (text), `widget` (structured parts), then `done` (the saved message) or `error`. After a lost connection the app asks for the reply again: a saved one is sent whole; an unsaved one is generated again.
- **No message is ever lost.** The client message is saved before the Oracle is called. A resend with the same `client_msg_id` returns the saved message (200), and is answered before the trial and rate checks.
- **The safety check** runs on every message after it's saved, with no transaction or lock held, and gets only `is_self` and the age band. Only the first successful result is stored, so two checks of one message can't overwrite each other. If it fails or answers an unknown level, the level stays empty, and:
    - a worker job saved with every message (`conversations.safety_check`, the message id only) retries it a minute later, even if no reply is ever asked for;
    - the reply step re-checks every client message the Oracle would read, not only the last one, and gives no reply while any of them is unchecked.

    Acting on the level is 3.2.
- **A conversation starts with the client's first message**, after the Oracle's opening question, which is saved as the first message. There are no empty conversations.
- **Welcome back:** `GET /conversations/{id}` returns the story's "Welcome back, …" line when the conversation has a topic and is picked up after 12 hours (`WELCOME_BACK_AFTER_HOURS`). It's saved into the conversation when the client sends their next message, so the Oracle knows what they're answering.
- **The topic** is written by the Oracle after its first reply, to fit "Last time we talked about [topic]"; the apps capitalise it for the list. Until then it's null, and the apps show their own placeholder.
- **Starter questions** come from `app/conversations/starters.py` (the story's examples until The Oracle's team supplies lists), not from the Oracle, so nothing about the profile leaves the backend before its Health Consent and opening the screen costs nothing.
- **The Health Consent** is accepted per profile and per version, by the account that holds the profile, through one endpoint for the client and a family member; the two wordings are the apps'. A new version is asked for again at the next reply. An outdated version id gets 409 `health_consent_outdated` so the app fetches the new one.
- **The Oracle contract** (`app/oracle/contract.py`):
    - replies stream as text pieces plus `widgets`: tap-to-answer options, sliders, the Add Medicine widget, Skip, the checklist offer and in-chat cards. Their shape is for the AI team and the apps to agree; the backend stores and forwards them.
    - A client message can carry an `answer` (what was tapped) with its text.
    - Each reply gets the conversation's latest 60 messages, and the latest 20 messages of the profile's 3 most recent other conversations, so the Oracle doesn't ask again for what it was told.
    - The client raises `OracleError` with no request content; the backend logs only the class name.
- **Gates:** sending and replies need a usable profile and an active trial or plan; replies also need the consent. Gates are checked again before a reply is saved. Reading past conversations always works, including after the trial (open question 11) and for turned-off or deletion-requested members (9.2 only says those can't be used).
- **Cost and capacity:**
    - 60 client messages per hour and 20 new conversations per day per account.
    - One reply generated at a time per message, claimed for 2 minutes and released when it fails or the client disconnects. A stream releases only its own claim.
    - At most 5 attempts, counted only when the Oracle is actually asked (a busy server doesn't count). After that, a resend answers `next: "send_again"` and the app sends the text as a new message.
    - The reply's generator runs in the thread pool and is closed there, including on a disconnect, so its cleanup never blocks the event loop.
    - The Oracle client must enforce its own time limits (`contract.py`): the backend can't interrupt a call that's blocked waiting.
    - A reply may run for 90 seconds, and one server process streams at most 20 at once.

    All are settings.
- **Names:** sign-up first names, family member first names and write-ins are NFKC-normalised, lose hidden characters (zero-width, bidi, line separators, control characters), and are capped at 100 characters. A name with no letter counts as empty. `profile_context` cleans them again for older rows.
- **Messages not in the stories:**
    - "Please type a message to send."
    - "That message is too long. Please keep it to 8,000 characters or fewer."
    - "That answer is too long to save."
    - "We couldn’t find that conversation."
    - "Please finish setting up this profile first."
    - "[Name]’s data is being deleted, so their profile can’t be used."
    - "You’re sending messages faster than I can keep up with. Please wait a few minutes and try again."
    - "You’ve started a lot of conversations today. Please carry on in one of them, or try again tomorrow."
    - "I’m still replying to that message. Please wait a moment."
    - "I couldn’t reply to that message. Please try sending it again."
    - "Please keep this to 100 characters or fewer." (names and write-ins)
    - A failed reply or safety check uses 9.2's "We couldn’t do that just now. Please try again."
- **`GET /me/entitlements`** has `trial_ended`, so the apps lock the message box without comparing dates themselves.
- **`ENVIRONMENT`** must be `development`, `test` or `production`; anything else stops the app, so a typo can't run the fake Oracle or console email with real data.

Carried forward from the 3.1 reviews:

- **3.2:** `prepare_reply` is where the safety hold goes; today it replies to any level.
- **Before production:**
    - Make the Oracle client and the reply stream async (the database calls in a thread pool), so a slow AI service can't hold worker threads. Add SSE heartbeats and proxy timeouts.
    - Edge or WAF rate limits and a request body size limit; per-account token budgets and cost alerts.
    - The real Oracle client: a BAA, no data kept after the call, its own time limits, and `OracleError` without request content.
    - `lock_timeout` and `idle_in_transaction_session_timeout` on the database role.
    - Alert the team when a `conversations.safety_check` job fails for good: that message was never checked. During an Oracle outage, back off the reply step's re-checks, and add a per-account limit on `/reply`.
    - Clear out finished jobs; every message adds one.
- **Phase 4:** encrypt message text, answers, widgets and topics with the other health fields. The Hypothalamus Symptom Check list belongs with 7.1's checklists.
- **Phase 8:** a client back on the trial plan can still talk about family members; check the plan per profile when plans change.
- **Phase 10:** 12.4's export and purge include conversations, messages and Health Consents. Transferring a profile to another account needs a new Health Consent (the consent check already requires the current account holder).
- [ ] **3.2 Escalation / Emergency Detection** (as of 4 Nov):
    - The safety check runs on every message, before any reply and before the Health Consent. We keep our 2-second limit, though the story no longer sets one.
    - **Emergency or crisis:** shown before the consent. The conversation is paused until the client picks an option: "I’ve called for help" or "I’ve reached out for help", or "I’m safe now".
    - **Urgent:** advice to see a provider, and the conversation continues.
    - **Numbers:** US only (911, 988, and Poison Control where relevant); outside the US, "Please call your local emergency number now."
    - **Records:** an escalation for the support team to review, kept 6 years. No follow-up and no check-ins.
    - The parent's notice about a teen's emergency comes with Phase 3b.

### Phase 3b: Teen accounts (after 3.2)

- [ ] **1.5 Teen Sign Up (Parent Invite)** and **2.3 Onboarding (Teen)**, with the teen parts of 1.2, 2.2, 3.1, 4.2, 8.1, 8.2 and 12.2:
    - **A separate account:** an invited teen gets their own account (`account_type = teen`) and profile. The parent's side holds only a link: first name, relationship, invite email and status. The teen's profile never belongs to the parent's account, so `OwnedProfile` keeps it out of the parent's reach.
    - **Invites:** a hashed, single-use, time-limited token in the URL fragment, replaced on resend. The teen takes a place from the moment of the invite, checked under the account lock.
    - **The teen's sign-up and onboarding:** sign-up from the invite (no emailed code, no policies, no trial), then onboarding (sex at birth, gender, pronouns).
    - **Access gate:** the teen can use the app only while all of these hold:
        - the parent's Family plan is active;
        - the parent's policies are accepted and consent hasn't been revoked;
        - the link isn't turned off or removed;
        - the teen is under the age of majority.
    - **When the gate is shut** (5 Nov stories: removed, turned off, Family plan ended, consent revoked, or the parent hasn't accepted updated policies), the teen can still sign in, but only Privacy & Data works: Export My Data and Delete My Information (11.4). Every other endpoint refuses with "Your access is paused. Please ask your parent or guardian. You can still download your data or ask for it to be deleted here." A teen's own deletion request arrives in the support queue as a Teen Deletion from the app (Super Admin 5.2); a parent can't ask for it.
    - **Consent and the Oracle:** the parent's Health Consent counts for the teen, and the Oracle's context marks a teen with their own account (education only).
    - **Manage Family:** cards for invited teens (invite sent, joined, turned off, access paused), with resend, turn off and on, and remove (which deletes no data).
- [ ] **1.6 Teen Reaches the Age of Majority** and **2.4 Onboarding (Teen Reaching the Age of Majority)**, after Phase 8 because they need the plans:
    - a daily age check, and the two-week reminder (sent in Phase 9);
    - the account becomes an adult one with a trial, and the parent's place is freed;
    - converting the account in place keeps the history without moving it (question 39).

### Phase 4: Health profile

- [ ] **6.1 View, Edit & Complete Health Profile** (was 7.1):
    - **Questions and answers:**
        - the question rule set lives in config;
        - "Complete my profile" is a form, filled in section by section;
        - each answer records its source: the client, or the conversation.
    - **Body follow-ups:** only for these paths, after a privacy notice:
        - Path A: sex at birth is Intersex or Prefer not to say;
        - Path B: gender differs from sex at birth;
        - gender is Prefer not to say.
    - **Completion %** counts only the questions that apply.
    - **Privacy and security:**
        - the client can delete sensitive sections;
        - sensitive fields get app-level encryption;
        - every change is audited;
        - teen privacy rules apply.
    - My Health is greyed out during the trial.
    - Also the confirm-before-saving flow for facts the Oracle picks up in chat (3.1, 3.3).
    - **Blocked by** the routing rule set (question 1).

### Phase 5: Oracle outputs

- [ ] **3.3 View Personalised Guidance Summary**:
    - one summary per conversation, updated rather than repeated;
    - a Recommendations section for adults only (links, no prices), never during a safety hold;
    - typed lab values explained, never interpreted;
    - one disclosure box;
    - the PDF locked during the trial.
- [ ] **3.4 Generate Provider-Ready Notes**:
    - the specialty list lives in config;
    - the header gives the first name only, and the backend fills it in, so the Oracle never needs the date of birth;
    - an appointment card, and reminders.
- [ ] **3.5 View, Edit & Download Provider-Ready Notes**:
    - a PDF and copy-as-text, both with the disclosure box;
    - the first name in the file name;
    - locked during the trial;
    - a teen with their own account can download their notes; the parent can't see them.

### Phase 6: Visit notes

- [ ] **5.1 View, Download & Manage Visit Notes**: one list, upcoming appointments first and then newest first, searched in under 1 second. No Labs or Attachments tabs. Greyed out during the trial.
- [ ] **5.2 Log Provider Visit Outcome**: a visit log with medicine changes and next steps, and no uploads. Locked during the trial.
- The old 6.1 Manage Documents & Labs was removed from the stories on 4 Nov, so there's no file storage, upload checking or lab reading to build.

### Phase 7: Wellness Plan

- [ ] **7.1 View & Update the Wellness Plan** (was 8.1 and 8.2 Healing Plan):
    - **Creation and updates:** the system creates the plan and updates it after a new summary, a logged visit or a profile change.
    - **Versions:** only the latest is shown, but every update is recorded.
    - **Wellness Protocols library:** links only, with no prices.
    - **Age rules:**
        - no products or cleanses below the age of majority;
        - education only for teens;
        - no plan during the trial.

### Phase 8: Billing

- [ ] **9.1 Start Free Trial & Activate Subscription** (was 10.1):
    - the Individual and Family plans, paid through Stripe or in-app purchase (question 2);
    - per-member add-ons on the Family plan;
    - real entitlements replacing the stand-in, and receipts;
    - features greyed out during the trial.
- [ ] **11.3 Manage Billing & Subscription** (was 12.3):
    - the payment method, invoices, and cancel and resume;
    - upgrades, and a downgrade from Family to Individual at the next billing date;
    - failed renewals and the grace period;
    - when the Family plan ends: the system turns managed members off and pauses invited teens, and restores them when the plan restarts.
- [ ] 1.6 and 2.4, from Phase 3b, once the plans exist.

### Phase 9: Notifications

- [ ] **12.1 Notifications & Reminders** (was 13.1):
    - **Channels:** in-app, push and email, with no SMS.
    - **Preferences:** these can't be turned off: billing, requests, account, and every teen safety and access notice.
    - **Teen notices:** to the parent, and to the teen.
    - **When not to send:**
        - never for turned-off or deleted profiles, or while consent is revoked;
        - no check-ins after an emergency or crisis.
- [ ] **12.2 Policy Updates** (rest; was 13.2):
    - when a version is published, email every client and end all sessions;
    - an updated Health Consent is accepted before sign-in for the client's own profile, then re-confirmed for each family member and invited teen;
    - teens are paused until the parent accepts.

### Phase 10: Account and support

- [ ] **10.1 Contact the Support Team & Consult With Support Team** (was 11.1):
    - support requests, including knowledge gaps and requests to talk to a person from the Oracle, emailed to the team within 1 minute;
    - consultation requests as a form, booked and paid outside the app.
- [ ] **11.1 View & Edit My Profile** (was 12.1):
    - edits to the first name, state and ZIP code (the ZIP is back since 6 Nov, R1c);
    - a state change re-checks the age of majority, with the story's confirmation;
    - email change requests.
- [ ] **11.4 Revoke Consent / Delete Account** (was 12.4):
    - an in-app export, available straight away;
    - revoking consent keeps the data and pauses invited teens; consent can be given again;
    - delete everything, stay advocate-only, or transfer profiles to members at the age of majority for their state;
    - a teen's own deletion request;
    - a purge job that respects legal holds, also covering the family-member deletions requested in 8.2, conversations the client deleted, and feedback comments.

### Phase 11: Home dashboard

- [ ] **4.1 View Home Dashboard**:
    - **One endpoint per profile:** returns every widget in order, each with flags for whether it's shown and whether it's locked (the trial locks most of them).
    - **My Family:** the Family plan's card, including invited teens' status.
    - **Teens:** a teen version of the dashboard.
    - Built last, because it reads from almost every phase.

### Phase A: Admin and Super Admin (code built 2026-11-06, see Build status)

Added on 4 Nov after comparing with the team's API, which has admin invitations and a knowledge-base endpoint. These are the Admin and Super Admin stories (`docs/requirements/admin-user-stories.md`, `super-admin-user-stories.md`): a separate admin panel, built after the Client phases unless the team says otherwise. The code is built (A1 and A2 in the Build status table); the plan below was the starting point.

- **A1 Roles and admin sign-in:** a `role` on accounts (`client`, `admin`, `super_admin`; the column already exists with `client`). Admins sign in with a code at every sign-in, on every device, and are signed out after 15 idle minutes (Super Admin 1.1; Admin sign-in rules). Admin endpoints get their own dependency, and `/me` returns the role.
- **A2 Admin invitations** (Super Admin "Manage Admins", Admin 1.1): the Super Admin invites an admin by email; the invite link opens a setup screen (read the invite, set a password, accept). Invite tokens are stored hashed and single-use, like reset links.
- **A3 Knowledge base management** (Super Admin epic 6: view and edit content, add content, knowledge gaps): content listing, approvals (Admins' edits wait for the Super Admin), sources and syncs, knowledge gaps from the Oracle. Most of it touches the AI team's store (pgvector), so it's planned with them.
- **Before starting:** map every Admin and Super Admin story into phases here, like the Client ones, and widen `CLAUDE.md`'s scope.

## Who else we depend on

- **AI team**: the `app/oracle/` contract, the safety classifier speed (our 2-second limit), the safety test set that 3.2 asks for before every release, the knowledge base (approved content and pgvector embeddings), and the question routing rules.
- **Frontend and mobile**: the error format, how the token is carried (Bearer header or cookie), deep links for verify and reset emails, push token registration, the active profile.
- **The Oracle's team and the BA**: the routing document, prices, trial length and limits, policy texts, and the answers to the BA questions doc.
- **Vendors**: email, push, hosting and database (Azure, per the 4 Nov stories), and the LLM provider each need a BAA if they touch PHI. Stripe needs no PHI. No SMS, OCR or file storage any more.

## Open questions

**6 Nov:** the build added about 108 new questions, kept in each `docs/decisions/*.md` file (the Build status table counts them) until the BA has seen them.

These come from reading every Client story. Questions 1–21 were raised against the 30 Oct stories and are marked where the 4 Nov stories answered them; questions 22–41 come from the 4 Nov stories, and 42 onwards from building them.

| # | Question | Stories | Blocks |
| --- | --- | --- | --- |
| 1 | **Partly answered (4 Nov):** the gender, sex and age lists now agree across the stories, and 3.1 links the routing document. We still need the routing rule set itself: which questions apply to whom. | 2.x, 3.1, 6.1 | Phase 4 |
| 2 | Stripe (card, Apple Pay, Google Pay) or App Store / Play in-app purchase? Apple generally requires in-app purchase for digital subscriptions sold inside iOS apps. | 9.1, 11.3 | Phase 8 |
| 3 | **Answered (4 Nov):** extra family members are a paid per-member add-on on the Family plan; trial and Individual clients can't add any. | 8.1, 9.1 | Resolved |
| 4 | **Answered (4 Nov):** the policy screen comes before sign-in. `next-step` keeps `policy_update` as a fallback for apps that skip it. | 1.2, 12.2 | Resolved |
| 5 | **Obsolete (4 Nov):** an under-age person is stopped at sign-up, before any account exists. | 1.1 | Resolved |
| 6 | Where does an unverified email fit in the after-sign-in order? Answered by design: sign-in sends the verify code before a session exists. | 1.1, 1.2 | Resolved |
| 7 | **Answered (4 Nov):** only the current password can't be reused. | 1.3, 11.2 | Resolved |
| 8 | Reminders need the client's time zone. **Partly answered:** sign-up collects the state, which gives it for most clients; the ZIP code (back on 6 Nov) narrows it further. States that span two time zones (Florida, Texas, Tennessee, Kentucky, Indiana and others) need another source: the device's time zone, sent by the app? | 3.4, 12.1 | Phase 5 |
| 9 | Missing timings: appointment reminder lead time and follow-up, trial-ending reminder, complete-profile reminder. **Partly answered:** the age-of-majority reminder is two weeks before. | 3.4, 5.2, 9.1, 12.1 | Phase 9 |
| 10 | Are the lean body mass and Healthy Four formulas fixed maths (backend) or LLM output? The Drugs.com part is obsolete: medicines now only link to it. | 3.1, 7.1 | Phases 3 and 7 |
| 11 | Trial: one per person? Is a Wellness Plan built from trial summaries when they subscribe? **Partly answered:** the trial covers the client's own profile only, history is kept after it, and there's no plan during it. | 9.1, 7.1 | Phase 8 |
| 12 | Export format? **Partly answered:** it's in the app, immediate, its contents are listed, and a parent's export excludes invited teens. 11.4 still mentions a "secure download link" and an "availability period". | 11.4 | Phase 10 |
| 13 | How long is the grace period after a failed renewal? (The "member discount" was removed.) | 11.3 | Phase 8 |
| 14 | **Obsolete (4 Nov):** uploads, documents, labs and lab reading were removed. | — | Resolved |
| 15 | Can one conversation have several sets of provider notes? | 3.4, 5.1 | Phase 5 |
| 16 | **Answered (4 Nov):** every account holder is at or over the age of majority, and teens with their own account can't add family members. | 1.1, 8.1 | Resolved |
| 17 | Should the advocate consent options depend on the member's age? For example, "[Name] has agreed" for a 4-year-old, or "parent or legal guardian" for an adult partner. | 2.2 | Nothing (validation only) |
| 18 | When a family member's deletion is requested, should their place be freed and should they be hidden from the panel straight away, rather than when the support team completes the deletion (the story's timing, which we follow)? Can the client cancel a pending request? | 8.1, 8.2 | Nothing (small change) |
| 19 | Changing a family member's relationship in View & edit asks the advocate consent again (we built it that way). Is that right, and should a first-name change ask too? | 2.2, 8.2 | Nothing (small change) |
| 20 | The safety check gets only whether the profile is the client's own and its age band. Is anything else allowed to reach the AI service before the Health Consent? (4 Nov confirms the check runs before the consent.) | 3.1, 3.2 | Nothing (built minimal) |
| 21 | Message and conversation limits per account (60 messages an hour, 20 conversations a day), the 8,000-character message limit and the 12-hour "welcome back" gap are our guesses. Are they right? | 3.1 | Nothing (settings) |
| 22 | **Reversed (11 Nov):** the 4 Nov "18 everywhere" decision is replaced by the stories' per-state rule. Sources: Client 1.1's Age Check (18 in most states and DC, 19 in Alabama and Nebraska, 21 in Mississippi), 3.1 and 11.1's age rules, and the BA's routing document ("Revised Intake Routing" and "Answers and Fixes": the user's state's age of majority, "not a flat 18"). Built in `app/core/ages.py` (docs/decisions/state-age-of-majority.md). **Still open:** (a) a family member has no state of their own: we use the account holder's; is that right? (b) the routing document says the state comes "from billing address"; we use the state given at sign-up and edited in 11.1; (c) what if a teen's own date of birth at setup makes them under 13 or already of age? | 1.1, 1.5, 1.6, 2.2, 8.1 | Phase 3b |
| 23 | **Gender options:** which genders follow body Path B (Non-binary, Agender, Not listed)? Are Girl and Boy only labels for Woman and Man? Do pronouns get "Prefer not to say" (3.1 lists it; 2.1–2.3 don't)? Does "options can change without an app release" mean labels and order, or new codes too? | 2.1–2.3, 3.1, 6.1 | Phase R |
| 24 | **The safety hold:** is it per conversation, or does it also block new conversations and switching profile? Is a message typed during the hold saved and checked, or refused? How does "The Oracle got it wrong" work: typed, or a button? Does it mark a false alarm? What's shown after an option is chosen (the old "I’m glad you’re safe…" is gone), and does the Oracle then answer the message that started the hold? | 3.2 | 3.2 |
| 25 | **Safety wording:** is urgent advice shown before the Health Consent or in the first reply? What's the full emergency text for a family member, and the crisis text when an advocate describes someone else's crisis? When is Poison Control "relevant", and what does it say? What's shown when the safety check can't run? | 3.2 | 3.2 |
| 26 | **Outside the US:** how does the app tell the backend that the device is outside the US (a flag per message?), and does 988 change too? | 3.2 | 3.2 |
| 27 | **Escalation records** must be kept 6 years (3.2), but 8.2 and 11.4 promise permanent deletion, including backups. What remains after a purge? | 3.2, 8.2, 11.4 | 3.2 |
| 28 | **After an emergency or crisis,** "no check-ins": does that also stop the 2-week summary follow-up, the 30-day inactivity check-in and Wellness Plan check-ins? Can the parent's notice about a teen go by push and email, given 12.1's "general message only"? | 3.2, 12.1 | 3.2, Phase 9 |
| 29 | **Symptoms:** structured or plain text? Who serves the Hypothalamus Symptom Check list? Are ticked symptoms saved to the health profile? | 3.1, 6.1 | Phase R |
| 30 | **Welcome back:** our fixed line (no longer in the stories), or the Oracle's own words? | 3.1 | Nothing (built) |
| 31 | **Message conflicts:** the wrong-code and expired-code texts differ between 1.1 and 1.2, but there's one verify endpoint (we'd pick by purpose); trial ended is "…keep using Your Oracle." in 2.4 and "…keep talking with me." in 3.1 and 9.1; the family gender write-in is "describes their gender" in 2.2 and "identifies" in 8.2; the family limit text differs between 2.2/4.2 and 8.1. 1.5's "Upgrade to invite [Name]" looks unreachable. Sign-up has no message for an empty email, an empty confirm password or a non-US country. | 1.1, 1.2, 1.5, 2.2, 2.4, 3.1, 4.2, 8.1, 8.2, 9.1 | Phase R |
| 32 | **Sign-up details:** which states are valid (50 states and DC only, or territories and military addresses too)? Is ZIP+4 allowed, and must the ZIP match the state? (Dropped on 5 Nov, back on 6 Nov. **Decided by the user on 6 Nov:** the ZIP code must belong to the state; R1c checks its USPS prefix and accepts ZIP+4.) Is a separate step-2 age check endpoint fine, and should refused attempts be logged? No story collects a last name any more: drop the column? **Built in R1 as:** 50 states and DC; a check endpoint; refusals not logged; the column kept. | 1.1, 11.1 | Phase R |
| 33 | **Web vs mobile sessions:** how does the backend know the platform? A platform the app declares can be faked by a browser. Is that acceptable? **Built in R1 as:** the app declares it, browsers (requests with `Origin` or `Sec-Fetch-Mode`) always get web, and a trusted device keeps its platform. Still open: is the mobile app native (React Native, Flutter, Swift/Kotlin) or a webview (Capacitor, Ionic)? A webview would get web sessions. | 1.2 | Phase R |
| 34 | **Teens, answered by the prototype (4 Nov):** the teen journey is name → age (date of birth and city) → password with the email locked → teen basics → chat, so teens go straight to their own chat, as 2.3's criteria and 1.5 say. Still open: "Complete my intake" opens My Health, which the trial greys out, and "For a family member" at the first onboarding always meets the upgrade prompt on the trial. Intended? | 2.1–2.3, 9.1 | Phase R |
| 35 | **Teen invites:** for which relationships (only Child)? How long is an invite valid? Does the teen's setup need an emailed code? What if the email already has an account (an adult's, or another family's teen)? Teens give city, state and country (5 Nov: nobody gives a ZIP now): US only? (The prototype's city search also lists UK and Australian cities.) 1.5 says "every feature is available" but also lists what teens can't do. | 1.5, 2.2 | Phase 3b |
| 36 | **Places and invited teens:** does a pending or expired invite hold its place for ever? Does removing a pending invite free it? Do invited teens count for the advocate-only last-member rule, and for 11.4's "family members exist"? | 8.1, 8.2, 11.4 | Phase 3b |
| 37 | **Mostly answered (5 Nov):** every teen who's lost access (removed, turned off, Family plan ended, consent revoked, parent's policies pending) can sign in and sees only Privacy & Data, with the long paused message. Still open: can a paused teen finish onboarding (1.2's order says onboarding comes first)? The leftover short messages are question 48. | 1.2, 1.5, 8.2, 11.4, 12.2 | Phase 3b |
| 38 | **Teens and consents:** when does the parent confirm the Health Consent for an invited teen? The policy screen before sign-in doesn't know a teen is signing in. Are clients who never accepted a Health Consent shown an updated one before sign-in? | 1.5, 3.1, 12.2 | Phase 3b, Phase 9 |
| 39 | **1.6 and 2.4:** convert the teen's account in place (our proposal: the history never moves) or create a new account and move the history? Same email? New password or code? What about an aged-out teen who never creates an account: their place, export and deletion? Which channels carry the two-week reminder, and what about 29 February birthdays? | 1.6, 2.4 | Phase 3b |
| 40 | **Managed teens over time:** can a parent turn a managed teen (or an under-13 who turns 13) into an invited teen? What happens to a managed teen at the age of majority? | 1.6, 2.2, 8.2 | Phase 3b |
| 41 | **After "stay as advocate only":** can the client recreate their own profile later? Are their date of birth and state kept? Family members' age groups need the state. | 11.4 | Phase 10 |
| 42 | **Sign-up's "already exists" message** tells anyone that an email has an account at a hormone-health service. R1 rate-limits it per IP. Would the BA accept OWASP's pattern instead: sign-up always answers "check your email", and the owner gets an "you already have an account" email? | 1.1 | Nothing (built) |
| 43 | **Answered by design (4 Nov):** a sign-up that's never verified is deleted 60 minutes after its last code. The BA can change the time (`pending_sign_up_minutes`). | 1.1 | Resolved |
| 44 | **Message feedback** (built on the user's request, not in the stories): is thumbs up or down with an optional comment what's wanted? Who sees it (the Super Admin's analytics? the AI team?), and for how long is it kept? Is it allowed on a family member's or a teen's conversation? Whoever reads it: comments are health data, never go to third-party analytics, aren't used while consent is revoked (11.4), and a teen's stay with the teen's account. | 3.1, Super Admin analytics | Nothing (built) |
| 45 | **Deleting a conversation** (built on the user's request, not in the stories): should it be possible? If so, what's erased and when, given 3.2's 6-year escalation records and 8.2's and 11.4's permanent deletion? Should the app ask for confirmation, and with what text? Can a parent delete a teen's conversation? Is a deleted conversation in the 11.4 export? Can it be deleted during a safety hold, and what happens to its summaries and provider notes (3.5, 5.1)? | 3.1, 3.2, 3.5, 5.1, 8.2, 11.4 | Phase 10 |
| 46 | **Sign-up codes can be guessed slowly:** with no per-email lock (it would let anyone block the owner's sign-up), someone using many IP addresses could eventually create an empty account on an email they don't own; the owner recovers it with Forgot password. Should the code email also carry a link with a long token, which can't be guessed? | 1.1 | Nothing (built) |
| 47 | **Taking back an account someone else verified:** after Forgot password, the account still has the other person's first name, date of birth and state, and the self intake can't change the date of birth. Should the first reset of an account that never finished onboarding let the owner re-enter the sign-up details, or should support correct them (an 11.1 request)? | 1.1, 1.3, 11.1 | Phase R (R2) |
| 48 | **Paused-teen messages after the 5 Nov update:** 12.1's notice to the parent that a teen's access is paused or restored now carries the teen's own message ("Your access is paused. Please ask your parent or guardian..."). What should the parent see? The old texts were "[Name]’s access is paused because your Family plan has ended. Renew to restore it." and "[Name]’s access has been restored." The short paused message is still in 11.4 (beside the long one), in 12.1's notices to the teen and in 12.2: is the long one meant everywhere? Two typos: 8.2 repeats "Teen’s access turned off (shown to the teen):" inside the message, and 12.2 says "our access is paused". | 8.2, 11.4, 12.1, 12.2 | Phase 3b |
| 49 | **Health information in Client Details** (6 Nov): Super Admin 3.1 now adds "Health Information: includes health information only which would get updated as the user converse with the Oracle.", but the same story's requirements still say Client Details shows "no health information", and Admin 3.1 still forbids it. Which is right? If it stays: is it the health profile answers only (not conversations, summaries or notes)? Do Admins see it? Is each view audited, and is the HIPAA minimum-necessary rule met for the support team's work? | Super Admin 3.1, Admin 3.1 | Phase A |
