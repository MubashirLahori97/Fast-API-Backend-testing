"""Billing emails. They hold the plan, the amount and the date only: no health data, no card
details."""

from datetime import datetime

from app.billing import catalog
from app.billing.models import Invoice
from app.core.ages import HAWAII
from app.core.email import EmailMessage


def long_date(moment: datetime) -> str:
    """ "December 5, 2026", on the date in Hawaii: the last US state to reach each date, so a
    date we promise access until has come everywhere the client could be."""
    day = moment.astimezone(HAWAII).date()
    return f"{day:%B} {day.day}, {day.year}"


def receipt(to: str, invoice: Invoice) -> EmailMessage:
    """Story 9.1: a receipt by email once the payment succeeds (and after each renewal)."""
    lines = ["Thank you for your payment.", ""]
    if invoice.plan:
        lines.append(f"Plan: {catalog.plan_name(invoice.plan)}")
    lines += [
        f"Amount: {catalog.format_price(invoice.amount_cents)}",
        f"Date: {long_date(invoice.issued_at)}",
        "",
        "You can see your billing history and download your receipts in Profile & Account, "
        "under Subscription & Billing.",
    ]
    if invoice.receipt_url:
        lines += ["", f"Your receipt: {invoice.receipt_url}"]
    return EmailMessage(to=to, subject="Your receipt from Your Oracle", body="\n".join(lines))
