"""Базовый интерфейс коннектора к базе данных."""
from abc import ABC, abstractmethod


class BaseConnector(ABC):
    def __init__(self, params: dict):
        self.params = params

    @abstractmethod
    def fetch_one(self, sql: str) -> tuple | None:
        """Выполнить запрос и вернуть первую строку результата (или None)."""

    @abstractmethod
    def fetch_all(self, sql: str) -> list[tuple]:
        """Выполнить запрос и вернуть все строки результата."""

    def fetch_value(self, sql: str):
        """Первое значение первой строки результата."""
        row = self.fetch_one(sql)
        return row[0] if row else None

    def test(self) -> None:
        """Проверка подключения: бросает исключение, если база недоступна."""
        self.fetch_one("SELECT 1")

    def close(self) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
