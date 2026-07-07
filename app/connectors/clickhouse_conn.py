from .base import BaseConnector


class ClickHouseConnector(BaseConnector):
    def __init__(self, params: dict):
        super().__init__(params)
        try:
            import clickhouse_connect
        except ImportError as e:
            raise RuntimeError(
                "clickhouse-connect is not installed: pip install clickhouse-connect") from e
        self._client = clickhouse_connect.get_client(
            host=params.get("host", "localhost"),
            port=int(params.get("port") or 8123),
            username=params.get("user", "default"),
            password=params.get("password", ""),
            database=params.get("database", "default"),
            secure=bool(params.get("secure")),
            connect_timeout=10,
        )

    def fetch_one(self, sql: str):
        rows = self._client.query(sql).result_rows
        return rows[0] if rows else None

    def fetch_all(self, sql: str):
        return self._client.query(sql).result_rows

    def close(self):
        self._client.close()
