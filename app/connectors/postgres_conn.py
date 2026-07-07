from .base import BaseConnector


class PostgresConnector(BaseConnector):
    def __init__(self, params: dict):
        super().__init__(params)
        try:
            import psycopg2
        except ImportError as e:
            raise RuntimeError("psycopg2 is not installed: pip install psycopg2-binary") from e
        self._conn = psycopg2.connect(
            host=params.get("host", "localhost"),
            port=int(params.get("port") or 5432),
            dbname=params.get("database", "postgres"),
            user=params.get("user", "postgres"),
            password=params.get("password", ""),
            connect_timeout=10,
        )
        self._conn.autocommit = True

    def fetch_one(self, sql: str):
        with self._conn.cursor() as cur:
            cur.execute(sql)
            return cur.fetchone()

    def fetch_all(self, sql: str):
        with self._conn.cursor() as cur:
            cur.execute(sql)
            return cur.fetchall()

    def close(self):
        self._conn.close()
