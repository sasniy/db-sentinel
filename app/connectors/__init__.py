"""Фабрика коннекторов: get_connector('postgresql', {...})."""
from .base import BaseConnector


def get_connector(db_type: str, params: dict) -> BaseConnector:
    if db_type == "sqlite":
        from .sqlite_conn import SQLiteConnector
        return SQLiteConnector(params)
    if db_type == "postgresql":
        from .postgres_conn import PostgresConnector
        return PostgresConnector(params)
    if db_type == "clickhouse":
        from .clickhouse_conn import ClickHouseConnector
        return ClickHouseConnector(params)
    raise ValueError(f"Unknown db_type: {db_type}")
