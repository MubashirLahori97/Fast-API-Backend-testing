# Stripe integration: what's left to do

This is the single list of remaining Stripe setup steps. The design and the reasons behind it are in [docs/decisions/stripe-billing.md](docs/decisions/stripe-billing.md).

The backend already creates its Checkout Session in one place, `StripeProvider.start_checkout` in [app/billing/stripe_provider.py](app/billing/stripe_provider.py). The Checkout Studio parameters were added to that call. Its existing `mode`, `success_url`, `cancel_url` and `line_items` already had real values, so they were kept.

## Values to Replace

The Checkout Session call has no placeholder values in the code itself: `mode`, `success_url`, `cancel_url` and `line_items` are real. Their values come from settings that are still empty or local, so set these before going live.

**Files containing placeholders:**
- [.env.example](.env.example), copied to your own `.env`, which isn't committed

| Field | Current Value | What to Set |
|-------|--------------|-------------|
| mode | `subscription` | Nothing: the plans are monthly subscriptions (stories 9.1, 11.3). |
| success_url | `{BILLING_RETURN_URL}?checkout=success`, with `BILLING_RETURN_URL=http://localhost:5173/billing` | Set `BILLING_RETURN_URL` to your real billing page for each environment. |
| cancel_url | `{BILLING_RETURN_URL}?checkout=cancelled` | The same `BILLING_RETURN_URL`. |
| line_items[].price (Individual) | `STRIPE_INDIVIDUAL_PRICE_ID=` (empty) | The Individual plan's Price ID (`price_…`). |
| line_items[].price (Family) | `STRIPE_FAMILY_PRICE_ID=` (empty) | The Family plan's Price ID. |
| line_items[].price (Family add-on) | `STRIPE_FAMILY_ADD_ON_PRICE_ID=` (empty) | The extra family member's Price ID (sent as a quantity). |

Run `scripts/create_stripe_prices.py` once with your test key: it creates the three prices and prints the ids. Once the Super Admin saves a plan in the admin panel, its `billing_plans` row holds the id instead of the setting.

## Configured Parameters

These parameters were configured in Checkout Studio and are already set correctly.

**Files containing these parameters:**
- [app/billing/stripe_provider.py](app/billing/stripe_provider.py)

| Parameter | Value |
|-----------|-------|
| ui_mode | `hosted` (stripe-python 16.1.0 is installed; from 21.0.0 the value is `hosted_page`) |
| billing_address_collection | `auto` |
| phone_number_collection | `{"enabled": false}` |
| automatic_tax | `{"enabled": false}` |
| allow_promotion_codes | `false` |
| payment_method_collection | `always` (included because `mode` is `subscription`) |
| submit_type | `auto` |
| integration_identifier | `hosted_mobile_app_0001` |
| origin_context | `mobile_app` |

**Kept on purpose** (the Checkout Studio prompt says to remove parameters it doesn't list): `customer` or `customer_email`, `client_reference_id`, `metadata` and `subscription_data.metadata`. They link the payment to the client's account, and the webhook needs them to activate the right subscription. Removing them would break subscriptions.

**Check once in test mode:** `integration_identifier`, `origin_context` and `submit_type` together with subscription mode are newer or mode-specific parameters. If Stripe answers a test checkout with "Received unknown parameter" or a mode error, either upgrade `stripe` (`uv add stripe@latest`, then change `ui_mode` to `hosted_page` on 21.0.0 or later), or remove just that parameter.

## Setup

1. **Stripe account:** sign up at https://dashboard.stripe.com and stay in **test mode**.
2. **Keys** in your `.env` (never in code). These are server-only, so no `VITE_` prefix; hosted Checkout needs no publishable key in the backend.
   - `STRIPE_SECRET_KEY=sk_test_…`, from Developers → API keys.
   - `STRIPE_WEBHOOK_SECRET=whsec_…`, from the Stripe CLI (step 4), or from Dashboard → Workbench → Webhooks for a deployed server.
3. **Prices:** run `uv run python scripts/create_stripe_prices.py` and paste the three price ids into `.env` (see the table above).
4. **Webhooks locally:** install the Stripe CLI, then run:
   ```bash
   stripe login
   stripe listen --forward-to localhost:8000/api/v1/billing/webhook
   ```
   Copy the `whsec_…` it prints into `STRIPE_WEBHOOK_SECRET`.
5. **Restart the API.** With `STRIPE_SECRET_KEY` set, billing uses Stripe; without it, development keeps the fake provider. The tests always use the fake.

## Files involved (no new files for this task, apart from this one)

- `app/billing/stripe_provider.py`: the Stripe provider, including the Checkout Session call.
- `app/billing/dependencies.py`: chooses Stripe or the fake.
- `app/billing/router.py`: `POST /api/v1/billing/subscription` (starts checkout) and `POST /api/v1/billing/webhook`.
- `scripts/create_stripe_prices.py`: creates the test prices.

## How it works

1. The client taps Subscribe; the app calls `POST /api/v1/billing/subscription`.
2. The backend creates the Checkout Session and returns its `checkout_url`.
3. The app opens Stripe's hosted page; the client pays.
4. Stripe redirects to `success_url` or `cancel_url`, and separately posts `checkout.session.completed` and `invoice.paid` to the webhook. The webhook, not the redirect, activates the subscription.
5. Renewals, failed payments, plan changes and cancellations keep arriving as webhooks (`invoice.paid`, `invoice.payment_failed`, `customer.subscription.updated`, `customer.subscription.deleted`).

## Testing

- Card `4242 4242 4242 4242` succeeds; `4000 0000 0000 0341` is declined. Use any future date, any CVC and any ZIP code.
- Watch events with `stripe listen`, and replay one with `stripe events resend <event id>`.
- Test mode never moves real money; live keys (`sk_live_…`) are for production only.

## Next steps

- Set the real prices and plan names in the admin panel (Super Admin 8.1 and 8.2), which updates Stripe.
- Decide the open questions in `docs/decisions/stripe-billing.md`: billing during the deletion grace period, refunds on deletion, and whose receipts to send.
- Mobile app: Apple generally requires in-app purchase for digital subscriptions sold in iOS apps (`docs/PLAN.md` question 2).

## Resources

- https://support.stripe.com
- https://docs.stripe.com/mcp
