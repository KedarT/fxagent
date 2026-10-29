import os
import re
import json
import time
import signal
import sqlite3
import hashlib
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, List, Tuple

import requests
import yfinance as yf
from dotenv import load_dotenv
from google import genai
from google.genai import types
from apscheduler.schedulers.background import BackgroundScheduler


# ============================================================
# CONFIG
# ============================================================

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

FINANCE_CALENDAR_BASE_URL = "https://www.financecalendar.com/wp-json/fc/v1"

DB_FILE = "multicurrency_agent.db"

CHECK_INTERVAL_MINUTES = 15
CALENDAR_LIMIT = 500

DEBUG_CALENDAR_EVENTS = True

GEMINI_MODEL = "gemini-2.5-flash"

SUPPORTED_CURRENCIES = {
    "USD",
    "EUR",
    "GBP",
    "JPY",
    "AUD",
    "CAD",
    "CHF",
    "NZD",
}

SUPPORTED_IMPACTS = {
    "high",
    "medium",
}

CURRENCY_TO_PAIR = {
    "USD": "EURUSD=X",
    "EUR": "EURUSD=X",
    "GBP": "GBPUSD=X",
    "JPY": "USDJPY=X",
    "AUD": "AUDUSD=X",
    "CAD": "USDCAD=X",
    "CHF": "USDCHF=X",
    "NZD": "NZDUSD=X",
}


# ============================================================
# VALIDATION
# ============================================================

if not TELEGRAM_BOT_TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN missing from .env")

if not TELEGRAM_CHAT_ID:
    raise RuntimeError("TELEGRAM_CHAT_ID missing from .env")

if not GEMINI_API_KEY:
    raise RuntimeError("GEMINI_API_KEY missing from .env")


# ============================================================
# CLIENTS
# ============================================================

gemini_client = genai.Client(api_key=GEMINI_API_KEY)

scheduler = None


# ============================================================
# DATABASE
# ============================================================

def init_db():
    conn = sqlite3.connect(DB_FILE)

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS analyzed_events (
            event_hash TEXT PRIMARY KEY,
            event_name TEXT,
            event_date TEXT,
            timestamp TEXT
        )
        """
    )

    conn.commit()
    conn.close()


def is_event_processed(event_hash: str) -> bool:
    conn = sqlite3.connect(DB_FILE)

    row = conn.execute(
        """
        SELECT 1
        FROM analyzed_events
        WHERE event_hash = ?
        """,
        (event_hash,),
    ).fetchone()

    conn.close()

    return row is not None


def mark_event_processed(
    event_hash: str,
    event_name: str,
    event_date: str,
):
    conn = sqlite3.connect(DB_FILE)

    conn.execute(
        """
        INSERT OR IGNORE INTO analyzed_events
        (
            event_hash,
            event_name,
            event_date,
            timestamp
        )
        VALUES (?, ?, ?, ?)
        """,
        (
            event_hash,
            event_name,
            event_date,
            datetime.now(timezone.utc).isoformat(),
        ),
    )

    conn.commit()
    conn.close()


# ============================================================
# TELEGRAM
# ============================================================

def send_telegram(message: str) -> bool:
    url = (
        f"https://api.telegram.org/"
        f"bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    )

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "disable_web_page_preview": True,
    }

    try:
        response = requests.post(
            url,
            json=payload,
            timeout=20,
        )

        print(
            f"Telegram: {response.status_code}"
        )

        if response.ok:
            return True

        print(
            f"Telegram error: {response.text[:300]}"
        )

        return False

    except Exception as exc:
        print(
            f"Telegram error: {exc}"
        )
        return False

# ============================================================
# FINANCE CALENDAR
# ============================================================

def get_calendar_events() -> List[Dict[str, Any]]:
    """
    Fetch yesterday + today.

    Yesterday is included because some calendar providers
    may update actual values after the initial publication.
    """

    now = datetime.now(timezone.utc)

    yesterday = (
        now.date() - timedelta(days=1)
    ).isoformat()

    today = now.date().isoformat()

    params = {
        "from": yesterday,
        "to": today,
        "impact": "high,medium",
        "limit": CALENDAR_LIMIT,
    }

    url = f"{FINANCE_CALENDAR_BASE_URL}/calendar"

    try:
        response = requests.get(
            url,
            params=params,
            timeout=30,
        )

        print(
            f"Finance Calendar status: "
            f"{response.status_code}"
        )

        response.raise_for_status()

        data = response.json()

        if isinstance(data, dict):
            events = data.get("events", data.get("data", []))
        else:
            events = data

        if not isinstance(events, list):
            print("Unexpected calendar response format.")
            return []

        print(
            f"Finance Calendar returned "
            f"{len(events)} events."
        )

        return events

    except Exception as exc:
        print(
            f"Finance Calendar error: {exc}"
        )

        return []


# ============================================================
# CURRENCY DETECTION
# ============================================================

def normalize_currency(
    event: Dict[str, Any]
) -> Optional[str]:

    direct_currency = event.get("currency")

    if direct_currency:
        direct_currency = str(
            direct_currency
        ).upper().strip()

        if direct_currency in SUPPORTED_CURRENCIES:
            return direct_currency

    text = " ".join(
        [
            str(event.get("name", "")),
            str(event.get("title", "")),
            str(event.get("category", "")),
        ]
    ).upper()

    currency_patterns = {
        "USD": [
            "US ",
            "U.S.",
            "UNITED STATES",
            "FED ",
            "FEDERAL RESERVE",
            "FOMC",
            "DOLLAR",
            "GDP",
            "NONFARM",
            "PAYROLL",
            "CPI",
            "PCE",
            "ISM",
            "RETAIL SALES",
            "UNEMPLOYMENT RATE",
            "JOBLESS CLAIMS",
        ],
        "EUR": [
            "EURO",
            "EUROZONE",
            "EURO AREA",
            "ECB",
            "GERMANY",
            "FRANCE",
            "ITALY",
            "SPAIN",
        ],
        "GBP": [
            "UK ",
            "U.K.",
            "UNITED KINGDOM",
            "BOE",
            "BANK OF ENGLAND",
            "BRITAIN",
            "BRITISH",
        ],
        "JPY": [
            "JAPAN",
            "BOJ",
            "BANK OF JAPAN",
            "YEN",
        ],
        "AUD": [
            "AUSTRALIA",
            "RBA",
            "RESERVE BANK OF AUSTRALIA",
        ],
        "CAD": [
            "CANADA",
            "BOC",
            "BANK OF CANADA",
        ],
        "CHF": [
            "SWITZERLAND",
            "SNB",
            "SWISS NATIONAL BANK",
        ],
        "NZD": [
            "NEW ZEALAND",
            "RBNZ",
            "RESERVE BANK OF NEW ZEALAND",
        ],
    }

    for currency, patterns in currency_patterns.items():
        for pattern in patterns:
            if pattern in text:
                return currency

    return None


# ============================================================
# RELEASE TIME
# ============================================================

def event_release_has_occurred(
    event: Dict[str, Any]
) -> bool:

    now = datetime.now(timezone.utc)

    event_date = event.get("date")

    if not event_date:
        return False

    try:
        release_date = datetime.strptime(
            str(event_date),
            "%Y-%m-%d",
        ).date()
    except ValueError:
        return False

    # Historical date
    if release_date < now.date():
        return True

    # Future date
    if release_date > now.date():
        return False

    # Same day
    time_utc = event.get("time_utc")

    # If it is an all-day event, allow Gemini to search
    # because there may not be a precise publication time.
    if event.get("all_day"):
        return True

    if not time_utc:
        return False

    try:
        parsed = datetime.fromisoformat(
            str(time_utc).replace("Z", "+00:00")
        )

        if parsed.tzinfo is None:
            parsed = parsed.replace(
                tzinfo=timezone.utc
            )

        return parsed <= now

    except Exception:
        return False


# ============================================================
# JSON HELPERS
# ============================================================

def extract_json_object(text: str) -> Optional[Dict[str, Any]]:
    """
    Extract JSON even if Gemini surrounds it with markdown.
    """

    if not text:
        return None

    cleaned = text.strip()

    # Remove markdown fences
    cleaned = re.sub(
        r"^```(?:json)?\s*",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )

    cleaned = re.sub(
        r"\s*```$",
        "",
        cleaned,
    )

    try:
        parsed = json.loads(cleaned)

        if isinstance(parsed, dict):
            return parsed

    except json.JSONDecodeError:
        pass

    # Find first JSON object
    start = cleaned.find("{")
    end = cleaned.rfind("}")

    if start >= 0 and end > start:
        candidate = cleaned[start:end + 1]

        try:
            parsed = json.loads(candidate)

            if isinstance(parsed, dict):
                return parsed

        except json.JSONDecodeError:
            pass

    return None


# ============================================================
# GEMINI GROUNDING SOURCES
# ============================================================

def get_grounding_sources(response) -> List[Dict[str, str]]:
    """
    Extract web sources returned by Gemini Search grounding.

    The Google GenAI SDK exposes grounding chunks containing
    web title + URI.
    """

    sources = []

    try:
        metadata = (
            response.candidates[0].grounding_metadata
        )

        if not metadata:
            return sources

        chunks = (
            metadata.grounding_chunks or []
        )

        for chunk in chunks:
            web = getattr(chunk, "web", None)

            if not web:
                continue

            uri = getattr(web, "uri", None)
            title = getattr(web, "title", None)

            if uri:
                sources.append(
                    {
                        "title": title or "",
                        "url": uri,
                    }
                )

    except Exception as exc:
        print(
            f"Could not extract Gemini grounding sources: "
            f"{exc}"
        )

    # Remove duplicates
    unique = []

    seen = set()

    for source in sources:
        url = source["url"]

        if url not in seen:
            seen.add(url)
            unique.append(source)

    return unique


# ============================================================
# GEMINI RELEASE FINDER
# ============================================================

def get_actual_with_gemini(
    event: Dict[str, Any],
    currency: str,
) -> Optional[Dict[str, Any]]:

    name = event.get("name", "")
    title = event.get("title", "")
    date = event.get("date", "")
    time_utc = event.get("time_utc", "")
    consensus = event.get("consensus")
    prior = event.get("prior")

    prompt = f"""
You are a macroeconomic release verification agent.

Your job is to find the ACTUAL RELEASED VALUE of a specific
economic event using current web search.

EVENT
-----
Name: {name}
Title: {title}
Currency: {currency}
Date: {date}
Scheduled UTC time: {time_utc}
Calendar consensus: {consensus}
Calendar prior: {prior}

IMPORTANT RULES
---------------
1. Search the live web.
2. Prefer the official publishing institution.
3. Examples of official sources include:
   - BEA for US GDP
   - BLS for US employment/CPI
   - Federal Reserve for Fed decisions
   - ECB / Eurostat for euro-area releases
   - ONS / Bank of England for UK releases
   - Statistics Bureau of Japan / Bank of Japan
   - ABS / RBA for Australia
   - Statistics Canada / Bank of Canada
   - SNB / Swiss statistics
   - Stats NZ / RBNZ
4. Do NOT use the forecast or consensus as the actual.
5. Do NOT use the prior value as the actual.
6. Do NOT use a calendar page merely showing that an event
   exists as evidence that the actual was released.
7. Distinguish revised values from the originally released
   value. If the current official source reports a revision,
   clearly state that it is revised.
8. If the actual cannot be reliably verified, return found=false.
9. Never guess.
10. The source URL must be a page actually returned by web search.
11. Return JSON only.

Return exactly this structure:

{{
  "found": true,
  "actual": "2.2%",
  "unit": "percent",
  "period": "Q2 2026",
  "is_revision": false,
  "source_name": "U.S. Bureau of Economic Analysis",
  "source_url": "https://...",
  "evidence": "Brief description of what the official source reports.",
  "confidence": "high"
}}

If you cannot verify the actual:

{{
  "found": false,
  "actual": null,
  "unit": null,
  "period": null,
  "is_revision": false,
  "source_name": null,
  "source_url": null,
  "evidence": "Why the actual could not be verified.",
  "confidence": "low"
}}
"""

    try:
        response = gemini_client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                tools=[
                    types.Tool(
                        google_search=types.GoogleSearch()
                    )
                ],
                temperature=0.0,
            ),
        )

        response_text = response.text or ""

        print(
            "\nGemini release finder response:"
        )

        print(response_text)

        result = extract_json_object(
            response_text
        )

        if not result:
            print(
                "Gemini release finder did not return valid JSON."
            )
            return None

        found = result.get("found")

        if found is not True:
            print(
                "Gemini could not verify the actual."
            )
            return None

        actual = result.get("actual")

        if actual is None or str(actual).strip() == "":
            print(
                "Gemini returned found=true but no actual."
            )
            return None

        # ----------------------------------------------------
        # Verify that Gemini actually performed grounded search
        # and gave us source material.
        # ----------------------------------------------------

        sources = get_grounding_sources(response)

        if not sources:
            print(
                "Gemini returned no grounding sources."
            )

            return None

        # ----------------------------------------------------
        # Verify source_url against grounding sources.
        # ----------------------------------------------------

        requested_source_url = result.get(
            "source_url"
        )

        grounded_urls = {
            source["url"]
            for source in sources
        }

        if (
            requested_source_url
            and requested_source_url in grounded_urls
        ):
            verified_source_url = requested_source_url

        else:
            # If Gemini's JSON URL doesn't exactly match one
            # of the grounding URLs, use the first grounded
            # source rather than trusting an ungrounded URL.
            verified_source_url = sources[0]["url"]

        verified_source_name = (
            result.get("source_name")
            or sources[0]["title"]
            or "Web source"
        )

        print(
            "\nGrounded sources:"
        )

        for source in sources:
            print(
                f" - {source['title']} "
                f"{source['url']}"
            )

        return {
            "actual": str(actual).strip(),
            "unit": result.get("unit"),
            "period": result.get("period"),
            "is_revision": bool(
                result.get("is_revision", False)
            ),
            "source_name": verified_source_name,
            "source_url": verified_source_url,
            "evidence": result.get("evidence", ""),
            "confidence": result.get(
                "confidence",
                "medium",
            ),
            "grounding_sources": sources,
        }

    except Exception as exc:
        print(
            f"Gemini release finder error: {exc}"
        )

        return None


# ============================================================
# EVENT HASH
# ============================================================

def create_event_hash(
    event: Dict[str, Any],
    currency: str,
    actual: str,
) -> str:

    raw = "|".join(
        [
            str(event.get("name", "")),
            str(event.get("title", "")),
            str(event.get("date", "")),
            str(event.get("time_utc", "")),
            currency,
            str(actual),
        ]
    )

    return hashlib.sha256(
        raw.encode("utf-8")
    ).hexdigest()


# ============================================================
# GET FRESH MACRO EVENTS
# ============================================================

def get_fresh_macro_events() -> List[Dict[str, Any]]:

    events = get_calendar_events()

    fresh_events = []

    print(
        f"\nChecking {len(events)} calendar events..."
    )

    for event in events:

        name = event.get("name", "")
        title = event.get("title", "")

        currency = normalize_currency(event)

        impact = str(
            event.get("impact", "")
        ).lower()

        actual = event.get("actual")

        print("\n--------------------------------")
        print(f"Event: {name}")
        print(f"Title: {title}")
        print(f"Currency: {currency}")
        print(f"Impact: {impact}")
        print(f"Calendar actual: {actual}")
        print(f"Date: {event.get('date')}")
        print(f"UTC: {event.get('time_utc')}")

        # ----------------------------------------------------
        # Currency filter
        # ----------------------------------------------------

        if currency not in SUPPORTED_CURRENCIES:
            print(
                "SKIP: unsupported or unknown currency"
            )
            continue

        # ----------------------------------------------------
        # Impact filter
        # ----------------------------------------------------

        if impact not in SUPPORTED_IMPACTS:
            print(
                "SKIP: impact not high/medium"
            )
            continue

        # ----------------------------------------------------
        # If calendar has actual, use it.
        # ----------------------------------------------------

        actual_source = "Finance Calendar"
        actual_metadata = None

        if actual is not None and str(actual).strip() != "":
            print(
                f"Using Finance Calendar actual: {actual}"
            )

        else:
            # ------------------------------------------------
            # Actual missing.
            # Make sure release should already have happened.
            # ------------------------------------------------

            if not event_release_has_occurred(event):
                print(
                    "SKIP: release time has not occurred yet"
                )
                continue

            print(
                "Actual missing. "
                "Asking Gemini + Google Search..."
            )

            actual_metadata = get_actual_with_gemini(
                event=event,
                currency=currency,
            )

            if not actual_metadata:
                print(
                    "SKIP: Gemini could not verify actual."
                )
                continue

            actual = actual_metadata["actual"]

            actual_source = (
                actual_metadata["source_name"]
            )

            print(
                f"Verified actual: {actual}"
            )

            print(
                f"Source: {actual_source}"
            )

            print(
                f"URL: {actual_metadata['source_url']}"
            )

        # ----------------------------------------------------
        # Sanity check
        # ----------------------------------------------------

        if actual is None:
            print(
                "SKIP: actual is still missing"
            )
            continue

        actual = str(actual).strip()

        if actual.lower() in {
            "",
            "null",
            "none",
            "pending",
            "n/a",
            "na",
        }:
            print(
                "SKIP: invalid/pending actual"
            )
            continue

        # ----------------------------------------------------
        # Duplicate detection
        # ----------------------------------------------------

        event_hash = create_event_hash(
            event=event,
            currency=currency,
            actual=actual,
        )

        if is_event_processed(event_hash):
            print(
                "SKIP: already processed"
            )
            continue

        print(
            "QUALIFIED EVENT"
        )

        fresh_events.append(
            {
                "event": event,
                "currency": currency,
                "actual": actual,
                "actual_source": actual_source,
                "actual_metadata": actual_metadata,
                "event_hash": event_hash,
            }
        )

    print(
        f"\nNew qualifying macro events: "
        f"{len(fresh_events)}"
    )

    return fresh_events


# ============================================================
# TECHNICAL ANALYSIS
# ============================================================

def get_technical_context(
    ticker: str,
) -> Optional[Dict[str, Any]]:

    print(
        f"Downloading Yahoo Finance data: {ticker}"
    )

    try:
        df = yf.download(
            ticker,
            period="5d",
            interval="15m",
            progress=False,
            auto_adjust=False,
        )

        if df is None or df.empty:
            print(
                "Yahoo Finance returned no data."
            )
            return None

        # Handle MultiIndex columns
        if hasattr(df.columns, "nlevels"):
            if df.columns.nlevels > 1:
                df.columns = df.columns.get_level_values(0)

        if "Close" not in df.columns:
            print(
                "Close column missing."
            )
            return None

        df = df.dropna(
            subset=["Close"]
        ).copy()

        if len(df) < 200:
            print(
                f"Not enough candles: {len(df)}"
            )
            return None

        close = df["Close"]

        df["EMA50"] = (
            close.ewm(
                span=50,
                adjust=False,
            ).mean()
        )

        df["EMA200"] = (
            close.ewm(
                span=200,
                adjust=False,
            ).mean()
        )

        latest_close = float(
            df["Close"].iloc[-1]
        )

        ema50 = float(
            df["EMA50"].iloc[-1]
        )

        ema200 = float(
            df["EMA200"].iloc[-1]
        )

        if (
            latest_close > ema50
            and ema50 > ema200
        ):
            trend = "Bullish"

        elif (
            latest_close < ema50
            and ema50 < ema200
        ):
            trend = "Bearish"

        else:
            trend = "Mixed / Transitional"

        return {
            "ticker": ticker,
            "timeframe": "15m",
            "price": latest_close,
            "ema50": ema50,
            "ema200": ema200,
            "trend": trend,
            "candles": len(df),
        }

    except Exception as exc:
        print(
            f"Technical data error: {exc}"
        )

        return None


# ============================================================
# GEMINI MARKET ANALYSIS
# ============================================================

def analyze_with_gemini(
    event: Dict[str, Any],
    currency: str,
    actual: str,
    actual_source: str,
    actual_metadata: Optional[Dict[str, Any]],
    technical: Dict[str, Any],
) -> Optional[Dict[str, str]]:

    name = event.get("name", "")
    title = event.get("title", "")
    consensus = event.get("consensus")
    prior = event.get("prior")

    prompt = f"""
You are a professional macro FX alert engine.

Analyze this economic release and technical context.

EVENT
-----
Event: {name}
Title: {title}
Currency: {currency}
Actual: {actual}
Consensus: {consensus}
Prior: {prior}

TECHNICAL
---------
Pair: {technical["ticker"]}
Price: {technical["price"]}
EMA50: {technical["ema50"]}
EMA200: {technical["ema200"]}
Trend: {technical["trend"]}

Return JSON ONLY.

Use exactly this structure:

{{
  "macro_bias": "USD positive",
  "alignment": "Bearish EURUSD",
  "risk": "Moderate",
  "summary": "One short sentence explaining the macro result.",
  "technical_summary": "One short sentence explaining the technical setup."
}}

RULES
-----
- Keep every field SHORT.
- macro_bias: maximum 4 words.
- alignment: maximum 4 words.
- risk: Low, Moderate, or High.
- summary: maximum 20 words.
- technical_summary: maximum 20 words.
- Do not give trade instructions.
- Do not give price targets.
- Do not give stop loss or take profit.
- Do not invent data.
- Do not use markdown.
"""

    try:
        response = gemini_client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.1,
                max_output_tokens=300,
            ),
        )

        result = extract_json_object(
            response.text or ""
        )

        if not result:
            print(
                "Gemini analysis returned invalid JSON."
            )
            return None

        return {
            "macro_bias": str(
                result.get(
                    "macro_bias",
                    "Unknown",
                )
            ),

            "alignment": str(
                result.get(
                    "alignment",
                    "Unknown",
                )
            ),

            "risk": str(
                result.get(
                    "risk",
                    "Unknown",
                )
            ),

            "summary": str(
                result.get(
                    "summary",
                    "",
                )
            ),

            "technical_summary": str(
                result.get(
                    "technical_summary",
                    "",
                )
            ),
        }

    except Exception as exc:
        print(
            f"Gemini market analysis error: {exc}"
        )
        return None


# ============================================================
# TELEGRAM MESSAGE FORMAT
# ============================================================

def build_telegram_message(
    event_data: Dict[str, Any],
    technical: Dict[str, Any],
    analysis: Dict[str, str],
) -> str:

    event = event_data["event"]

    name = event.get("name", "")
    currency = event_data["currency"]

    actual = event_data["actual"]

    consensus = event.get("consensus")
    prior = event.get("prior")

    actual_source = event_data["actual_source"]

    actual_metadata = event_data.get(
        "actual_metadata"
    )

    source_url = ""

    if actual_metadata:
        source_url = actual_metadata.get(
            "source_url",
            "",
        )

    trend = technical["trend"]

    if trend == "Bullish":
        trend_icon = "🟢"
    elif trend == "Bearish":
        trend_icon = "🔴"
    else:
        trend_icon = "🟡"

    risk = analysis["risk"]

    if risk.lower() == "high":
        risk_icon = "🔴"
    elif risk.lower() == "moderate":
        risk_icon = "🟡"
    else:
        risk_icon = "🟢"

    message = f"""
🚨 {name} | {currency}

Actual: {actual}
Consensus: {consensus if consensus else "—"}
Prior: {prior if prior else "—"}
Source: {actual_source}

━━━━━━━━━━━━━━

📈 {technical["ticker"]} | 15m

Price: {technical["price"]:.5f}
EMA50: {technical["ema50"]:.5f}
EMA200: {technical["ema200"]:.5f}
Trend: {trend_icon} {trend}

━━━━━━━━━━━━━━

🧠 Macro: {analysis["macro_bias"]}
📊 Alignment: {analysis["alignment"]}
⚠️ Risk: {risk_icon} {risk}

{analysis["summary"]}

{analysis["technical_summary"]}
""".strip()

    if source_url:
        message += f"\n\n🔗 Source: {source_url}"

    return message
    

# ============================================================
# PROCESS EVENT
# ============================================================

def process_event(
    event_data: Dict[str, Any],
):

    event = event_data["event"]
    currency = event_data["currency"]
    actual = event_data["actual"]

    ticker = CURRENCY_TO_PAIR.get(
        currency
    )

    if not ticker:
        print(
            f"No ticker mapping for {currency}"
        )
        return

    print(
        f"\nProcessing {event.get('name')} "
        f"-> {ticker}"
    )

    # --------------------------------------------------------
    # Technical data
    # --------------------------------------------------------

    technical = get_technical_context(
        ticker
    )

    if not technical:
        print(
            "Could not obtain technical context."
        )
        return

    # --------------------------------------------------------
    # Gemini market analysis
    # --------------------------------------------------------

    analysis = analyze_with_gemini(
        event=event,
        currency=currency,
        actual=actual,
        actual_source=event_data["actual_source"],
        actual_metadata=event_data.get(
        "actual_metadata"
        ),
        technical=technical,
    )

    if not analysis:
        print(
            "Gemini analysis failed."
        )
        return

    # --------------------------------------------------------
    # Telegram
    # --------------------------------------------------------

    message = build_telegram_message(
        event_data=event_data,
        technical=technical,
        analysis=analysis,
    )

    telegram_success = send_telegram(
        message
    )

    if not telegram_success:
        print(
            "Telegram failed. "
            "Event will NOT be marked processed."
        )
        return

    # --------------------------------------------------------
    # Mark processed only after Telegram succeeds
    # --------------------------------------------------------

    mark_event_processed(
        event_hash=event_data["event_hash"],
        event_name=event.get("name", ""),
        event_date=event.get("date", ""),
    )

    print(
        "Event successfully processed."
    )


# ============================================================
# AGENT CYCLE
# ============================================================

def run_agent_cycle():

    print(
        "\n"
        "==================================================\n"
        "Starting macro monitoring cycle\n"
        f"{datetime.now(timezone.utc).isoformat()}\n"
        "=================================================="
    )

    try:

        events = get_fresh_macro_events()

        if not events:
            print(
                "No new events to process."
            )
            return

        for event_data in events:

            try:
                process_event(
                    event_data
                )

            except Exception as exc:
                print(
                    f"Error processing event: {exc}"
                )

            # Small delay between events
            time.sleep(2)

    except Exception as exc:
        print(
            f"Agent cycle error: {exc}"
        )

    print(
        "\nCycle complete."
    )


# ============================================================
# SHUTDOWN
# ============================================================

def shutdown_handler(
    signum=None,
    frame=None,
):
    global scheduler

    print(
        "\nShutdown signal received."
    )

    if scheduler:
        try:
            scheduler.shutdown(
                wait=False
            )
        except Exception:
            pass

    raise KeyboardInterrupt


# ============================================================
# MAIN
# ============================================================

def main():

    global scheduler

    init_db()

    print(
        "\n"
        "=================================================="
    )

    print(
        "MULTICURRENCY MACRO MONITOR"
    )

    print(
        "=================================================="
    )

    print(
        f"Gemini model: {GEMINI_MODEL}"
    )

    print(
        f"Calendar: {FINANCE_CALENDAR_BASE_URL}"
    )

    print(
        f"Interval: {CHECK_INTERVAL_MINUTES} minutes"
    )

    print(
        "Grounded actual verification: ENABLED"
    )

    print(
        "==================================================\n"
    )

    # --------------------------------------------------------
    # Signal handlers
    # --------------------------------------------------------

    signal.signal(
        signal.SIGINT,
        shutdown_handler,
    )

    if hasattr(signal, "SIGBREAK"):
        signal.signal(
            signal.SIGBREAK,
            shutdown_handler,
        )

    # --------------------------------------------------------
    # Run immediately
    # --------------------------------------------------------

    run_agent_cycle()

    # --------------------------------------------------------
    # Scheduler
    # --------------------------------------------------------

    scheduler = BackgroundScheduler()

    scheduler.add_job(
        run_agent_cycle,
        "interval",
        minutes=CHECK_INTERVAL_MINUTES,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=300,
    )

    scheduler.start()

    print(
        f"\nAgent running."
    )

    print(
        f"Next cycles every "
        f"{CHECK_INTERVAL_MINUTES} minutes."
    )

    print(
        "Press Ctrl+C to stop.\n"
    )

    try:

        while True:
            time.sleep(1)

    except KeyboardInterrupt:

        print(
            "\nStopping agent..."
        )

        if scheduler:
            scheduler.shutdown(
                wait=False
            )

        print(
            "Agent stopped cleanly."
        )


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    main()