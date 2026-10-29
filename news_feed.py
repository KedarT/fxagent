from database import (
    is_news_processed,
    mark_news_processed,
    news_hash,
)

from gemini_agent import (
    discover_recent_news,
)


def get_new_news_candidates():

    raw_items = (
        discover_recent_news()
    )

    candidates = []

    for item in raw_items:

        title = str(
            item.get(
                "title",
                "",
            )
        ).strip()

        url = str(
            item.get(
                "url",
                "",
            )
        ).strip()

        if not title:
            continue

        h = news_hash(
            title,
            url,
        )

        if is_news_processed(h):
            continue

        item["_news_hash"] = h

        candidates.append(item)

    return candidates


def mark_candidate_processed(
    item: dict,
):

    mark_news_processed(
        item["_news_hash"],
        item.get(
            "title",
            "",
        ),
        item.get(
            "url",
            "",
        ),
        item.get(
            "published_at",
            "",
        ),
        item.get(
            "currency",
            "",
        ),
    )