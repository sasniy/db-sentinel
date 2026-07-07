"""Планировщик: выполняет правила по их интервалам и рассылает уведомления."""
import logging
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler

from . import notifiers, storage
from .rules.engine import run_rule

log = logging.getLogger("db-sentinel.scheduler")

scheduler = BackgroundScheduler(job_defaults={"coalesce": True, "max_instances": 1})


def execute_rule(rule_id: int) -> dict | None:
    """Выполнить правило, сохранить результат, при необходимости отправить уведомление."""
    rule = storage.get_rule(rule_id)
    if rule is None:
        return None
    connection = storage.get_connection(rule["connection_id"])
    if connection is None:
        return None

    previous = storage.last_result(rule_id)
    result = run_rule(rule, connection)
    storage.add_result(rule_id, result["status"], result["value"], result["message"])
    log.info("Rule %s [%s]: %s — %s", rule_id, rule["name"], result["status"], result["message"])

    _handle_notifications(rule, connection, result, previous)
    return result


def _handle_notifications(rule: dict, connection: dict, result: dict, previous: dict | None) -> None:
    lang = storage.get_language()
    status = result["status"]

    if status in ("alert", "error"):
        if _cooldown_passed(rule):
            _, body = notifiers.build_message(status, rule, connection, result, lang)
            title = body.splitlines()[0]
            notifiers.broadcast(body, subject=title)
            storage.set_rule_notified(rule["id"], storage.now_str())
    elif status == "ok" and previous and previous["status"] in ("alert", "error"):
        # Восстановление после тревоги
        storage.set_rule_notified(rule["id"], None)
        if storage.get_setting("notify_recovery", True):
            _, body = notifiers.build_message("recovery", rule, connection, result, lang)
            notifiers.broadcast(body, subject=body.splitlines()[0])


def _cooldown_passed(rule: dict) -> bool:
    last = rule.get("last_notified_at")
    if not last:
        return True
    try:
        last_dt = datetime.strptime(last, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return True
    elapsed_min = (datetime.now() - last_dt).total_seconds() / 60
    return elapsed_min >= (rule.get("cooldown_minutes") or 0)


def reload_jobs() -> None:
    """Пересоздать задания планировщика по текущему списку правил."""
    for job in scheduler.get_jobs():
        job.remove()
    for rule in storage.list_rules():
        if not rule["enabled"]:
            continue
        scheduler.add_job(
            execute_rule,
            trigger="interval",
            minutes=max(1, int(rule["interval_minutes"])),
            args=[rule["id"]],
            id=f"rule-{rule['id']}",
            replace_existing=True,
        )
    log.info("Scheduler reloaded: %d job(s)", len(scheduler.get_jobs()))


def start() -> None:
    reload_jobs()
    if not scheduler.running:
        scheduler.start()


def shutdown() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
