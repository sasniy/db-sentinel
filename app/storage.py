"""Внутреннее хранилище приложения (SQLite): подключения, правила, история, настройки."""
import json
import sqlite3
from datetime import datetime

from .config import DB_PATH, DEFAULT_LANGUAGE


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(DB_PATH, timeout=15)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    return c


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def init_db() -> None:
    with _conn() as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS settings (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS connections (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                name       TEXT NOT NULL,
                db_type    TEXT NOT NULL,
                params     TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS rules (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                name             TEXT NOT NULL,
                connection_id    INTEGER NOT NULL REFERENCES connections(id),
                rule_type        TEXT NOT NULL,
                params           TEXT NOT NULL,
                interval_minutes INTEGER NOT NULL DEFAULT 60,
                cooldown_minutes INTEGER NOT NULL DEFAULT 60,
                enabled          INTEGER NOT NULL DEFAULT 1,
                last_notified_at TEXT,
                created_at       TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS results (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                rule_id    INTEGER NOT NULL REFERENCES rules(id),
                status     TEXT NOT NULL,
                value      REAL,
                message    TEXT,
                checked_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_results_rule ON results(rule_id, id);
            """
        )
        # Миграция: тип запуска (auto — планировщик, manual — кнопка в UI)
        cols = [r[1] for r in c.execute("PRAGMA table_info(results)").fetchall()]
        if "run_type" not in cols:
            c.execute("ALTER TABLE results ADD COLUMN run_type TEXT NOT NULL DEFAULT 'auto'")
    if get_setting("language") is None:
        set_setting("language", DEFAULT_LANGUAGE)


# ---------------------------------------------------------------- settings

def get_setting(key: str, default=None):
    with _conn() as c:
        row = c.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return json.loads(row["value"]) if row else default


def set_setting(key: str, value) -> None:
    with _conn() as c:
        c.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, json.dumps(value, ensure_ascii=False)),
        )


def get_language() -> str:
    return get_setting("language", DEFAULT_LANGUAGE)


# ------------------------------------------------------------- connections

def _row_to_connection(row) -> dict:
    d = dict(row)
    d["params"] = json.loads(d["params"])
    return d


def list_connections() -> list[dict]:
    with _conn() as c:
        rows = c.execute("SELECT * FROM connections ORDER BY id").fetchall()
    return [_row_to_connection(r) for r in rows]


def get_connection(conn_id: int) -> dict | None:
    with _conn() as c:
        row = c.execute("SELECT * FROM connections WHERE id = ?", (conn_id,)).fetchone()
    return _row_to_connection(row) if row else None


def create_connection(name: str, db_type: str, params: dict) -> int:
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO connections (name, db_type, params, created_at) VALUES (?, ?, ?, ?)",
            (name, db_type, json.dumps(params, ensure_ascii=False), now_str()),
        )
        return cur.lastrowid


def update_connection(conn_id: int, name: str, db_type: str, params: dict) -> None:
    with _conn() as c:
        c.execute(
            "UPDATE connections SET name = ?, db_type = ?, params = ? WHERE id = ?",
            (name, db_type, json.dumps(params, ensure_ascii=False), conn_id),
        )


def delete_connection(conn_id: int) -> None:
    with _conn() as c:
        rule_ids = [r["id"] for r in c.execute(
            "SELECT id FROM rules WHERE connection_id = ?", (conn_id,)).fetchall()]
        if rule_ids:
            qs = ",".join("?" * len(rule_ids))
            c.execute(f"DELETE FROM results WHERE rule_id IN ({qs})", rule_ids)
            c.execute(f"DELETE FROM rules WHERE id IN ({qs})", rule_ids)
        c.execute("DELETE FROM connections WHERE id = ?", (conn_id,))


# ------------------------------------------------------------------ rules

def _row_to_rule(row) -> dict:
    d = dict(row)
    d["params"] = json.loads(d["params"])
    return d


def list_rules() -> list[dict]:
    with _conn() as c:
        rows = c.execute("SELECT * FROM rules ORDER BY id").fetchall()
    return [_row_to_rule(r) for r in rows]


def get_rule(rule_id: int) -> dict | None:
    with _conn() as c:
        row = c.execute("SELECT * FROM rules WHERE id = ?", (rule_id,)).fetchone()
    return _row_to_rule(row) if row else None


def create_rule(name: str, connection_id: int, rule_type: str, params: dict,
                interval_minutes: int, cooldown_minutes: int, enabled: bool) -> int:
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO rules (name, connection_id, rule_type, params, interval_minutes,"
            " cooldown_minutes, enabled, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (name, connection_id, rule_type, json.dumps(params, ensure_ascii=False),
             interval_minutes, cooldown_minutes, int(enabled), now_str()),
        )
        return cur.lastrowid


def update_rule(rule_id: int, name: str, connection_id: int, rule_type: str, params: dict,
                interval_minutes: int, cooldown_minutes: int, enabled: bool) -> None:
    with _conn() as c:
        c.execute(
            "UPDATE rules SET name = ?, connection_id = ?, rule_type = ?, params = ?,"
            " interval_minutes = ?, cooldown_minutes = ?, enabled = ? WHERE id = ?",
            (name, connection_id, rule_type, json.dumps(params, ensure_ascii=False),
             interval_minutes, cooldown_minutes, int(enabled), rule_id),
        )


def delete_rule(rule_id: int) -> None:
    with _conn() as c:
        c.execute("DELETE FROM results WHERE rule_id = ?", (rule_id,))
        c.execute("DELETE FROM rules WHERE id = ?", (rule_id,))


def set_rule_notified(rule_id: int, when: str | None) -> None:
    with _conn() as c:
        c.execute("UPDATE rules SET last_notified_at = ? WHERE id = ?", (when, rule_id))


# ---------------------------------------------------------------- results

def add_result(rule_id: int, status: str, value, message: str, run_type: str = "auto") -> None:
    with _conn() as c:
        c.execute(
            "INSERT INTO results (rule_id, status, value, message, checked_at, run_type)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (rule_id, status, value, message, now_str(), run_type),
        )


def list_results(rule_id: int | None = None, limit: int = 200) -> list[dict]:
    q = "SELECT r.*, ru.name AS rule_name FROM results r JOIN rules ru ON ru.id = r.rule_id"
    args: list = []
    if rule_id is not None:
        q += " WHERE r.rule_id = ?"
        args.append(rule_id)
    q += " ORDER BY r.id DESC LIMIT ?"
    args.append(limit)
    with _conn() as c:
        rows = c.execute(q, args).fetchall()
    return [dict(r) for r in rows]


def last_result(rule_id: int) -> dict | None:
    with _conn() as c:
        row = c.execute(
            "SELECT * FROM results WHERE rule_id = ? ORDER BY id DESC LIMIT 1", (rule_id,)
        ).fetchone()
    return dict(row) if row else None


def last_result_by_type(rule_id: int, run_type: str) -> dict | None:
    with _conn() as c:
        row = c.execute(
            "SELECT * FROM results WHERE rule_id = ? AND run_type = ? ORDER BY id DESC LIMIT 1",
            (rule_id, run_type),
        ).fetchone()
    return dict(row) if row else None


def previous_values(rule_id: int, limit: int = 30, before_id: int | None = None) -> list[float]:
    """Последние значения метрики правила (для поиска аномалий), новые первыми."""
    q = "SELECT value FROM results WHERE rule_id = ? AND value IS NOT NULL AND status != 'error'"
    args: list = [rule_id]
    if before_id is not None:
        q += " AND id < ?"
        args.append(before_id)
    q += " ORDER BY id DESC LIMIT ?"
    args.append(limit)
    with _conn() as c:
        rows = c.execute(q, args).fetchall()
    return [r["value"] for r in rows]
