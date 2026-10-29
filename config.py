import os

from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

MODEL_NAME = "gemini-2.5-flash"

FINANCE_CALENDAR_BASE_URL = (
    "https://www.financecalendar.com/wp-json/fc/v1"
)

DB_FILE = os.getenv(
    "DB_FILE",
    "data/multicurrency_agent.db",
)

CHECK_INTERVAL_MINUTES = int(
    os.getenv("CHECK_INTERVAL_MINUTES", "35")
)

NEWS_LOOKBACK_HOURS = int(
    os.getenv("NEWS_LOOKBACK_HOURS", "3")
)

NEWS_MAX_CANDIDATES = int(
    os.getenv("NEWS_MAX_CANDIDATES", "8")
)

ALERT_COOLDOWN_MINUTES = int(
    os.getenv("ALERT_COOLDOWN_MINUTES", "120")
)

CALENDAR_LIMIT = 500


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


# Yahoo Finance symbols.
#
# Gold / silver / crude are futures proxies rather than literal
# spot symbols:
#
# XAUUSD -> GC=F
# XAGUSD -> SI=F
# WTI    -> CL=F

MARKETS = {
    "EURUSD": {
        "symbol": "EURUSD=X",
        "type": "fx",
    },

    "GBPUSD": {
        "symbol": "GBPUSD=X",
        "type": "fx",
    },

    "USDJPY": {
        "symbol": "USDJPY=X",
        "type": "fx",
    },

    "AUDUSD": {
        "symbol": "AUDUSD=X",
        "type": "fx",
    },

    "USDCAD": {
        "symbol": "USDCAD=X",
        "type": "fx",
    },

    "USDCHF": {
        "symbol": "USDCHF=X",
        "type": "fx",
    },

    "NZDUSD": {
        "symbol": "NZDUSD=X",
        "type": "fx",
    },

    "XAUUSD": {
        "symbol": "GC=F",
        "type": "commodity",
    },

    "XAGUSD": {
        "symbol": "SI=F",
        "type": "commodity",
    },

    "WTI": {
        "symbol": "CL=F",
        "type": "commodity",
    },
}


CURRENCY_TO_MARKETS = {
    "USD": [
        "EURUSD",
        "GBPUSD",
        "XAUUSD",
        "XAGUSD",
        "WTI",
        "USDCAD",
        "USDJPY",
        "AUDUSD",
        "USDCHF",
        "NZDUSD",
    ],

    "EUR": ["EURUSD"],

    "GBP": ["GBPUSD"],

    "JPY": ["USDJPY"],

    "AUD": ["AUDUSD"],

    "CAD": [
        "USDCAD",
        "WTI",
    ],

    "CHF": ["USDCHF"],

    "NZD": ["NZDUSD"],
}


if not TELEGRAM_BOT_TOKEN:
    raise RuntimeError(
        "Missing TELEGRAM_BOT_TOKEN in .env"
    )

if not TELEGRAM_CHAT_ID:
    raise RuntimeError(
        "Missing TELEGRAM_CHAT_ID in .env"
    )

if not GEMINI_API_KEY:
    raise RuntimeError(
        "Missing GEMINI_API_KEY in .env"
    )