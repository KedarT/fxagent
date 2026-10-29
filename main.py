import signal
import time

from datetime import (
    datetime,
    timezone,
)

from apscheduler.schedulers.background import (
    BackgroundScheduler,
)

from alerts import (
    build_telegram_message,
    record_alert,
    should_send_alert,
)

from analyzer import (
    analyze_news_candidate,
)

from calendar_feed import (
    get_new_calendar_events,
)

from config import (
    CHECK_INTERVAL_MINUTES,
)

from database import (
    init_db,
    mark_event_processed,
)

from gemini_agent import (
    get_actual_with_gemini,
)

from news_feed import (
    get_new_news_candidates,
    mark_candidate_processed,
)

from telegram_client import (
    send_telegram,
)


running = True


def shutdown(
    signum=None,
    frame=None,
):

    global running

    running = False

    print(
        "\nStopping agent..."
    )


def process_calendar_event(
    event: dict,
):

    currency = event[
        "_currency"
    ]

    actual = event.get(
        "actual"
    )

    if actual in (
        None,
        "",
        "Pending",
        "pending",
    ):

        release_info = (
            get_actual_with_gemini(
                event
            )
        )

        if not release_info:

            print(
                "Calendar release found "
                "but actual could not be "
                f"verified: "
                f"{event.get('name')}"
            )

            return

        event["actual"] = (
            release_info.get(
                "actual"
            )
        )

        event["_source_name"] = (
            release_info.get(
                "source_name",
                "",
            )
        )

        event["_source_url"] = (
            release_info.get(
                "source_url",
                "",
            )
        )

    candidate = {

        "title":
            event.get(
                "title"
            )
            or event.get(
                "name"
            )
            or "Economic release",

        "summary":
            (
                f"Actual: "
                f"{event.get('actual')}; "
                f"Consensus: "
                f"{event.get('consensus') or '—'}; "
                f"Prior: "
                f"{event.get('prior') or '—'}"
            ),

        "url":
            event.get(
                "_source_url"
            )
            or event.get(
                "url"
            )
            or "",

        "source":
            event.get(
                "_source_name"
            )
            or "FinanceCalendar",

        "published_at":
            event.get(
                "time_utc",
                "",
            ),

        "currency":
            currency,

        "impact":
            str(
                event.get(
                    "impact",
                    "MEDIUM",
                )
            ).upper(),

        "direction":
            "MIXED",

        "assets":
            [],
    }

    analysis, contexts = (
        analyze_news_candidate(
            candidate
        )
    )

    analysis.source_name = (
        candidate["source"]
    )

    if candidate["url"]:

        analysis.source_url = (
            candidate["url"]
        )

    assets = (
        analysis.affected_assets
        or [
            m.asset
            for m in contexts
        ]
    )

    asset = (
        assets[0]
        if assets
        else currency
    )

    allowed, topic = (
        should_send_alert(
            candidate,
            analysis,
            asset,
        )
    )

    if allowed:

        message = (
            build_telegram_message(
                candidate,
                analysis,
                contexts,
            )
        )

        if send_telegram(
            message
        ):

            record_alert(
                candidate,
                analysis,
                asset,
                topic,
            )

            print(
                "Alert sent: "
                f"{candidate['title']}"
            )

    else:

        print(
            "Calendar ignored: "
            f"{candidate['title']}"
        )

    # The event has now been evaluated.
    mark_event_processed(
        event["_event_hash"],
        event.get(
            "name",
            "",
        ),
        event.get(
            "date",
            "",
        ),
    )


def process_news_candidate(
    candidate: dict,
):

    analysis, contexts = (
        analyze_news_candidate(
            candidate
        )
    )

    assets = (
        analysis.affected_assets
        or [
            m.asset
            for m in contexts
        ]
    )

    if not assets:

        mark_candidate_processed(
            candidate
        )

        return

    sent = False

    for asset in assets[:3]:

        allowed, topic = (
            should_send_alert(
                candidate,
                analysis,
                asset,
            )
        )

        if not allowed:
            continue

        message = (
            build_telegram_message(
                candidate,
                analysis,
                contexts,
            )
        )

        if send_telegram(
            message
        ):

            record_alert(
                candidate,
                analysis,
                asset,
                topic,
            )

            sent = True

            print(
                "News alert sent: "
                f"{candidate.get('title')}"
            )

            break

    mark_candidate_processed(
        candidate
    )

    if not sent:

        print(
            "News ignored: "
            f"{candidate.get('title')}"
        )


def run_cycle():

    print(
        "\n"
        f"[{datetime.now(timezone.utc).isoformat()}]"
        " Scan"
    )

    # --------------------------------
    # 1. Economic releases
    # --------------------------------

    try:

        events = (
            get_new_calendar_events()
        )

        print(
            "New released calendar "
            f"events: {len(events)}"
        )

        for event in events:

            process_calendar_event(
                event
            )

    except Exception as exc:

        print(
            f"Calendar cycle error: "
            f"{exc}"
        )

    # --------------------------------
    # 2. Unscheduled news
    # --------------------------------

    try:

        news = (
            get_new_news_candidates()
        )

        print(
            "New news candidates: "
            f"{len(news)}"
        )

        for candidate in news:

            process_news_candidate(
                candidate
            )

    except Exception as exc:

        print(
            f"News cycle error: "
            f"{exc}"
        )

    print(
        "Cycle complete."
    )


def main():

    global running

    init_db()

    signal.signal(
        signal.SIGINT,
        shutdown,
    )

    signal.signal(
        signal.SIGTERM,
        shutdown,
    )

    scheduler = (
        BackgroundScheduler()
    )

    scheduler.add_job(
        run_cycle,
        "interval",
        minutes=CHECK_INTERVAL_MINUTES,
        max_instances=1,
        coalesce=True,
    )

    scheduler.start()

    print(
        "FX Macro Intelligence "
        "Agent started."
    )

    print(
        f"Scanning every "
        f"{CHECK_INTERVAL_MINUTES} minutes."
    )

    print(
        "Markets:"
        " EURUSD GBPUSD USDJPY "
        "AUDUSD USDCAD USDCHF NZDUSD "
        "XAUUSD XAGUSD WTI"
    )

    print(
        "Telegram:"
        " significant developments only."
    )

    # Immediate scan
    run_cycle()

    try:

        while running:

            time.sleep(1)

    finally:

        scheduler.shutdown(
            wait=False
        )

        print(
            "Agent stopped."
        )


if __name__ == "__main__":

    main()