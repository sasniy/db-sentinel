from pathlib import Path

from .base import BaseConnector


class ClickHouseConnector(BaseConnector):
    def __init__(self, params: dict):
        super().__init__(params)
        try:
            import clickhouse_connect
        except ImportError as e:
            raise RuntimeError(
                "clickhouse-connect is not installed: pip install clickhouse-connect") from e
        kwargs = dict(
            host=params.get("host", "localhost"),
            port=int(params.get("port") or 8123),
            username=params.get("user", "default"),
            password=params.get("password", ""),
            database=params.get("database", "default"),
            secure=bool(params.get("secure")),
            connect_timeout=10,
        )
        # 8443 — стандартный HTTPS-порт ClickHouse: драйвер всё равно пойдёт по
        # TLS, поэтому включаем secure явно, даже если галочку забыли
        if kwargs["port"] == 8443:
            kwargs["secure"] = True
        if kwargs["secure"]:
            # Корпоративный CA (перехват TLS на VPN/прокси) или self-signed сервер
            kwargs["verify"] = params.get("verify", True) is not False
            # Проводник Windows копирует пути в кавычках — убираем их
            ca_cert = (params.get("ca_cert") or "").strip().strip('"').strip("'")
            if ca_cert:
                if not Path(ca_cert).is_file():
                    raise FileNotFoundError(f"CA certificate file not found: {ca_cert}")
                kwargs["ca_cert"] = ca_cert
        self._client = clickhouse_connect.get_client(**kwargs)

    def fetch_one(self, sql: str):
        rows = self._client.query(sql).result_rows
        return rows[0] if rows else None

    def fetch_all(self, sql: str):
        return self._client.query(sql).result_rows

    def get_schema(self):
        rows = self.fetch_all(
            "SELECT table, name FROM system.columns "
            "WHERE database = currentDatabase() ORDER BY table, position")
        schema: dict[str, list[str]] = {}
        for tbl, col in rows:
            schema.setdefault(tbl, []).append(col)
        return schema

    def close(self):
        self._client.close()
