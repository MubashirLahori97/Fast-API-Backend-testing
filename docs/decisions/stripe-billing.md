# Stripe billing: decisions

Built 2026-11-11, after the user chose Stripe as the payment provider (docs/PLAN.md, question 2). It covers Client stories 9.1 "Start Free Trial & Activate Subscription" and 11.3 "Manage Billing & Subscription", Super Admin 8.1 "View & Edit Subscription Plans" and 8.2 "Add Subscription Plans and Pricing", and the subscription part of 11.4 "Revoke Consent / Delete Account". It builds on `docs/decisions/phase-8-billing.md` and `phase-a2-admin-operations.md`. Code only: no tests and no migration. Nothing in it has been run against the real Stripe API (there were no keys); it was checked with signed test webhooks and a mocked Stripe client.

## What was built

- **`app/billing/stripe_provider.py`: `StripeProvider`**, every `PaymentProvider` call, using the official `stripe` library (16.1, `StripeClient`, API version `2026-10-28.endive`).
- **`get_payment_provider`** (`dependencies.py`):
  - returns Stripe when `STRIPE_SECRET_KEY` is set;
  - otherwise returns the fake, in development and test;
  - in production, refuses to run without `STRIPE_SECRET_KEY` and `STRIPE_WEBHOOK_SECRET`.
- **`PaymentProvider` gained two calls**, with matching ones in the fake:
  - `set_up_plan(PlanSetup)`: creates or updates the plan's product and prices;
  - `use_current_prices(subscription_id, plan)`: moves a subscription to the current prices from its next billing date.

  It also gained `IgnoredEvent`, for webhooks billing doesn't follow.
- **Super Admin plans** (`app/admin/plans/`): a price change creates the new Stripe price and archives the old one before the change is saved. `_set_up_with_providers` does the setup. The plan endpoints now take the payment provider as a dependency.
- **Account deletion:** `purge.end_subscription` ends the Stripe subscription at once.
- **`scripts/create_stripe_prices.py`:** creates the test-mode products and prices.

No endpoint was added. These endpoints changed:

- `POST /billing/webhook` now takes Stripe events when Stripe is configured;
- `PATCH /admin/plans/{id}` and `POST /admin/plans/{id}/publish` (and `POST /admin/plans` with publish) now call the provider.

## How each call maps onto Stripe

| Call | Stripe |
| --- | --- |
| `start_checkout` | Checkout Session, `mode=subscription`. Line items: the plan's price ×1, plus the add-on price × the add-on count (Family only). Uses `customer` if the client subscribed before, else `customer_email`. `client_reference_id` and the subscription metadata carry the account id, plan and add-on count. Back to `billing_return_url?checkout=success` or `?checkout=cancelled` |
| Upgrade (`change_plan`, now) | The plan item's price is swapped for Family's, with `proration_behavior=always_invoice` and `payment_behavior=error_if_incomplete`. The difference for the rest of the period is charged straight away; if the card is declined, Stripe changes nothing and the client sees 9.1's "We couldn’t process your payment..." |
| Downgrade (`change_plan`, at the period end) | The price is swapped for Individual's with `proration_behavior=none`, and the add-on item is removed. In Stripe that means "from the next invoice": the period already paid for stays Family. The add-on count is kept in the subscription's metadata (`add_ons_before_downgrade`) |
| Staying on Family while a downgrade waits | Swapped back, with no proration, and the add-ons are put back from that metadata |
| `set_add_on_members` | The add-on item's quantity (added or deleted as needed). Adding is invoiced at once, prorated (9.1: "charged from that day"); removing uses no proration (11.3: "stops from the next billing date") |
| `cancel(at_period_end=True)` / `resume` | `cancel_at_period_end` true or false |
| `cancel(at_period_end=False)` | `DELETE /subscriptions/{id}` with no proration and no final invoice. It does nothing when the subscription has already been cancelled. Used when the grace period runs out and for account deletion |
| `payment_method_link` | A Customer Portal session with `flow_data.type=payment_method_update`, so the portal opens only on the payment method page. After completion it returns to `billing_return_url?payment_method=updated` |
| `set_up_plan` | Reuses the current price when it's active, monthly and the same amount. Otherwise it creates a new price on the same product (creating the product the first time) and archives the old price (`active=false`) |
| `use_current_prices` | Swaps each item to the catalogue's current price with no proration, so nothing is charged until the next invoice |

- **Prices carry metadata** `genesis_plan` (the plan code) and `genesis_kind` (`plan` or `add_on`). That's how a subscription's add-on item is told apart from its plan item. A price without the metadata is recognised by the catalogue's add-on price id.
- **Checking prices:**
  - Checkout, upgrades and new add-on items check that the Stripe price's amount is the one the client confirmed. If it isn't, nothing is charged, a warning names the plan, and the client sees 503 `provider_unavailable`.
  - Adding to an existing add-on item keeps that item's price until `use_current_prices` moves it.
- **Failures:**
  - Stripe's `CardError` becomes `PaymentDeclined` (402 `payment_failed`).
  - Any other Stripe error becomes `ProviderError` (503 "We couldn’t do that just now. Please try again.").
  - These failures are logged by class name and Stripe's error code only.
- **Retries:** `max_network_retries=2`. Product and price creation also carry their own idempotency keys, so a retried admin save doesn't create duplicates.

## Webhooks

`POST /api/v1/billing/webhook` checks the `Stripe-Signature` header with `stripe.Webhook.construct_event`. It uses `STRIPE_WEBHOOK_SECRET` and the existing `payment_webhook_tolerance_seconds` (300).

**Handled once:** each Stripe event id is still recorded in `payment_events` in the same transaction as its changes, so a redelivered event changes nothing.

| Stripe event | Billing event |
| --- | --- |
| `checkout.session.completed` (subscription mode, paid) | `payment_succeeded`, the first payment. Reads the subscription to get the account, plan, add-ons, period and payment method |
| `invoice.paid` | `payment_succeeded`. For `subscription_create` and `subscription_cycle`, the subscription is read for its period and metadata, so the first invoice can start the subscription too (whichever of the two events arrives first does it). Other invoices, such as an upgrade's proration, record the payment only |
| `invoice.payment_failed` | `payment_failed`, with the amount due |
| `customer.subscription.updated` | `payment_method_updated` when `default_payment_method` changed (the Customer Portal). Otherwise `subscription_renewed` with the current period: billing renews only when the period has moved on, so other updates change nothing |
| `customer.subscription.deleted` | `subscription_ended` |
| anything else, and invoices with no subscription | `IgnoredEvent`: answered 200, so Stripe doesn't resend it |

- **When Stripe can't be reached:** if reading a subscription during a webhook fails, the answer is 503 and Stripe sends the event again.
- **Duplicate records:** the first payment arrives twice (in the checkout event and the invoice event), but the invoice's unique id keeps it to one invoice and one receipt.
- **Payment method:** wallets are shown as `apple_pay` or `google_pay` with no last 4 digits; cards as brand plus last 4.

## Other design choices

- **Where the price ids live:**
  - `billing_plans.stripe_price_id` and `stripe_add_on_price_id` hold them, as new columns.
  - A launch plan's row with none falls back to the settings `STRIPE_INDIVIDUAL_PRICE_ID`, `STRIPE_FAMILY_PRICE_ID` and `STRIPE_FAMILY_ADD_ON_PRICE_ID`.
  - Both are read through `catalog.stripe_price_id(plan)` and `catalog.stripe_add_on_price_id()`.
  - Ids are saved on the row only when the provider is Stripe, so the fake never writes ids.
- **A price change in the admin panel (8.1):**
  - Before saving, `_set_up_with_providers` creates the new Stripe price and archives the old one. If Stripe fails, nothing is saved and the Super Admin sees 8.1's "We couldn’t do that just now. Please try again." (503 `provider_unavailable`).
  - Existing subscribers stay on the archived price, which Stripe keeps billing, until their price change email job runs. That job (`send_price_change_email`) first calls `use_current_prices` and then emails. So they pay the new price from their next billing date, after being told, matching billing's local `_renew`.
  - If Stripe can't be reached, the job is retried before any email goes out.
- **Publishing a new plan (8.2):** still answers "We couldn’t set up this plan with the payment providers. Please try again.". Billing only sells Individual and Family (`PaidPlan`, `subscriptions.plan`'s check), so nothing is created in Stripe for a plan clients couldn't buy.
- **Add-ons that stop at the next billing date (11.3):**
  - Stripe creates the renewal invoice at the period end and freezes its lines. So a new check, `billing_pre_renewal_minutes` (60) before the period end, takes add-ons no longer used off Stripe with no proration.
  - The places stay in the app until the period ends, when `_settle_period` drops them as before.
  - `_activate` and `_renew` now queue that extra `billing.check_subscription` run.
- **Account deletion (11.4):**
  - 11.4 says nothing about the subscription, and the deletion grace period keeps "full use of the account". So renewals are **not** stopped during the grace period.
  - The subscription is ended at once, with no refund, when the purge deletes the account (`end_subscription`, audited as `billing.subscription.ended_for_deletion`).
  - If Stripe can't be reached, the purge job fails and is retried, so the account isn't deleted while Stripe still bills it.
  - App Store and Google Play subscriptions are skipped: only the client can cancel those.
- **Customer Portal:** opened only on its payment method page. Cancelling and plan changes stay in the app, so the app's rules (confirmations, family members) always apply.

## Messages

No new messages for the apps. These existing ones are reused:

- 9.1's "We couldn’t process your payment..." for a declined upgrade or add-on;
- 8.1 and 11.3's "We couldn’t do that just now. Please try again." when Stripe can't be reached, including a failed price change in the admin panel;
- 8.2's "We couldn’t set up this plan with the payment providers. Please try again.".

## Settings added

| Setting | Default | Notes |
| --- | --- | --- |
| `stripe_secret_key` | empty | Empty means the fake (development and test only) |
| `stripe_webhook_secret` | empty | From `stripe listen` or the dashboard's endpoint. Empty refuses every webhook |
| `stripe_individual_price_id`, `stripe_family_price_id`, `stripe_family_add_on_price_id` | empty | From `scripts/create_stripe_prices.py` |
| `billing_pre_renewal_minutes` | 60 | Assumed value: how long before the billing date unused add-ons come off Stripe |

## For the migration

- `billing_plans`: two nullable `VARCHAR` columns, `stripe_price_id` and `stripe_add_on_price_id`.
- Autogenerate finds both. Nothing to hand-add: no constraints, data changes, seed rows or triggers.

## Not done, and known gaps

- **Tests** (out of scope): `tests/conftest.py` doesn't override `get_payment_provider`. If `.env` has a `STRIPE_SECRET_KEY`, pytest would call Stripe test mode. The tests should override it with `FakePaymentProvider`.
- **Payment method changed on the customer only:** if the Customer Portal changes only the customer's default payment method, not the subscription's, no listed event reports it. Listening to `customer.updated` would cover it.
- **Changes made in the Stripe dashboard** (cancelling, changing prices by hand) aren't mirrored, apart from the subscription ending.
- **Turning a member back on in the last hour:** if a member is turned back on within `billing_pre_renewal_minutes` of the billing date, after their add-on came off Stripe, the next period doesn't charge that add-on.
- **Resuming after a price change:** a subscriber who had cancelled when a price changed wasn't emailed, so wasn't moved to the new Stripe price. If they resume, Stripe bills them the old price, while the app shows the new one from renewal.
- **Store subscriptions:** Apple and Google aren't built (no receipt checking), and 8.1's "Store update pending" isn't used.
- `docs/decisions/deletion-flow-1922.md` item 7 still says `end_subscription` is empty. That file belongs to another area, so it wasn't edited here.

## New open questions for the BA

1. **Locked account, still billed:** after a deletion request's grace period, the account is locked, but the subscription keeps renewing until the team completes the deletion (up to 45 days). Should renewals stop, or the subscription cancel, when the grace period ends? 11.4 doesn't say.
2. **Refunds on deletion:** is anything refunded for the unused part of the period when an account is deleted? Built: no refund.
3. **Receipts:** do we email our own receipts, or let Stripe send its receipts (dashboard setting)? Both are on now unless `SEND_RECEIPT_EMAILS=false`.

## How to set up Stripe test mode

1. **Create a Stripe account** at https://dashboard.stripe.com/register and stay in **Test mode** (the toggle at the top). You don't need to activate the account for payments.
2. **Turn on the Customer Portal:** in the dashboard, go to Settings → Billing → Customer portal and save it once. Allow "Update payment methods"; turn off cancelling and switching plans. Until it's saved, "Change payment method" fails.
3. **Copy the test secret key:** Developers → API keys → "Secret key" (`sk_test_...`). Put it in `.env` (never in `.env.example` or the code):

   ```
   STRIPE_SECRET_KEY=sk_test_...
   ```

4. **Create the prices:** run the script once. It refuses a live key.

   ```bash
   uv run python scripts/create_stripe_prices.py
   ```

   Copy the three `STRIPE_..._PRICE_ID=` lines it prints into `.env`.
5. **Forward webhooks to your local API:** install the Stripe CLI (https://docs.stripe.com/stripe-cli), then run `stripe login` and:

   ```bash
   stripe listen --forward-to localhost:8000/api/v1/billing/webhook
   ```

   It prints `Your webhook signing secret is whsec_...`. Put it in `.env` as `STRIPE_WEBHOOK_SECRET=whsec_...`, and keep `stripe listen` running while you test.
6. **Restart the API and the worker** so they read `.env`:

   ```bash
   uv run fastapi dev app/main.py
   uv run python -m app.worker
   ```

7. **Try it:**
   - Subscribe from the app, or with `POST /api/v1/billing/subscription`.
   - Open the returned `checkout_url` and pay with the test card `4242 4242 4242 4242` (any future date, any CVC).
   - `GET /api/v1/billing/subscription` should show `active` within a few seconds.
   - To test a payment issue, use "Change payment method" to switch to test card `4000 0000 0000 0341`, which saves but declines later charges. Then let a renewal happen: Stripe's test clocks move a test customer's time forward.
   - `stripe trigger invoice.payment_failed` sends sample events, but those are for subscriptions the app doesn't know, so it ignores them.

To go back to the fake provider, empty `STRIPE_SECRET_KEY` in `.env` and restart.
