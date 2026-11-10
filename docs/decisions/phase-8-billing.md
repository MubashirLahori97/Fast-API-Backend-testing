# Phase 8 Billing: decisions

Phase 8 in `docs/PLAN.md`, built 2026-11-05 against the 4 Nov stories "Start Free Trial & Activate Subscription" (9.1) and "Manage Billing & Subscription" (11.3), with open questions 2, 11 and 13. It builds on R2's plan codes (`docs/decisions/r2-profiles.md`). Code only: no tests and no migration yet.

## What was built

- **`app/billing/`**:
  - `catalog.py`: plans, prices and features;
  - `provider.py`: the `PaymentProvider` protocol;
  - `fake.py`: `FakePaymentProvider`;
  - `dependencies.py`: `get_payment_provider`;
  - `models.py`, `entitlements.py`, `family.py` (family members when the Family plan ends and restarts), `service.py`, `schemas.py`, `router.py`, `jobs.py`, `emails.py` (receipts).
- **Endpoints**, all under `/api/v1`. The client ones are signed in and behind the policy gate; the webhook isn't signed in.

| Method and path | What it does |
| --- | --- |
| `GET /billing/plans` | 9.1's plan screen: plans, prices, features, add-on price, renewal disclaimer, add-on confirmation |
| `GET /billing/subscription` | 11.3's current plan: status, next billing date and amount, family places, add-ons, payment method, confirmation texts, locked features |
| `POST /billing/subscription` | Subscribe (`plan`, `add_on_members`, `confirmed_monthly_price_cents`). Answers `checkout_url` for a hosted page; the fake pays at once |
| `POST /billing/subscription/plan` | Individual to Family at once; Family to Individual from the next billing date |
| `POST /billing/subscription/add-ons` | Adds paid places on the Family plan (`count`, `confirmed_monthly_price_cents`) |
| `POST /billing/subscription/cancel` | Cancels at the end of the period |
| `POST /billing/subscription/resume` | Undoes a cancellation before the period ends |
| `POST /billing/payment-method` | Returns a link to the provider's page for changing the payment method |
| `GET /billing/invoices` | Billing history, newest first |
| `POST /billing/webhook` | The provider's events. Signature checked, each event handled once |

- **Jobs:**
  - `billing.check_subscription`: whatever is due for one subscription;
  - `billing.sync_family_members`: family members follow the Family plan.

## Design choices

- **The provider sits behind a protocol** (question 2 is still open), like email and the Oracle.
  - The methods: `start_checkout`, `cancel`, `resume`, `change_plan`, `set_add_on_members`, `payment_method_link`, and `parse_event` (checks the signature and reads the webhook).
  - `get_payment_provider` and `FakePaymentProvider` both refuse to run when `ENVIRONMENT=production`.
  - The app never sees card details. Checkout and the payment method page are the provider's own pages; the provider's events tell us what happened.
  - The provider never gets health data, only the account id, email, plan and prices.
- **The fake provider** pays at once, with no page to open.
  - `checkout_result` can be `"declined"`, `"cancelled"` or `"hosted"`. With `"hosted"` it answers with a link, as Stripe would, and the subscription starts on a `payment_succeeded` event.
  - `decline_charges` and `fail` simulate declined payments and an unreachable provider.
  - `calls` lists what was called.
  - `signed_event(...)` builds signed webhooks for renewals, failures and endings.
- **One `subscriptions` row per account**, reused when the client subscribes again.
  - No row means the account never subscribed, so it's on the trial.
  - The row is the source of truth.
  - `users.subscription_plan` is kept in step: the plan the account can use now, or null. The notifications package's trial reminders filter on it. Nothing else should read it.
- **Statuses:**
  - `active`: paid and renewing;
  - `past_due`: 11.3's "Payment issue". Access continues until `grace_ends_at`;
  - `cancelled`: 11.3's "Cancelled". Access continues until the end of the period paid for, or of the grace period if a payment had failed;
  - `ended`: no access. `ended_reason` is `cancelled`, `payment_failed` or `other`.
  - `cancel_at_period_end` mirrors the provider's flag: true from Cancel until Resume.
  - `GET /billing/subscription` shows these as `trial`, `active`, `payment_issue`, `cancelled` and `ended`.
- **Entitlements check the times, not only the status.**
  - `entitlements.gives_access` compares `grace_ends_at` and the period end with now.
  - Access therefore ends on time even if the worker is late. The job still marks the row ended and turns family members off.
  - `entitlements.py` keeps its public functions and their signatures (`plan`, `trial_ended`, `check_can_talk`, `family_members_included`, `family_members_used`, `check_can_add_family_member`, `check_can_turn_on_family_member`).
  - It reads the subscription through `object_session(user)`, so every caller still passes just the account.
- **`plan()` and `trial_ended()` after a subscription ends.**
  - `plan()` returns `"trial"` once a subscription has ended, so `/me/entitlements` keeps its three codes.
  - `trial_ended()` then means "the message box is locked", which is what `next_step` and the conversations package use it for.
  - `check_can_talk` answers `subscription_ended` instead of `trial_ended` when the account has subscribed before. **The apps should treat both codes as the upgrade prompt.**
- **`feature_access(user)`** returns `{feature: locked}` for `conversations`, `my_health`, `visit_notes`, `wellness_plan`, `family_members`, `teen_invites` and `downloads`. `check_feature(user, feature)` raises the story's upgrade prompt. Phases 4 to 7 and 11 call these.
  - The trial locks everything except conversations, and conversations too once the trial has ended.
  - Individual locks only family members and teen invites.
- **The trial** is unchanged: 14 days (`trial_days`) from verification, set in `auth.service`. The trial reminders (9.1, 12.1) are sent by the notifications sweep, which leaves out subscribers through `users.subscription_plan`.
- **Prices** are settings, read only through `catalog.py`, which Phase A can switch to a table.
  - Each subscription keeps the prices of its current period (`plan_price_cents`, `add_on_price_cents`).
  - They're refreshed from the catalog at each renewal. So a price change reaches existing subscribers from their next billing date (Super Admin 8.1); telling them first is Phase A's job.
- **Confirming the price:**
  - Subscribing, upgrading and adding places all need `confirmed_monthly_price_cents`. That's the total the client was shown: the plan plus add-ons, the Family price for an upgrade, or the add-ons' price.
  - A different value means the price changed since the screen loaded: 409 `price_changed`.
  - This is the backend half of 9.1's "confirm the price"; the renewal disclaimer is shown on the same screen.
- **Locking and order:**
  - Every billing change takes the account row lock, then the subscription's (`FOR UPDATE`).
  - The provider is called before anything is saved, so a declined or unreachable provider leaves nothing half-done. A declined or cancelled payment is audited.
  - The provider is called while the lock is held, so a double tap can't subscribe twice. That costs one provider round trip on that account's lock.
- **Webhooks:**
  - **Signature:** header `Payment-Signature: t=<unix time>,v1=<hex HMAC-SHA256 of "<t>.<body>">`, using `payment_webhook_secret`. It's refused when more than `payment_webhook_tolerance_seconds` old, so a captured event can't be replayed later.
  - **Handled once:** each event inserts a `payment_events` row (`ON CONFLICT DO NOTHING`) in the same transaction as its changes. A second delivery, even a simultaneous one, waits for the first and then does nothing. If handling fails, nothing is saved and the provider retries.
  - **Event types:**
    - `payment_succeeded`: starts a hosted-checkout subscription, renews, or fixes a payment issue;
    - `payment_failed`: `past_due` plus the grace period, the `renewal_failed` notice, and a check at the grace period's end;
    - `subscription_renewed`: a new period;
    - `subscription_ended`: the provider ended it;
    - `payment_method_updated`.
  - Unknown subscriptions are ignored with 200.
- **Time-based changes** run in `billing.check_subscription`, queued for when they're due. Extra or early runs change nothing.
  - **At the end of a cancelled period:** the subscription ends.
  - **At the end of the grace period:** it ends, and the provider is told to stop retrying. If the provider can't be reached, access ends anyway and a warning is logged.
  - **At the next billing date** (`_settle_period`), done once per period. `settled_period_end` records that it's done, whether the job or the renewal event got there first.
    - A scheduled downgrade applies.
    - Add-ons drop to the places in use (11.3: turning off or removing a member stops the add-on charge from the next billing date).
- **Add-ons and the 8.1/8.2 flow:**
  - `check_can_add_family_member` and `check_can_turn_on_family_member` count `family_members_included + add_on_members` on a Family plan.
  - When the plan is full, the app shows 9.1's add-on confirmation (from `GET /billing/plans`, with `[Name]` for the app to fill in), calls `POST /billing/subscription/add-ons`, and then repeats the add or turn-on, which now finds a place.
  - Declining the add-on adds nobody.
  - No profiles code was changed.
- **When the Family plan ends** (cancellation at the period end, a downgrade at the next billing date, or the grace period running out), `billing.sync_family_members`:
  - turns each managed member off by calling `profiles.service.turn_off_family_member` (unchanged), with no request;
  - records the member in `paused_family_members`, with the profile's own `turned_off_at`;
  - records `billing.family_member_paused` and sends `family_members_turned_off`;
  - pauses invited teens (`family.pause_invited_teens`, a PHASE 3B hook that does nothing yet).
  - Each member is its own transaction, as in 8.2; the job is retried if one fails.
  - 8.2's audit event `profile.turned_off` has the client as its actor, because that code isn't ours; `billing.family_member_paused` beside it shows the system did it.
- **When the Family plan is active again** (subscribe, upgrade, or added places):
  - The members it paused are turned back on with `turn_on_family_member`, only if they **all** fit. The client then gets `family_members_turned_on`.
  - If they don't all fit, none are turned on. `GET /billing/subscription` then gives `family_members_waiting` and 11.3's "Your plan includes 3 family members. Choose who to turn back on, or add another member.". The client turns members on in Manage Family, or adds places.
  - A member the client has turned on or off again since has a different `turned_off_at`, and is left alone.
  - `family.restore_invited_teens` is a PHASE 3B hook.
- **Advocate-only clients** (family members but no own profile):
  - 8.2's rule stops the last active member being turned off, so that member stays on when the plan ends. Nothing can be used without a plan anyway.
  - The Individual plan (own profile only) is refused to these clients, at subscribe and at downgrade: `own_profile_required`.
- **Teens with their own account** can't use any billing endpoint (403 `teen_account`). Until Phase 3b adds an account type, a teen is recognised as an account holder under the age of majority, as in `support.service`.
- **Store subscriptions:**
  - `provider` can be `app_store` or `google_play`. For these, cancel, resume, plan changes, add-ons and the payment method answer 11.3's "You subscribed through [App Store / Google Play]. Please manage your subscription there.", and billing history answers with the same text.
  - Nothing creates such a subscription yet: receipt checking comes with question 2.
- **Receipts:**
  - Every newly paid invoice is emailed after the commit (`send_receipt_emails`; turn it off if the provider sends its own).
  - The email holds the plan, amount, date and the provider's receipt link only.
  - `invoices` keeps the amount, date, status, plan and receipt link, with no card details.
  - The fake doesn't charge upgrades or added places straight away: a real provider sends their invoices as `payment_succeeded` events.
- **Dates in messages** are written "December 5, 2026", on the date in Hawaii (as in `app/core/ages.py`), so "access until [date]" never promises a later date than the client's own.
- **Audit events** (no card details):
  - client actions: `billing.checkout.started`, `billing.subscription.started`, `.upgraded`, `.downgrade_scheduled`, `.downgrade_cancelled`, `.cancelled`, `.resumed`, `billing.add_ons.added`, `billing.payment.declined`, `billing.payment.cancelled`, `billing.payment_method.change_started`;
  - provider events and jobs: `billing.subscription.renewed`, `.plan_changed`, `.ended`, `.duplicate`, `billing.add_ons.released`, `billing.payment.succeeded`, `.failed`, `.recovered`, `.after_end`, `billing.payment_method.updated`, `billing.family_member_paused`, `billing.family_member_restored`.

## Stored codes

| Column | Codes |
| --- | --- |
| `subscriptions.provider`, `invoices.provider`, `payment_events.provider` | `fake`, `stripe`, `app_store`, `google_play` |
| `subscriptions.plan`, `pending_plan`, `invoices.plan` | `individual`, `family` |
| `subscriptions.status` | `active`, `past_due`, `cancelled`, `ended` |
| `subscriptions.ended_reason` | `cancelled`, `payment_failed`, `other` |
| `invoices.status` | `paid`, `failed` |
| `payment_events.type` | `payment_succeeded`, `payment_failed`, `subscription_renewed`, `subscription_ended`, `payment_method_updated` |
| Features (`feature_access`) | `conversations`, `my_health`, `visit_notes`, `wellness_plan`, `family_members`, `teen_invites`, `downloads` |

## Messages from the stories

- 9.1:
  - "This is part of your plan. Choose a plan to unlock it." (`check_feature`)
  - "Your free trial has ended. Choose a plan to keep talking with me."
  - "Adding family members is part of the Family plan. Upgrade to add someone."
  - "We couldn’t process your payment. Please check your details or try another way to pay." (402 `payment_failed`)
  - "Your payment was cancelled. You can subscribe whenever you’re ready." (409 `payment_cancelled`)
  - "You’re all set. Welcome to the [Individual / Family] plan."
  - "Adding [Name] will add [price] a month to your subscription. Continue?"
  - the renewal disclaimer
- 11.3:
  - the cancel confirmation, and "Your subscription has been cancelled. You have access until [date]."
  - the downgrade confirmation
  - "We couldn’t renew your subscription. Please update your payment method to keep your access." (status message, the upgrade and add-on refusal while `past_due`, and the `renewal_failed` notice)
  - the store message
  - "Your plan includes 3 family members. Choose who to turn back on, or add another member." (uses the plan's real count)
  - "We couldn’t do that just now. Please try again." (provider unreachable, 503 `provider_unavailable`; database errors, 503 `save_failed`)
  - the short renewal disclaimer
- 11.3's alternate scenario: "There’s no billing history yet."
- "Your payment method has been updated." is shown by the app when the provider's page sends the client back. The backend doesn't learn the result until the provider's event arrives.
- The trial-ending reminder ("Your free trial ends in [X] days…") is sent by the notifications package.

## Messages not in the stories

| Situation | Message | Code |
| --- | --- | --- |
| Message box after a subscription ended | "Your subscription has ended. Choose a plan to keep talking with me." | `subscription_ended` |
| Subscribing while already subscribed | "You’re already on the [plan] plan." | `already_subscribed` |
| The confirmed price isn't the current one | "The price has changed. Please check the new price and try again." | `price_changed` |
| No confirmed price sent | "Please confirm the price to continue." | `validation_error` |
| Unknown or missing plan | "Please choose an option to continue." (the stories' text) | `validation_error` |
| Too many add-ons (over `max_add_on_members`) | "You can add up to 10 extra family members." | `validation_error` / `too_many_add_ons` |
| Managing a subscription that doesn't exist or has ended | "You don’t have an active subscription. Choose a plan to subscribe." | `no_subscription` |
| Changing the plan or adding places after cancelling | "Your subscription has been cancelled. Resume it first to make changes." | `subscription_cancelled` |
| Resume when not cancelled | "Your subscription is already active." | `not_cancelled` |
| Resumed | "Your subscription will continue. It renews on [date]." | — |
| Downgrade scheduled | "You’ll move to the Individual plan on [date]." | — |
| Family chosen while a downgrade waits | "You’ll stay on the Family plan." | — |
| Individual for an advocate-only client | "The Individual plan covers your own profile only. Please set up your own profile first, or choose the Family plan." | `own_profile_required` |
| A teen with their own account | "Your access comes through your parent’s or guardian’s Family plan." | `teen_account` |
| Webhook (for the provider only) | "The webhook signature isn’t valid." / "The webhook event couldn’t be read." | `invalid_signature` / `invalid_event` |
| Receipt email | Subject "Your receipt from Your Oracle"; plan, amount, date, receipt link | — |
| Plan features | 9.1's bullets, written to the client: "your own profile only", "you plus 3 family members, each with their own Wellness Plan" | — |

## Assumed values (all settings)

| Setting | Value | Why |
| --- | --- | --- |
| `individual_price_cents` / `family_price_cents` / `family_add_on_price_cents` | 1999 / 3999 / 999 (US cents a month) | Placeholders: no price is in the stories or docs |
| `individual_plan_name` / `family_plan_name` | Individual / Family | 9.1 |
| `billing_currency` | `usd` | US only |
| `payment_grace_days` | 7 | Question 13. Google Play's default grace period; Apple's is 3, 16 or 28 days |
| `max_add_on_members` | 10 | A sanity cap; the stories set none |
| `billing_return_url` | `http://localhost:5173/billing` | Where the provider's pages send the client back |
| `payment_webhook_secret` | `dev-only-payment-webhook-secret` | Development only; the real provider needs its own in `.env` |
| `payment_webhook_tolerance_seconds` | 300 | Stripe's default |
| `send_receipt_emails` | true | 9.1 |

Other assumptions:

- Cancelling while a payment issue is open keeps access until the grace period ends.
- An add-on bought mid-period is charged from that day by the provider (prorated). Unused add-ons are dropped at the next billing date, and the fake doesn't charge them at all.
- A payment for a subscription that has already ended doesn't reopen it (`billing.payment.after_end`, for the support team).
- A second subscription paid by mistake (two checkouts) isn't applied (`billing.subscription.duplicate`), so the support team can refund it.
- One trial per account. A person with a second email gets a second trial (question 11).

## For the migration

Autogenerate finds the four new tables with their check, unique and foreign key constraints and the server defaults: `subscriptions`, `invoices`, `payment_events` and `paused_family_members`. Nothing to hand-add on existing tables: `users.subscription_plan` and its check are unchanged. No triggers.

- **Data (development):** accounts whose `users.subscription_plan` was set by hand have no `subscriptions` row, so they're now on the trial. Either reset the dev database, or clear the copy with `UPDATE users SET subscription_plan = NULL WHERE id NOT IN (SELECT account_id FROM subscriptions)`. The existing tests that set `subscription_plan="basic"` or `"family"` need a subscription row instead.
- **Seed rows:** none. Prices are settings until Phase A.
- **Downgrade:** drop the four tables.

## For other phases

- **Phase 3b:**
  - Fill in `family.pause_invited_teens` and `restore_invited_teens`.
  - Count invited teens in `entitlements.family_members_used`.
  - Switch `service._check_client` and `feature_access` to the account type (a teen follows the parent's Family plan).
- **Phases 4 to 7 and 11:** gate their features with `entitlements.check_feature(user, "my_health")` and the others; the dashboard (4.1) can use `feature_access` and `trial_days_left`.
- **Profiles (optional):** the add-on release needs nothing from 8.2. If the real provider must know sooner, 8.2's turn-off and removal could tell billing straight away.
- **Frontend:**
  - `subscription_ended` (new) is shown like `trial_ended`.
  - After `checkout_url`, poll `GET /billing/subscription` until `status` is `active`.
  - Show `cancel_confirmation` and `downgrade_confirmation` before the POSTs.
- **The real provider (question 2):**
  - map its events onto `ProviderEvent`;
  - set the add-on count before its renewal invoice is final (Stripe drafts renewal invoices for about an hour);
  - use idempotency keys on its calls;
  - add App Store and Google Play receipt checking for store subscriptions.

## New open questions for the BA

1. **Prices:** what are the Individual, Family and add-on prices? The placeholders are $19.99, $39.99 and $9.99 a month.
2. **Grace period** (question 13): 7 days assumed. Is the payment retried during it, and how often?
3. **After a subscription ends:** what does Subscription & Billing show? We show the last plan as "ended" with "Your subscription has ended. Choose a plan to keep talking with me.". The story's statuses stop at Cancelled.
4. **Advocate-only clients** (family members, no own profile): can they choose the Individual plan, and what happens to their family members when the Family plan ends? We refuse Individual and leave their last member on, since 8.2 can't turn it off.
5. **More members than places when the plan restarts:** we restore none and let the client choose. Should we restore the first ones that fit instead?
6. **Is there a cap on add-on members?** We assumed 10.
7. **Downgrading with add-ons:** is anything shown about the add-ons ending with the Family plan? The downgrade confirmation only mentions family members.
8. **Receipts:** do we email them, or does Stripe or the store? Should renewals get one too (built: yes)?
