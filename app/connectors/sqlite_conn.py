import sqlite3
from pathlib import Path

from .base import BaseConnector


class SQLiteConnector(BaseConnector):
    def __init__(self, params: dict):
        super().__init__(params)
        path = params.get("path", "")
        if not path or not Path(path).exists():
            raise FileNotFoundError(f"SQLite file not found: {path}")
        self._conn = sqlite3.connect(path, timeout=15)

    def fetch_one(self, sql: str):
        cur = self._conn.execute(sql)
        return cur.fetchone()

    def fetch_all(self, sql: str):
        cur = self._conn.execute(sql)
        return cur.fetchall()

    def get_schema(self):
        tables = [r[0] for r in self.fetch_all(
            "SELECT name FROM sqlite_master WHERE type = 'table' "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        return {t: [c[1] for c in self.fetch_all(f'PRAGMA table_info("{t}")')]
                for t in tables}

    def close(self):
        self._conn.close()
