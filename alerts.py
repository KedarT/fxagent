from config import (
    ALERT_COOLDOWN_MINUTES,
)

from database import (
    alert_allowed,
    mark_alert_sent,
    stable_hash,
    topic_hash,
)

from models import (
    Analysis,
    MarketContext,
)


def _fmt_price(
    value,
):

    if value is None:
        return "—"

    if value >= 100:
        return f"{value:,.2f}"

    if value >= 10:
        return f"{value:,.3f}"

    return f"{value:,.5f}"


def _trend_icon(
    trend: str,
):

    return {
        "Bullish":
            "🟢 Bullish",

        "Bearish":
            "🔴 Bearish",

        "Mixed":
            "🟡 Mixed",

        "Unavailable":
            "⚪ Unavailable",
    }.get(
        trend,
        "⚪ Unknown",
    )


def build_telegram_message(
    candidate: dict,
    analysis: Analysis,
    contexts: list[
        MarketContext
    ],
):

    assets = (
        analysis.affected_assets
        or [
            m.asset
            for m in contexts
        ]
    )

    asset_label = ", ".join(
        assets[:4]
    )

    impact_icon = {
        "CRITICAL": "🚨",
        "HIGH": "🚨",
        "MEDIUM": "⚠️",
        "LOW": "ℹ️",
    }.get(
        analysis.impact,
        "⚠️",
    )

    lines = [

        f"{impact_icon} "
        f"{analysis.impact} IMPACT",

        asset_label,

        "",

        candidate.get(
            "title",
            "Market development",
        ),

        "",

        f"Macro: "
        f"{analysis.macro_bias}",

        f"Technical: "
        f"{analysis.technical_bias}",

        f"Alignment: "
        f"{analysis.alignment}",

        f"Risk: "
        f"{analysis.risk}",

        "",

        analysis.summary,

        analysis.technical_summary,
    ]

    relevant = [
        m
        for m in contexts
        if m.asset in assets
    ]

    if relevant:

        lines += [
            "",
            "📊 Market context",
        ]

        for m in relevant[:3]:

            lines.append(
                f"{m.asset}: "
                f"{_fmt_price(m.price)} | "
                f"EMA50 "
                f"{_fmt_price(m.ema50)} | "
                f"EMA200 "
                f"{_fmt_price(m.ema200)} | "
                f"{_trend_icon(m.trend)}"
            )

    source = (
        analysis.source_name
        or candidate.get(
            "source",
            "",
        )
    )

    url = (
        analysis.source_url
        or candidate.get(
            "url",
            "",
        )
    )

    if source:

        lines += [
            "",
            f"Source: {source}",
        ]

    if url:

        lines.append(
            f"🔗 {url}"
        )

    return "\n".join(
        lines
    )


def should_send_alert(
    candidate: dict,
    analysis: Analysis,
    asset: str,
):

    if not analysis.should_alert:
        return False, ""

    if analysis.impact not in {
        "HIGH",
        "CRITICAL",
        "MEDIUM",
    }:

        return False, ""

    if (
        analysis.confidence.lower()
        == "low"
    ):

        return False, ""

    topic = topic_hash(
        candidate.get(
            "title",
            "",
        ),
        asset,
    )

    if not alert_allowed(
        topic,
        ALERT_COOLDOWN_MINUTES,
    ):

        return False, ""

    return True, topic


def alert_hash(
    candidate: dict,
    analysis: Analysis,
    asset: str,
):

    return stable_hash(
        candidate.get(
            "title",
            "",
        ),
        candidate.get(
            "url",
            "",
        ),
        asset,
        analysis.macro_bias,
        analysis.technical_bias,
    )


def record_alert(
    candidate: dict,
    analysis: Analysis,
    asset: str,
    topic: str,
):

    mark_alert_sent(
        alert_hash(
            candidate,
            analysis,
            asset,
        ),
        topic,
        asset,
        candidate.get(
            "title",
            "",
        ),
    )