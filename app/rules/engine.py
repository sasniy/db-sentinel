"""Движок проверок: выполняет правило на подключении и возвращает результат.

Результат: {"status": "ok"|"alert"|"error", "value": float|None, "message": str}
"""
import math
import re
from datetime import date, datetime, timedelta

from .. import storage
from ..connectors import get_connector
from ..i18n import t

# Разрешаем в именах таблиц/колонок только буквы, цифры, подчёркивание и точку
# (schema.table) — защита от кривого SQL при подстановке идентификаторов.
_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)?$")

_OPERATORS = {
    ">":  lambda v, th: v > th,
    ">=": lambda v, th: v >= th,
    "<":  lambda v, th: v < th,
    "<=": lambda v, th: v <= th,
    "==": lambda v, th: v == th,
    "!=": lambda v, th: v != th,
}


def _ident(name: str) -> str:
    name = (name or "").strip()
    if not _IDENT_RE.match(name):
        raise ValueError(f"Invalid identifier: {name!r}")
    return name


_SQL_SOURCE_RE = re.compile(r"(?is)^\s*(select|with)\b")


def _source(p: dict) -> str:
    """Источник данных правила: имя таблицы или свой SELECT-подзапрос
    (поле source_sql) — удобно для больших таблиц с фильтрами WHERE/PREWHERE."""
    sql = str(p.get("source_sql") or "").strip().rstrip(";").strip()
    if sql:
        if not _SQL_SOURCE_RE.match(sql):
            raise ValueError("source_sql must start with SELECT or WITH")
        return f"({sql}) AS src"
    return _ident(p["table"])


def _source_label(p: dict) -> str:
    """Имя источника для сообщений."""
    return (p.get("table") or "").strip() or "SQL"


def _now(p: dict) -> datetime:
    """Текущее время в той зоне, в которой хранятся таймстемпы таблицы."""
    return datetime.utcnow() if p.get("use_utc") else datetime.now()


def _time_literal(minutes_ago: int, p: dict) -> str:
    ts = _now(p) - timedelta(minutes=minutes_ago)
    return ts.strftime("%Y-%m-%d %H:%M:%S")


def _parse_ts(value) -> datetime | None:
    """MAX(time_column) может прийти как datetime, date или строка — приводим к datetime."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None) if value.tzinfo else value
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time())
    s = str(value).strip().replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(s[:26], fmt)
        except ValueError:
            continue
    return None


def run_rule(rule: dict, connection: dict) -> dict:
    """Выполнить правило. Никогда не бросает исключений — ошибки идут в status=error."""
    lang = storage.get_language()
    try:
        with get_connector(connection["db_type"], connection["params"]) as db:
            return _dispatch(rule, db, connection["db_type"], lang)
    except Exception as e:
        return {"status": "error", "value": None,
                "message": t("msg.error", lang, error=f"{type(e).__name__}: {e}")}


def _dispatch(rule: dict, db, db_type: str, lang: str) -> dict:
    p = rule["params"]
    kind = rule["rule_type"]
    if kind == "freshness":
        return _check_freshness(p, db, lang)
    if kind == "row_count":
        return _check_row_count(p, db, lang)
    if kind == "null_check":
        return _check_nulls(p, db, lang)
    if kind == "duplicates":
        return _check_duplicates(p, db, lang)
    if kind == "anomaly":
        return _check_anomaly(rule, p, db, lang)
    if kind == "anomaly_history":
        return _check_anomaly_history(p, db, db_type, lang)
    if kind == "custom_sql":
        return _check_custom(p, db, lang)
    raise ValueError(f"Unknown rule type: {kind}")


def _check_freshness(p: dict, db, lang: str) -> dict:
    src, col = _source(p), _ident(p["time_column"])
    max_age = float(p.get("max_age_minutes", 60))
    raw = db.fetch_value(f"SELECT MAX({col}) FROM {src}")
    ts = _parse_ts(raw)
    if ts is None:
        return {"status": "alert", "value": None,
                "message": t("msg.freshness_empty", lang,
                             table=_source_label(p), column=col)}
    age_min = (_now(p) - ts).total_seconds() / 60
    ok = age_min <= max_age
    key = "msg.freshness_ok" if ok else "msg.freshness_alert"
    return {"status": "ok" if ok else "alert", "value": round(age_min, 1),
            "message": t(key, lang, age=age_min, max=int(max_age))}


def _check_row_count(p: dict, db, lang: str) -> dict:
    min_rows = float(p.get("min_rows", 1))
    window = int(p.get("window_minutes") or 0)
    sql = f"SELECT COUNT(*) FROM {_source(p)}"
    if window > 0:
        col = _ident(p["time_column"])
        sql += f" WHERE {col} >= '{_time_literal(window, p)}'"
    count = float(db.fetch_value(sql) or 0)
    ok = count >= min_rows
    key = "msg.rowcount_ok" if ok else "msg.rowcount_alert"
    return {"status": "ok" if ok else "alert", "value": count,
            "message": t(key, lang, value=count, min=int(min_rows))}


def _check_nulls(p: dict, db, lang: str) -> dict:
    src, col = _source(p), _ident(p["column"])
    max_pct = float(p.get("max_null_percent", 0))
    window = int(p.get("window_minutes") or 0)
    where = ""
    if window > 0:
        tcol = _ident(p["time_column"])
        where = f" WHERE {tcol} >= '{_time_literal(window, p)}'"
    row = db.fetch_one(
        f"SELECT COUNT(*), SUM(CASE WHEN {col} IS NULL THEN 1 ELSE 0 END) FROM {src}{where}"
    )
    total = float(row[0] or 0) if row else 0
    if total == 0:
        return {"status": "alert", "value": None,
                "message": t("msg.null_empty", lang, table=_source_label(p))}
    nulls = float(row[1] or 0)
    pct = nulls / total * 100
    ok = pct <= max_pct
    key = "msg.null_ok" if ok else "msg.null_alert"
    return {"status": "ok" if ok else "alert", "value": round(pct, 2),
            "message": t(key, lang, column=col, value=pct, max=max_pct)}


def _check_duplicates(p: dict, db, lang: str) -> dict:
    keys = [_ident(k) for k in str(p["key_columns"]).split(",") if k.strip()]
    if not keys:
        raise ValueError("key_columns is empty")
    max_dup = float(p.get("max_duplicates", 0))
    key_list = ", ".join(keys)
    dup = float(db.fetch_value(
        f"SELECT COUNT(*) FROM (SELECT {key_list} FROM {_source(p)} "
        f"GROUP BY {key_list} HAVING COUNT(*) > 1) AS dup_t"
    ) or 0)
    ok = dup <= max_dup
    key = "msg.dup_ok" if ok else "msg.dup_alert"
    return {"status": "ok" if ok else "alert", "value": dup,
            "message": t(key, lang, keys=key_list, value=dup, max=int(max_dup))}


def _check_anomaly(rule: dict, p: dict, db, lang: str) -> dict:
    value = db.fetch_value(str(p["metric_sql"]))
    if value is None:
        return {"status": "alert", "value": None, "message": t("msg.no_value", lang)}
    value = float(value)
    sigma = float(p.get("sigma", 3))
    min_samples = int(p.get("min_samples", 5))
    history = storage.previous_values(rule["id"], limit=int(p.get("history_size", 30)))
    if len(history) < min_samples:
        return {"status": "ok", "value": value,
                "message": t("msg.anomaly_warmup", lang, value=value,
                             have=len(history), need=min_samples)}
    mean = sum(history) / len(history)
    variance = sum((x - mean) ** 2 for x in history) / len(history)
    std = math.sqrt(variance)
    # При нулевом разбросе истории любое отклонение считаем аномалией
    is_anomaly = abs(value - mean) > sigma * std if std > 0 else value != mean
    key = "msg.anomaly_alert" if is_anomaly else "msg.anomaly_ok"
    return {"status": "alert" if is_anomaly else "ok", "value": value,
            "message": t(key, lang, value=value, mean=mean, std=std, sigma=sigma)}


# Формат метки периода: единый для всех БД, сортируется как строка
_BUCKET_FMT = {"day": "%Y-%m-%d", "hour": "%Y-%m-%d %H"}


def _bucket_expr(db_type: str, col: str, granularity: str) -> str:
    """SQL-выражение, приводящее таймстемп к метке периода в формате _BUCKET_FMT."""
    if db_type == "sqlite":
        fmt = "%Y-%m-%d" if granularity == "day" else "%Y-%m-%d %H"
        return f"strftime('{fmt}', {col})"
    if db_type == "postgresql":
        fmt = "YYYY-MM-DD" if granularity == "day" else "YYYY-MM-DD HH24"
        return f"to_char({col}, '{fmt}')"
    if db_type == "clickhouse":
        fmt = "%Y-%m-%d" if granularity == "day" else "%Y-%m-%d %H"
        return f"formatDateTime({col}, '{fmt}')"
    raise ValueError(f"Unsupported db_type for anomaly_history: {db_type}")


def _check_anomaly_history(p: dict, db, db_type: str, lang: str) -> dict:
    """Аномалия по истории самой таблицы: метрика агрегируется по периодам
    (день/час) за последние N дней, последний ЗАВЕРШЁННЫЙ период сравнивается
    с историей по z-score. Пропущенные периоды считаются нулём — так ловится
    и «данные вообще не приехали».
    """
    src, col = _source(p), _ident(p["time_column"])
    granularity = p.get("granularity", "day")
    if granularity not in _BUCKET_FMT:
        raise ValueError(f"Unknown granularity: {granularity}")
    fmt = _BUCKET_FMT[granularity]
    days = int(p.get("history_days", 30))
    sigma = float(p.get("sigma", 3))
    min_samples = int(p.get("min_samples", 5))
    metric = str(p.get("metric") or "COUNT(*)").strip()
    seasonality = bool(p.get("seasonality"))

    expr = _bucket_expr(db_type, col, granularity)
    since = _time_literal(days * 1440, p)
    rows = db.fetch_all(
        f"SELECT {expr} AS bucket, {metric} FROM {src} "
        f"WHERE {col} >= '{since}' GROUP BY {expr} ORDER BY {expr}"
    )
    data = {str(r[0]): float(r[1] or 0) for r in rows}
    if not data:
        return {"status": "alert", "value": None,
                "message": t("msg.hanom_nodata", lang, days=days)}

    now = _now(p)
    step = timedelta(days=1) if granularity == "day" else timedelta(hours=1)
    target_dt = now - step                     # последний завершённый период
    target_label = target_dt.strftime(fmt)
    target_value = data.get(target_label, 0.0)

    # Полный ряд периодов до target; пропуски = 0. Первый период истории
    # пропускаем — он обрезан условием WHERE и почти всегда неполный.
    history: list[float] = []
    cur = now - timedelta(days=days) + step
    while cur.strftime(fmt) < target_label:
        if seasonality:
            same_season = (cur.weekday() == target_dt.weekday()) if granularity == "day" \
                else (cur.hour == target_dt.hour)
            if not same_season:
                cur += step
                continue
        history.append(data.get(cur.strftime(fmt), 0.0))
        cur += step

    if len(history) < min_samples:
        return {"status": "ok", "value": target_value,
                "message": t("msg.hanom_warmup", lang,
                             have=len(history), need=min_samples)}

    mean = sum(history) / len(history)
    std = math.sqrt(sum((x - mean) ** 2 for x in history) / len(history))
    is_anomaly = abs(target_value - mean) > sigma * std if std > 0 else target_value != mean
    key = "msg.hanom_alert" if is_anomaly else "msg.hanom_ok"
    return {"status": "alert" if is_anomaly else "ok", "value": target_value,
            "message": t(key, lang, period=target_label, value=target_value,
                         mean=mean, std=std, sigma=sigma, n=len(history))}


def _check_custom(p: dict, db, lang: str) -> dict:
    op = str(p.get("operator", ">")).strip()
    if op not in _OPERATORS:
        raise ValueError(f"Unknown operator: {op!r}")
    threshold = float(p.get("threshold", 0))
    value = db.fetch_value(str(p["sql"]))
    if value is None:
        return {"status": "alert", "value": None, "message": t("msg.no_value", lang)}
    value = float(value)
    ok = _OPERATORS[op](value, threshold)
    key = "msg.custom_ok" if ok else "msg.custom_alert"
    return {"status": "ok" if ok else "alert", "value": value,
            "message": t(key, lang, value=value, op=op, threshold=threshold)}
