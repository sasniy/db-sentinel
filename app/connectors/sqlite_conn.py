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

    def close(self):
        self._conn.close()
