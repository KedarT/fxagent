import requests

from config import (
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_ID,
)


def send_telegram(
    message: str,
) -> bool:

    url = (
        "https://api.telegram.org/"
        f"bot{TELEGRAM_BOT_TOKEN}/"
        "sendMessage"
    )

    payload = {
        "chat_id":
            TELEGRAM_CHAT_ID,

        "text":
            message,

        "disable_web_page_preview":
            True,
    }

    try:

        response = requests.post(
            url,
            json=payload,
            timeout=20,
        )

        print(
            f"Telegram: "
            f"{response.status_code}"
        )

        if not response.ok:

            print(
                "Telegram error: "
                f"{response.text[:300]}"
            )

        return response.ok

    except Exception as exc:

        print(
            f"Telegram error: {exc}"
        )

        return False