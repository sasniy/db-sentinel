"""Создаёт демо-базу demo/demo.sqlite с таблицей продаж и регистрирует
демо-подключение + набор правил в DB Sentinel.

Данные специально «испорчены», чтобы показать все типы проверок:
  - свежие данные обрываются 6 часов назад  -> сработает freshness
  - ~8% NULL в колонке amount              -> сработает null_check (порог 5%)
  - несколько дубликатов order_id          -> сработает duplicates
Запуск: python demo/make_demo.py  (из корня проекта)
"""
import random
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import storage  # noqa: E402

DEMO_DB = Path(__file__).resolve().parent / "demo.sqlite"


def make_demo_database() -> None:
    DEMO_DB.unlink(missing_ok=True)
    conn = sqlite3.connect(DEMO_DB)
    conn.execute(
        """CREATE TABLE sales (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               order_id TEXT NOT NULL,
               user_id INTEGER NOT NULL,
               amount REAL,
               created_at TEXT NOT NULL
           )"""
    )
    random.seed(42)
    now = datetime.now()
    rows = []
    # 30 дней истории, ~200 заказов в день; последние 6 часов данных нет
    for day in range(30, 0, -1):
        day_start = now - timedelta(days=day)
        for i in range(random.randint(180, 220)):
            ts = day_start + timedelta(minutes=random.randint(0, 1439))
            if ts > now - timedelta(hours=6):
                continue
            amount = None if random.random() < 0.08 else round(random.uniform(100, 5000), 2)
            rows.append((f"ORD-{day:02d}-{i:04d}", random.randint(1, 500), amount,
                         ts.strftime("%Y-%m-%d %H:%M:%S")))
    # Дубликаты order_id
    for _ in range(5):
        rows.append(rows[random.randrange(len(rows))])
    conn.executemany(
        "INSERT INTO sales (order_id, user_id, amount, created_at) VALUES (?, ?, ?, ?)", rows)
    conn.commit()
    conn.close()
    print(f"Demo database created: {DEMO_DB} ({len(rows)} rows)")


def register_in_sentinel() -> None:
    storage.init_db()
    existing = [c for c in storage.list_connections() if c["name"] == "Demo SQLite"]
    if existing:
        print("Demo connection already registered, skipping.")
        return
    conn_id = storage.create_connection(
        "Demo SQLite", "sqlite", {"path": str(DEMO_DB)})
    rules = [
        ("Свежесть sales", "freshness",
         {"table": "sales", "time_column": "created_at", "max_age_minutes": 120}, 30),
        ("Объём sales за сутки", "row_count",
         {"table": "sales", "time_column": "created_at",
          "window_minutes": 1440, "min_rows": 100}, 60),
        ("NULL в amount", "null_check",
         {"table": "sales", "column": "amount", "max_null_percent": 5}, 60),
        ("Дубликаты заказов", "duplicates",
         {"table": "sales", "key_columns": "order_id", "max_duplicates": 0}, 120),
        ("Аномалия дневного объёма", "anomaly",
         {"metric_sql": "SELECT COUNT(*) FROM sales", "sigma": 3, "min_samples": 5}, 60),
    ]
    for name, rtype, params, interval in rules:
        storage.create_rule(name, conn_id, rtype, params,
                            interval_minutes=interval, cooldown_minutes=60, enabled=True)
    print(f"Registered demo connection (id={conn_id}) and {len(rules)} rules.")


if __name__ == "__main__":
    make_demo_database()
    register_in_sentinel()
    print("Done. Start the app:  python run.py")
