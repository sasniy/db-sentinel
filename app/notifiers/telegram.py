import requests


def send(cfg: dict, text: str) -> None:
    """Отправка сообщения через Telegram Bot API. Бросает исключение при ошибке."""
    token = (cfg.get("bot_token") or "").strip()
    chat_id = str(cfg.get("chat_id") or "").strip()
    if not token or not chat_id:
        raise ValueError("Telegram: bot_token / chat_id not configured")
    resp = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": chat_id, "text": text},
        timeout=15,
    )
    data = resp.json()
    if not data.get("ok"):
        raise RuntimeError(f"Telegram API error: {data.get('description', resp.text)}")
