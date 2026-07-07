"""Пути и базовые константы приложения."""
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

# Внутренняя база приложения (подключения, правила, история проверок, настройки)
DB_PATH = DATA_DIR / "sentinel.db"

STATIC_DIR = Path(__file__).resolve().parent / "static"

DEFAULT_LANGUAGE = "ru"

DB_TYPES = ["sqlite", "postgresql", "clickhouse"]

RULE_TYPES = [
    "freshness",     # свежесть данных: MAX(time_column) не старше N минут
    "row_count",     # объём: минимум строк за окно времени
    "null_check",    # доля NULL в колонке не выше порога
    "duplicates",    # дубликаты по ключевым колонкам
    "anomaly",           # аномалия метрики (z-score по истории запусков)
    "anomaly_history",   # аномалия по историческим данным самой таблицы
    "custom_sql",    # свой SQL: значение сравнивается с порогом
]
