"""Create the launch plans' products and prices in Stripe test mode, and print their ids for .env
(docs/decisions/stripe-billing.md, "How to set up Stripe test mode").

Usage, from the repo root, with STRIPE_SECRET_KEY=sk_test_... in .env:

    uv run python scripts/create_stripe_prices.py

It creates three monthly prices, at the current catalogue prices (the admin panel's rows if
the database is running, otherwise the settings): Individual, Family, and each extra family
member on the Family plan. Copy the printed lines into .env and restart the API and the worker.

Running it again reuses prices that already match the ids in .env, so it's safe to repeat.
It refuses a live key (sk_live_ or rk_live_): live prices are created by the Super Admin's
plan changes in the admin panel, never by this script.
"""

import sys
from pathlib import Path

# Lets `python scripts/create_stripe_prices.py` import the app from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.billing import catalog  # noqa: E402
from app.billing.provider import PlanSetup, ProviderError  # noqa: E402
from app.billing.stripe_provider import StripeProvider  # noqa: E402
from app.core.config import settings  # noqa: E402


def _fail(message: str) -> None:
    print(message, file=sys.stderr)
    sys.exit(1)


def main() -> None:
    key = settings.stripe_secret_key
    if not key:
        _fail("Set STRIPE_SECRET_KEY=sk_test_... in .env first.")
    if key.startswith(("sk_live_", "rk_live_")):
        _fail("That's a live Stripe key. This script only runs in test mode (sk_test_...).")
    if not key.startswith(("sk_test_", "rk_test_")):
        _fail("STRIPE_SECRET_KEY doesn't look like a Stripe test key (sk_test_...).")

    provider = StripeProvider(api_key=key)
    individual = catalog.values("individual")
    family = catalog.values("family")
    try:
        individual_setup = provider.set_up_plan(
            PlanSetup(
                code="individual",
                name=individual.name,
                monthly_price_cents=individual.monthly_price_cents,
                currency=settings.billing_currency,
                price_id=individual.stripe_price_id,
            )
        )
        family_setup = provider.set_up_plan(
            PlanSetup(
                code="family",
                name=family.name,
                monthly_price_cents=family.monthly_price_cents,
                currency=settings.billing_currency,
                add_on_price_cents=family.add_on_price_cents,
                price_id=family.stripe_price_id,
                add_on_price_id=family.stripe_add_on_price_id,
            )
        )
    except ProviderError:
        _fail("Stripe refused or couldn't be reached. Check the key and try again.")

    print("# Stripe test mode prices: copy these lines into .env")
    print(f"STRIPE_INDIVIDUAL_PRICE_ID={individual_setup.price_id}")
    print(f"STRIPE_FAMILY_PRICE_ID={family_setup.price_id}")
    print(f"STRIPE_FAMILY_ADD_ON_PRICE_ID={family_setup.add_on_price_id}")


if __name__ == "__main__":
    main()
