"""List prices used to estimate what an investigation would cost on the paid tier.

The runs themselves are free-tier and cost nothing. A price appears here only when it was read
from the provider's pricing page; a model that is not listed has no cost estimate.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ListPrice:
    usd_per_m_input: float
    usd_per_m_output: float  # includes thinking tokens
    source: str
    read_on: str


GEMINI_PRICING_URL = "https://ai.google.dev/gemini-api/docs/pricing"

LIST_PRICES: dict[str, ListPrice] = {
    "gemini:gemini-3.5-flash-lite": ListPrice(0.30, 2.50, GEMINI_PRICING_URL, "2026-10-10"),
    "gemini:gemini-3.1-flash-lite": ListPrice(0.25, 1.50, GEMINI_PRICING_URL, "2026-10-10"),
}


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float | None:
    """USD at list price (standard paid tier, text input), or None if the price is unknown."""
    price = LIST_PRICES.get(model)
    if price is None:
        return None
    return (
        input_tokens * price.usd_per_m_input + output_tokens * price.usd_per_m_output
    ) / 1_000_000
