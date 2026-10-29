from datetime import datetime, timedelta, timezone

import requests

from config import (
    FINANCE_CALENDAR_BASE_URL,
    CALENDAR_LIMIT,
)

from database import (
    event_hash,
    is_event_processed,
)


def fetch_calendar_events():

    now = datetime.now(timezone.utc)

    start = (
        now - timedelta(days=1)
    ).date().isoformat()

    end = now.date().isoformat()

    url = (
        f"{FINANCE_CALENDAR_BASE_URL}"
        f"/calendar"
    )

    params = {
        "from": start,
        "to": end,
        "impact": "high,medium",
        "limit": CALENDAR_LIMIT,
        "format": "json",
    }

    try:

        response = requests.get(
            url,
            params=params,
            timeout=20,
        )

        print(
            f"Calendar: {response.status_code}"
        )

        response.raise_for_status()

        data = response.json()

    except Exception as exc:

        print(
            f"Calendar error: {exc}"
        )

        return []

    if isinstance(data, dict):

        events = (
            data.get("events")
            or data.get("data")
            or []
        )

    else:

        events = data

    if not isinstance(events, list):
        return []

    return events


def event_release_has_occurred(
    event: dict,
) -> bool:

    raw = event.get(
        "time_utc"
    )

    if not raw:
        return False

    try:

        release = datetime.fromisoformat(
            raw.replace(
                "Z",
                "+00:00",
            )
        )

        if release.tzinfo is None:

            release = release.replace(
                tzinfo=timezone.utc
            )

        return (
            release
            <= datetime.now(timezone.utc)
        )

    except ValueError:

        return False


def infer_currency(
    event: dict,
) -> str:

    text = " ".join(
        str(event.get(k, ""))
        for k in (
            "currency",
            "name",
            "title",
            "category",
        )
    ).upper()

    if (
        "EUROZONE" in text
        or "ECB" in text
        or "EUR" in text
    ):
        return "EUR"

    if (
        "UNITED KINGDOM" in text
        or "BOE" in text
        or "GBP" in text
    ):
        return "GBP"

    if (
        "JAPAN" in text
        or "BOJ" in text
        or "JPY" in text
    ):
        return "JPY"

    if (
        "AUSTRALIA" in text
        or "RBA" in text
        or "AUD" in text
    ):
        return "AUD"

    if (
        "CANADA" in text
        or "BOC" in text
        or "CAD" in text
    ):
        return "CAD"

    if (
        "SWITZERLAND" in text
        or "SNB" in text
        or "CHF" in text
    ):
        return "CHF"

    if (
        "NEW ZEALAND" in text
        or "RBNZ" in text
        or "NZD" in text
    ):
        return "NZD"

    if (
        "UNITED STATES" in text
        or "U.S." in text
        or "FED" in text
        or "USD" in text
    ):
        return "USD"

    return ""


def get_new_calendar_events():

    events = fetch_calendar_events()

    fresh = []

    for event in events:

        impact = str(
            event.get(
                "impact",
                "",
            )
        ).upper()

        if impact not in {
            "HIGH",
            "MEDIUM",
        }:
            continue

        currency = infer_currency(
            event
        )

        if not currency:
            continue

        if not event_release_has_occurred(
            event
        ):
            continue

        h = event_hash(
            event,
            currency,
        )

        if is_event_processed(h):
            continue

        event["_currency"] = currency
        event["_event_hash"] = h

        fresh.append(event)

    return fresh