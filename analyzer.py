from config import (
    CURRENCY_TO_MARKETS,
    MARKETS,
)

from gemini_agent import (
    verify_and_analyze_news,
)

from market_data import (
    get_context_for_assets,
)


def choose_assets(candidate):
    # 1. Explicit asset from news discovery
    asset = candidate.get("asset")

    if asset in MARKETS:
        return [asset]

    # 2. Explicit list of assets, if present
    candidate_assets = candidate.get("assets", [])

    if candidate_assets:
        valid_assets = [
            a for a in candidate_assets
            if a in MARKETS
        ]

        if valid_assets:
            return valid_assets[:5]

    # 3. Currency mapping
    currency = candidate.get("currency")

    if currency in CURRENCY_TO_MARKETS:
        return CURRENCY_TO_MARKETS[currency][:5]

    # 4. No usable asset
    return []


def analyze_news_candidate(
    candidate: dict,
):

    assets = choose_assets(
        candidate
    )

    contexts = (
        get_context_for_assets(
            assets
        )
    )

    analysis = (
        verify_and_analyze_news(
            candidate,
            contexts,
        )
    )

    return (
        analysis,
        contexts,
    )