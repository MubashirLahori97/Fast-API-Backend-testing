"""The email that tells an existing subscriber their plan's price is changing (Super Admin 8.1:
"existing subscribers pay it from their next billing date, after they've been told"). It holds
the plan's name and price only. The text isn't in the stories
(docs/decisions/phase-a2-admin-operations.md)."""

from app.billing import catalog
from app.core.email import EmailMessage


def price_change(
    to: str,
    plan_name: str,
    monthly_price_cents: int | None,
    add_on_price_cents: int | None,
) -> EmailMessage:
    lines = []
    if monthly_price_cents is not None:
        lines.append(
            f"The price of your {plan_name} plan is changing to "
            f"{catalog.format_price(monthly_price_cents)} a month."
        )
    if add_on_price_cents is not None:
        lines.append(
            f"The price of each extra family member on your {plan_name} plan is changing to "
            f"{catalog.format_price(add_on_price_cents)} a month."
        )
    return EmailMessage(
        to=to,
        subject="A change to your plan’s price",
        body=(
            "\n".join(lines) + "\n\n"
            "You’ll pay the new price from your next billing date. You can change or cancel your "
            "plan anytime in Profile & Account."
        ),
    )
