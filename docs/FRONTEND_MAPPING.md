# Frontend to backend mapping

How the screens of the design team's prototype ([Ibrahim-tk/Deborah-app](https://github.com/Ibrahim-tk/Deborah-app), live at your-oracle-clinician.vercel.app) map to this API, for whoever builds the real apps. Mapped on 5 Nov 2026 against the prototype's `main` (`7b685d4`).

**About the prototype.** It's a frontend-only design prototype ("No backend, ever" is its first rule). Everything that would talk to a server is a Zustand store action (`src/shared/store/slices/*.ts`) and a simulated Oracle (`src/shared/engine`). So the mapping below is: *this screen and this store action* → *this endpoint*. Screen IDs (M- mobile, W- web, A- admin) come from its `docs/xref.md`.

## How a real app talks to this API

- Every path below is under `/api/v1` (for example `POST /api/v1/auth/signup`). Swagger UI lists them at `/docs`.
- **Signed in:** send `Authorization: Bearer <access_token>`. Keep the `device_token` from `POST /auth/verify` on the device, and send it with the next `POST /auth/signin` to skip the code.
- **Mobile app:** send `"platform": "mobile"` at sign-in and verify for the 30-day session. Browsers always get web sessions (12 hours, 30 minutes idle).
- **Errors:** always `{"error": {"code", "message", "field"}}`. Show `message` under `field`; switch on `code` for screens such as `under_age`, `policy_update_required` or `account_locked`.
- **After sign-in,** ask `GET /me/next-step`: it says which screen comes first (`policy_update`, `intake`, `upgrade` or `dashboard`).
- **The reply streams** as server-sent events from `POST /conversations/{id}/reply`: `delta` (text), `widget`, then `done` or `error`.

## Screen by screen

Status: **Built** = the endpoint exists and is tested; **Partly** = exists but the screen needs more; **Not built** = planned, with its phase in [PLAN.md](PLAN.md).

### Onboarding and account (F01, F04, F10)

| Screen | Prototype action today | Endpoint | Status |
|---|---|---|---|
| M-1.3 Consent, M-1.5 Terms / Privacy sheet | `acceptTerms`, `acceptConsent` | `GET /policies/current` to show them; accepted with `accept_terms: true` on `POST /auth/signup` | Built |
| M-1.13 Your age (date of birth, country, state) | `setAccountAge` | `POST /auth/signup/check`: 204, or `under_age` | Built (no city: see differences) |
| M-1.10 Ask a parent (under 18) | — | the `under_age` error from the check or sign-up | Built |
| M-1.4 Create your profile (email, password, code, you're in) | `createAccount` | `POST /auth/signup` → `verification_required`, then `POST /auth/verify` with the code → signed in; `POST /auth/verify/resend` (wait `resend_after_seconds`) | Built |
| M-4.3 Create account / Sign in, W-4.0 guest auth gate | `restoreAccount` | `POST /auth/signin` → `signed_in`, or `verification_required` and then `POST /auth/verify` | Built |
| Forgot password (A-style sheet in the client flow) | — | `POST /auth/password/forgot`, `POST /auth/password/reset/check`, `POST /auth/password/reset` (the token arrives after `#` in the emailed link) | Built |
| M-2.15 Terms updated | `acceptConsent(version)` | `GET /me/pending-consents`, then `POST /me/policy-acceptances` | Built |
| M-10.1 Account | `updateAccount` | `GET /me` (first name, email, role, trial end). Editing the name and state (11.1) | Partly: read only; 11.1 is Phase 10 |
| M-10.7 Change password | — | `POST /me/password` | Built |
| Settings → Sign out | — | `POST /auth/signout` with the `device_token` | Built |
| M-10.2 Privacy & data (export, delete) | `discardGuestData`, `revokeHealthConsent` | — | Not built (Phase 10, story 11.4) |
| M-10.4 Notifications | `setPermission` | — | Not built (Phase 9) |

### Profiles and intake (F01 M-1.8, F06)

| Screen | Prototype action today | Endpoint | Status |
|---|---|---|---|
| M-1.8 "Who is this profile for?" | `addProfile` | `POST /profiles/self` or `POST /profiles/family` (one call per choice; the prototype's `profileFor: dependent` is the second) | Built |
| M-1.8 relationship, name, date of birth, advocate consent, sex, gender, pronouns | `updateIntake`, `setIntakeProgress` | `PATCH /profiles/{id}/intake` with whichever answers the screen has; the answer says the `next_question` | Built (codes change in R2: see differences) |
| M-1.9 Deborah's welcome ("Start chatting") | — | `POST /profiles/{id}/intake/complete` returns the welcome text | Built |
| M-6.1 Profile switcher | `switchProfile` | `GET /profiles` (active profiles); `GET /me/next-step` gives the default one | Built |
| M-6.2 Add family member, M-6.3 Upgrade to Family | `addProfile` | `POST /profiles/family`; on the trial or a full plan it answers the upgrade error, and `GET /me/entitlements` gives the places used and included | Built |
| M-6.5 Profile details | `updateProfile` | `GET /profiles/{id}`; `PATCH /profiles/{id}` edits a family member's first name, relationship (with the consent again), gender and pronouns | Built for family members; your own details are edited in 11.1 (Phase 10) |
| M-6.6 Manage profiles | `deleteProfile` | `GET /profiles/family`; `POST /profiles/{id}/turn-off`, `/turn-on`; `POST /profiles/{id}/deletion-request`; `DELETE /profiles/{id}` only cancels an unfinished intake | Built |
| M-6.7 Invite your teen, M-1.12 Teen invitation | `inviteTeen`, `acceptTeenInvite` | — | Not built (Phase 3b) |

### Conversations (F02, F03)

| Screen | Prototype action today | Endpoint | Status |
|---|---|---|---|
| M-2.0 Home | — | `GET /me/next-step`, `GET /me/entitlements`, `GET /profiles/{id}/conversations` | Partly: the dashboard (4.1) is Phase 11 |
| M-2.1 Conversation: new | `startConversation` | `GET /profiles/{id}/conversations/new` (opening line, starter questions), then `POST /profiles/{id}/conversations` with the first message | Built |
| M-2.1 Conversation: sending | `appendMessage` | `POST /conversations/{id}/messages`, then, if `next` is `reply`, `POST /conversations/{id}/reply` (stream) | Built |
| M-2.1 Health Consent (inline) | `acceptHealthConsent` | `GET` / `POST /profiles/{id}/health-consent` (when `next` is `health_consent`) | Built |
| M-2.1 history, returning client | `setActiveConversation` | `GET /profiles/{id}/conversations`, `GET /conversations/{id}` (messages, widgets, `awaiting_reply`, `welcome_back`) | Built |
| M-2.1 thumbs up or down | — | `PUT` / `DELETE /conversations/{id}/messages/{message_id}/feedback` | Built (not in the stories: question 44) |
| Delete a conversation | `archiveActive` (archives) | `DELETE /conversations/{id}` | Built (not in the stories: question 45) |
| M-2.12 First consultation (scripted) | engine scripts | the same conversation endpoints; the script is the real Oracle's job | Partly: the Oracle is the fake in dev |
| Safety: EmergencyInterrupt, CrisisSupportCard, MedicationSafetyCard | `engine/safety.ts` | every message is safety-checked (`check_safety` in `app/oracle/contract.py`); the escalation screens and hold are story 3.2 | Partly: 3.2 is next after Phase R |
| M-2.13 What Deborah noted (facts) | `proposeFacts`, `confirmFacts` | — | Not built (Phase 4/5: fact extraction) |
| M-2.8 Follow-up opt-in, M-5.1 notifications | `snoozeFollowUp` | — | Not built (Phase 9) |
| M-4.1 Free limit | `holdMessage`, `dismissLimit` | a message after the trial ends is refused (`trial_ended`); the counts are in `GET /me/entitlements` | Partly |

### Not built yet in the backend

| Screens | Phase in PLAN.md |
|---|---|
| M-2.11 Profile question, M-2.14 Complete intake, M-7.x My Health, M-7.7 Edit health detail | Phase 4 (health profile, story 6.1, with the body-routed question banks) |
| M-7.3 Healing / Wellness Plan | Phase 7 |
| M-9.x My Visit Notes, provider notes, PDF | Phases 5 and 6 |
| M-4.2 to M-4.5 plans and payment, M-10.3 Subscription, M-10.8 Cancel | Phase 8 |
| M-8.x booking a consultation | Phase 10 (story 10.1) |
| M-2.9 Scan a label, M-5.3 / M-5.4 labs, M-11.x documents and uploads | Not planned: the 4 Nov stories removed uploads, documents and labs |
| A-1.1 to A-13.4 (admin panel) | Phase A |

## Where the prototype and this API differ

| | Prototype | This API (and the 5 Nov stories) |
|---|---|---|
| Chat before an account | the web flow lets a guest chat first (W-1.0, M-1.11) | needs an account; no story has guest chat |
| Sign-up fields | first and last name, phone, city | first name, date of birth, country (US) and state only; no phone, last name or city |
| Sign-up order | name → age → email and password → code | the same order works: `/auth/signup/check` after the age step, then `/auth/signup` with the whole form |
| Sex at birth | `male`, `female`, `intersex`, `prefer-not` | today `male`, `female`, `intersex`; R2 adds `prefer_not_to_say` |
| Gender | `man`, `woman`, `non-binary`, `agender`, `other`, `prefer-not` | today the older list (with `trans_woman`, `trans_man`); R2 switches to `woman`, `man`, `non_binary`, `agender`, `not_listed`, `prefer_not_to_say` |
| Pronouns | `he-him`, `she-her`, `they-them`, `describe` | `he_him`, `she_her`, `they_them`, `other` (write-in in `pronouns_other`) |
| Relationship | `parent`, `child`, `partner`, `other` | `parent`, `child`, `partner`, `someone_else` |
| Who the profile is for | one `profileFor` answer (`dependent`) | two endpoints, `POST /profiles/self` and `POST /profiles/family` |
| Body questions | optional Health Profile, routed by the "Your body" answers, else sex at birth | the same plan, for Phase 4 |

The codes need one convention before the apps are wired: either the apps send this API's snake_case codes, or the API accepts both for a while. Agreeing on this API's codes is simpler.

## Suggested order to wire the real apps

1. Sign-up, verify, sign-in, sign-out and forgot password (all built).
2. The policy screens and `GET /me/next-step` routing.
3. Onboarding and Manage Family (after R2 aligns the codes above).
4. Conversations, with the streamed reply and the Health Consent.
5. The rest as each phase lands.
