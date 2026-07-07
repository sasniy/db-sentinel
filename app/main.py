"""DB Sentinel — веб-приложение и REST API."""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import notifiers, scheduler, storage
from .config import DB_TYPES, RULE_TYPES, STATIC_DIR
from .connectors import get_connector
from .i18n import TRANSLATIONS, t

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s: %(message)s")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    storage.init_db()
    scheduler.start()
    yield
    scheduler.shutdown()


app = FastAPI(title="DB Sentinel", lifespan=lifespan)


# ------------------------------------------------------------------ models

class ConnectionIn(BaseModel):
    name: str
    db_type: str
    params: dict


class RuleIn(BaseModel):
    name: str
    connection_id: int
    rule_type: str
    params: dict
    interval_minutes: int = 60
    cooldown_minutes: int = 60
    enabled: bool = True


class SettingsIn(BaseModel):
    language: str | None = None
    notify_recovery: bool | None = None
    telegram: dict | None = None
    email: dict | None = None
    mattermost: dict | None = None


# -------------------------------------------------------------------- meta

@app.get("/api/meta")
def get_meta():
    return {
        "db_types": DB_TYPES,
        "rule_types": RULE_TYPES,
        "language": storage.get_language(),
    }


@app.get("/api/i18n/{lang}")
def get_i18n(lang: str):
    if lang not in TRANSLATIONS:
        raise HTTPException(404, "Unknown language")
    return TRANSLATIONS[lang]


# ---------------------------------------------------------------- settings

@app.get("/api/settings")
def get_settings():
    def masked(channel):
        return storage.get_setting(channel) or {}
    return {
        "language": storage.get_language(),
        "notify_recovery": storage.get_setting("notify_recovery", True),
        "telegram": masked("telegram"),
        "email": masked("email"),
        "mattermost": masked("mattermost"),
    }


@app.post("/api/settings")
def save_settings(body: SettingsIn):
    if body.language is not None:
        if body.language not in TRANSLATIONS:
            raise HTTPException(400, "Unknown language")
        storage.set_setting("language", body.language)
    if body.notify_recovery is not None:
        storage.set_setting("notify_recovery", body.notify_recovery)
    for channel in ("telegram", "email", "mattermost"):
        value = getattr(body, channel)
        if value is not None:
            storage.set_setting(channel, value)
    return {"ok": True}


@app.post("/api/notify/test/{channel}")
def test_notification(channel: str):
    cfg = storage.get_setting(channel) or {}
    lang = storage.get_language()
    try:
        notifiers.send_to_channel(channel, cfg, t("notify.test_message", lang), "DB Sentinel: test")
    except Exception as e:
        raise HTTPException(400, str(e))
    return {"ok": True}


# ------------------------------------------------------------- connections

@app.get("/api/connections")
def connections_list():
    return storage.list_connections()


@app.post("/api/connections")
def connections_create(body: ConnectionIn):
    _validate_connection(body)
    conn_id = storage.create_connection(body.name, body.db_type, body.params)
    return {"id": conn_id}


@app.put("/api/connections/{conn_id}")
def connections_update(conn_id: int, body: ConnectionIn):
    if storage.get_connection(conn_id) is None:
        raise HTTPException(404, "Connection not found")
    _validate_connection(body)
    storage.update_connection(conn_id, body.name, body.db_type, body.params)
    return {"ok": True}


@app.delete("/api/connections/{conn_id}")
def connections_delete(conn_id: int):
    storage.delete_connection(conn_id)
    scheduler.reload_jobs()
    return {"ok": True}


@app.post("/api/connections/test")
def connections_test(body: ConnectionIn):
    _validate_connection(body)
    try:
        with get_connector(body.db_type, body.params) as db:
            db.test()
    except Exception as e:
        raise HTTPException(400, f"{type(e).__name__}: {e}")
    return {"ok": True}


def _validate_connection(body: ConnectionIn):
    if body.db_type not in DB_TYPES:
        raise HTTPException(400, f"Unknown db_type: {body.db_type}")
    if not body.name.strip():
        raise HTTPException(400, "Name is required")


# ------------------------------------------------------------------ rules

@app.get("/api/rules")
def rules_list():
    return storage.list_rules()


@app.post("/api/rules")
def rules_create(body: RuleIn):
    _validate_rule(body)
    rule_id = storage.create_rule(
        body.name, body.connection_id, body.rule_type, body.params,
        body.interval_minutes, body.cooldown_minutes, body.enabled)
    scheduler.reload_jobs()
    return {"id": rule_id}


@app.put("/api/rules/{rule_id}")
def rules_update(rule_id: int, body: RuleIn):
    if storage.get_rule(rule_id) is None:
        raise HTTPException(404, "Rule not found")
    _validate_rule(body)
    storage.update_rule(
        rule_id, body.name, body.connection_id, body.rule_type, body.params,
        body.interval_minutes, body.cooldown_minutes, body.enabled)
    scheduler.reload_jobs()
    return {"ok": True}


@app.delete("/api/rules/{rule_id}")
def rules_delete(rule_id: int):
    storage.delete_rule(rule_id)
    scheduler.reload_jobs()
    return {"ok": True}


@app.post("/api/rules/{rule_id}/run")
def rules_run(rule_id: int):
    result = scheduler.execute_rule(rule_id)
    if result is None:
        raise HTTPException(404, "Rule or its connection not found")
    return result


def _validate_rule(body: RuleIn):
    if body.rule_type not in RULE_TYPES:
        raise HTTPException(400, f"Unknown rule_type: {body.rule_type}")
    if storage.get_connection(body.connection_id) is None:
        raise HTTPException(400, "Connection not found")
    if not body.name.strip():
        raise HTTPException(400, "Name is required")


# -------------------------------------------------------------- monitoring

@app.get("/api/dashboard")
def dashboard():
    connections = {c["id"]: c for c in storage.list_connections()}
    items = []
    for rule in storage.list_rules():
        last = storage.last_result(rule["id"])
        conn = connections.get(rule["connection_id"])
        items.append({
            "rule_id": rule["id"],
            "rule_name": rule["name"],
            "rule_type": rule["rule_type"],
            "connection_name": conn["name"] if conn else "?",
            "db_type": conn["db_type"] if conn else "?",
            "enabled": bool(rule["enabled"]),
            "interval_minutes": rule["interval_minutes"],
            "status": last["status"] if last else None,
            "value": last["value"] if last else None,
            "message": last["message"] if last else None,
            "checked_at": last["checked_at"] if last else None,
        })
    return items


@app.get("/api/results")
def results(rule_id: int | None = None, limit: int = 200):
    return storage.list_results(rule_id=rule_id, limit=min(limit, 1000))


# ------------------------------------------------------------------ static

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")
