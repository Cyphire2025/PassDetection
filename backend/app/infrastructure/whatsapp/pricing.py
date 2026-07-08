"""
WhatsApp cost estimation helpers.

Rates change by Meta pricing period, recipient market, category, provider, and
volume tier. Treat these as planning defaults only; billing must use the active
BSP/Meta rate card at send time.
"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

from app.application.dtos.whatsapp_dtos import WhatsAppCostEstimate, WhatsAppMessageCategory

INR = "INR"
PLANNING_RATE_INR: dict[tuple[str, WhatsAppMessageCategory], Decimal] = {
    ("india", "utility"): Decimal("0.1450"),
    ("india", "authentication"): Decimal("0.1450"),
    ("india", "marketing"): Decimal("1.0900"),
    ("rest_of_asia_pacific", "utility"): Decimal("0.8282"),
}


def estimate_whatsapp_cost(
    *,
    market: str,
    category: WhatsAppMessageCategory,
    message_count: int,
    unit_rate: Decimal | None = None,
    currency: str = INR,
) -> WhatsAppCostEstimate:
    if message_count < 0:
        raise ValueError("message_count must be zero or greater")

    normalized_market = market.strip().lower().replace(" ", "_")
    rate = unit_rate if unit_rate is not None else PLANNING_RATE_INR.get((normalized_market, category))
    if rate is None:
        raise ValueError(f"No planning rate configured for {market}/{category}")

    total = (rate * Decimal(message_count)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return WhatsAppCostEstimate(
        market=normalized_market,
        currency=currency,
        category=category,
        message_count=message_count,
        unit_rate=rate,
        estimated_total=total,
        notes=(
            "Planning estimate only.",
            "Provider platform fees, taxes, template category decisions, and live Meta rate changes are excluded.",
        ),
    )
