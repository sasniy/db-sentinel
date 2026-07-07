"""Рассылка уведомлений по всем включённым каналам."""
import logging

from .. import storage
from ..i18n import t
from . import email_notifier, mattermost, telegram

log = logging.getLogger("db-sentinel.notify")

CHANNELS = ("telegram", "email", "mattermost")


def send_to_channel(channel: str, cfg: dict, text: str, subject: str) -> None:
    if channel == "telegram":
        telegram.send(cfg, text)
    elif channel == "email":
        email_notifier.send(cfg, text, subject=subject)
    elif channel == "mattermost":
        mattermost.send(cfg, text)
    else:
        raise ValueError(f"Unknown channel: {channel}")


def broadcast(text: str, subject: str) -> list[str]:
    """Отправить текст во все включённые каналы. Возвращает список ошибок."""
    errors = []
    for channel in CHANNELS:
        cfg = storage.get_setting(channel) or {}
        if not cfg.get("enabled"):
            continue
        try:
            send_to_channel(channel, cfg, text, subject)
        except Exception as e:
            log.warning("Notification via %s failed: %s", channel, e)
            errors.append(f"{channel}: {e}")
    return errors


def build_message(kind: str, rule: dict, connection: dict, result: dict, lang: str) -> tuple[str, str]:
    """Собрать (заголовок, полный текст) уведомления. kind: alert|error|recovery."""
    title = t(f"notify.{kind}_title", lang)
    body = (
        f"{title}\n\n"
        f"{t('notify.rule', lang)}: {rule['name']}\n"
        f"{t('notify.connection', lang)}: {connection['name']} ({connection['db_type']})\n"
        f"{t('notify.time', lang)}: {storage.now_str()}\n\n"
        f"{result['message']}"
    )
    return title, body
