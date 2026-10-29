from datetime import datetime, timezone, timedelta

from google import genai
from google.genai import types

from config import (
    GEMINI_API_KEY,
    NEWS_LOOKBACK_HOURS,
    NEWS_MAX_CANDIDATES,
    MARKETS,
    MODEL_NAME,
)

from models import (
    Analysis,
    MarketContext,
)


# ============================================================
# Gemini client
# ============================================================

client = genai.Client(
    api_key=GEMINI_API_KEY
)


# ============================================================
# Gemini Google Search configuration
# ============================================================

def _search_config():

    return types.GenerateContentConfig(
        tools=[
            types.Tool(
                google_search=types.GoogleSearch()
            )
        ],
        temperature=0.1,
        max_output_tokens=1200,
    )


def _news_discovery_config():

    print("USING NEWS DISCOVERY CONFIG")

    return types.GenerateContentConfig(
        #tools=[
        #    types.Tool(
        #        google_search=types.GoogleSearch()
        #    )
        #],
        temperature=0.1,
        max_output_tokens=300,
    )


# ============================================================
# Simple KEY: VALUE parser
# ============================================================

def _parse_key_value_text(text: str):

    result = {}

    for raw_line in (text or "").splitlines():

        line = raw_line.strip()

        if not line:
            continue

        if ":" not in line:
            continue

        key, value = line.split(":", 1)

        key = key.strip().upper()
        value = value.strip()

        if key and value:
            result[key] = value

    return result


def _parse_discovery_response(text: str) -> list[dict]:
    results = []
    valid_assets = {asset.upper() for asset in MARKETS.keys()}

    for raw_line in (text or "").splitlines():
        line = raw_line.strip()

        if not line or "|" not in line:
            continue

        asset, title = line.split("|", 1)

        asset = asset.strip().upper()
        title = title.strip()

        if asset not in valid_assets:
            continue

        if not title:
            continue

        results.append({
            "asset": asset,
            "title": title,
        })

    return results[:3]


# ============================================================
# Discover recent financial news
#
# Output format:
#
# ASSET | SHORT HEADLINE
#
# No JSON.
# ============================================================

def discover_recent_news() -> list[dict]:
    now = datetime.now(timezone.utc)
    since = now - timedelta(hours=NEWS_LOOKBACK_HOURS)

    prompt = f"""
Find the most important NEW financial/macro development from the last
{NEWS_LOOKBACK_HOURS} hours that could materially affect one of these markets:

{", ".join(MARKETS.keys())}

Focus only on:
- central-bank decisions/comments
- major inflation/employment/GDP surprises
- tariffs/trade policy
- wars/geopolitical developments
- oil/energy shocks
- FX intervention
- major fiscal/government decisions

Do NOT return routine economic-calendar events unless something unexpected
changed.

Return AT MOST 3 lines.

Each line MUST use exactly:
ASSET | SHORT HEADLINE

Valid assets:
{", ".join(MARKETS.keys())}

No explanations.
No markdown.
No JSON.
"""

    try:
        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=prompt,
            config=_news_discovery_config(),
        )

        raw = getattr(response, "text", None)

        print("--- GEMINI RAW RESPONSE ---")
        print(raw)
        print("--- END GEMINI RESPONSE ---")

        if not raw:
            print("Gemini discovery returned no text.")
            return []

        return _parse_discovery_response(raw)

    except Exception as exc:
        print(f"News discovery error: {exc}")
        return []

# ============================================================
# Extract Google Search grounding sources
# ============================================================

def get_grounding_sources(response):

    sources = []

    try:

        metadata = (
            response
            .candidates[0]
            .grounding_metadata
        )

        chunks = (
            getattr(
                metadata,
                "grounding_chunks",
                None,
            )
            or []
        )

        for chunk in chunks:

            web = getattr(
                chunk,
                "web",
                None,
            )

            if not web:
                continue

            url = getattr(
                web,
                "uri",
                None,
            )

            title = getattr(
                web,
                "title",
                None,
            )

            if url:

                sources.append(
                    {
                        "title": title or "",
                        "url": url,
                    }
                )

    except Exception:
        pass

    return sources


# ============================================================
# Deep news verification + market analysis
#
# Output format:
#
# IMPACT: HIGH
# BIAS: BULLISH
# TECHNICAL: BEARISH
# ALIGNMENT: CONTRADICTORY
# RISK: HIGH
# ALERT: YES
# SUMMARY: ...
# TECHNICAL_SUMMARY: ...
#
# No JSON.
# ============================================================

def verify_and_analyze_news(
    candidate: dict,
    market_contexts: list[MarketContext],
):

    context_text = "\n".join(
        (
            f"- {m.asset}: "
            f"price={m.price}, "
            f"EMA50={m.ema50}, "
            f"EMA200={m.ema200}, "
            f"trend={m.trend}, "
            f"15m_change={m.change_pct}, "
            f"ATR%={m.atr_pct}"
        )
        for m in market_contexts
    )

    prompt = f"""
Role: Financial macro analyst.

Verify and analyze this development using Google Search.

Headline:
{candidate.get("title", "")}

Asset:
{candidate.get("asset", "")}

Current market context:
{context_text}

Determine whether this is genuinely material to the specified asset.

Consider:
- macroeconomic impact
- monetary policy implications
- supply/demand implications
- geopolitical implications
- current technical trend
- whether macro and technical signals agree

Return ONLY these lines:

IMPACT: HIGH|MEDIUM|LOW
BIAS: BULLISH|BEARISH|MIXED|NEUTRAL
TECHNICAL: BULLISH|BEARISH|MIXED|NEUTRAL
ALIGNMENT: ALIGNED|CONTRADICTORY|MIXED
RISK: HIGH|MEDIUM|LOW
ALERT: YES|NO
SUMMARY: one concise factual sentence
TECHNICAL_SUMMARY: one concise sentence

Alert YES only if the development is genuinely material
and could reasonably move the specified asset.

Do not use JSON.
Do not use markdown.
Do not add other fields.
"""

    try:

        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=prompt,
            config=_search_config(),
        )

        print("--- GEMINI ANALYSIS ---")
        print(response.text)
        print("--- END GEMINI ANALYSIS ---")

        data = _parse_key_value_text(
            response.text
        )

        if not data:

            raise ValueError(
                "Gemini returned no usable analysis"
            )

        grounding = get_grounding_sources(
            response
        )

        source_name = ""
        source_url = ""
        evidence = ""

        if grounding:

            source_name = grounding[0].get(
                "title",
                "",
            )

            source_url = grounding[0].get(
                "url",
                "",
            )

            evidence = (
                "Verified using Google Search grounding."
            )

        alert_value = data.get(
            "ALERT",
            "NO",
        ).upper()

        affected_asset = candidate.get(
            "asset"
        )

        return Analysis(

            macro_bias=data.get(
                "BIAS",
                "MIXED",
            ),

            technical_bias=data.get(
                "TECHNICAL",
                "MIXED",
            ),

            alignment=data.get(
                "ALIGNMENT",
                "MIXED",
            ),

            risk=data.get(
                "RISK",
                "MEDIUM",
            ),

            summary=data.get(
                "SUMMARY",
                "",
            ),

            technical_summary=data.get(
                "TECHNICAL_SUMMARY",
                "",
            ),

            should_alert=(
                alert_value == "YES"
            ),

            impact=data.get(
                "IMPACT",
                "LOW",
            ).upper(),

            # We are deliberately not asking Gemini
            # for a confidence field anymore.
            confidence="Medium",

            affected_assets=(
                [affected_asset]
                if affected_asset
                else []
            ),

            source_name=source_name,

            source_url=source_url,

            evidence=evidence,

            raw=data,
        )

    except Exception as exc:

        print(
            "Gemini analysis error: "
            f"{exc}"
        )

        return Analysis(

            macro_bias="Unknown",

            technical_bias="Unknown",

            alignment="Unavailable",

            risk="High",

            summary="Analysis unavailable.",

            technical_summary=(
                "Market analysis unavailable."
            ),

            should_alert=False,

            impact="LOW",

            confidence="Low",

            affected_assets=[],

            source_name="",

            source_url="",

            evidence="",
        )


# ============================================================
# Verify actual economic calendar release
#
# This remains JSON because this call is specifically
# retrieving structured economic data.
# ============================================================

def get_actual_with_gemini(
    event: dict,
):

    prompt = f"""
Verify the actual released result for this economic event
using Google Search.

Event name:
{event.get("name")}

Title:
{event.get("title")}

Scheduled UTC:
{event.get("time_utc")}

Date:
{event.get("date")}

Consensus:
{event.get("consensus")}

Prior:
{event.get("prior")}

Find the actual released figure from the official publisher
where possible.

Prefer:
BEA
BLS
Federal Reserve
ECB
Eurostat
ONS
BoE
BoJ
RBA
BoC
RBNZ
SNB

Do not confuse:
actual
consensus
prior
revision

If the actual cannot be verified, return:

found=false

Return ONLY JSON:

{{
  "found": true,
  "actual": "2.2%",
  "unit": "percent",
  "period": "Q2 2026",
  "is_revision": false,
  "source_name": "official publisher",
  "source_url": "https://...",
  "evidence": "short factual sentence",
  "confidence": "high"
}}
"""

    try:

        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=prompt,
            config=_search_config(),
        )

        # ----------------------------------------------------
        # Calendar verification still expects JSON.
        # Use Gemini's raw response but extract the JSON
        # object without requiring response_mime_type.
        # ----------------------------------------------------

        text = (
            response.text or ""
        ).strip()

        data = None

        # First attempt
        try:
            import json

            data = json.loads(text)

        except Exception:
            pass

        # Second attempt: locate object
        if data is None:

            start = text.find("{")
            end = text.rfind("}")

            if (
                start != -1
                and end != -1
                and end > start
            ):

                try:

                    import json

                    data = json.loads(
                        text[start:end + 1]
                    )

                except Exception:
                    data = None

        if not isinstance(data, dict):

            raise ValueError(
                "Could not parse calendar verification response"
            )

        if not data.get("found"):

            return None

        grounding = get_grounding_sources(
            response
        )

        if grounding and not data.get(
            "source_url"
        ):

            data["source_url"] = (
                grounding[0]["url"]
            )

        if grounding and not data.get(
            "source_name"
        ):

            data["source_name"] = (
                grounding[0]["title"]
            )

        return data

    except Exception as exc:

        print(
            "Release verification error: "
            f"{exc}"
        )

        return None