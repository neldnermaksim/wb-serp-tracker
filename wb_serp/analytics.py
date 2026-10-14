"""Выборки из базы для веб-интерфейса. Все функции возвращают pandas.DataFrame.

Время в базе хранится в UTC, здесь переводится в московское (колонки ``*_msk``).
"""

from __future__ import annotations

import sqlite3
from typing import Sequence

import pandas as pd

from .config import MSK


def connect_readonly(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, check_same_thread=False)
    conn.execute("PRAGMA query_only = ON")
    return conn


def _to_msk(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series, utc=True).dt.tz_convert(MSK)


def _in_clause(values: Sequence) -> str:
    return ",".join("?" * len(values))


def wb_url(nm_id: int) -> str:
    return f"https://www.wildberries.ru/catalog/{int(nm_id)}/detail.aspx"


def queries_overview(conn: sqlite3.Connection) -> pd.DataFrame:
    """Все запросы в исходном порядке и сколько раз каждый был успешно собран."""
    df = pd.read_sql_query(
        """
        SELECT q.id AS query_id, q.text, q.sort_order, q.is_active,
               COUNT(qr.run_id) AS collections,
               MAX(qr.collected_at) AS last_collected_at
        FROM queries q
        LEFT JOIN query_runs qr ON qr.query_id = q.id AND qr.status = 'ok'
        GROUP BY q.id
        ORDER BY q.is_active DESC, q.sort_order
        """,
        conn,
    )
    df["last_collected_msk"] = _to_msk(df["last_collected_at"])
    return df


def query_collections(conn: sqlite3.Connection, query_id: int) -> pd.DataFrame:
    """Успешные сборы по запросу — «сетка» времени для графика."""
    df = pd.read_sql_query(
        """
        SELECT run_id, collected_at, items, wb_total
        FROM query_runs
        WHERE query_id = ? AND status = 'ok'
        ORDER BY collected_at
        """,
        conn,
        params=(query_id,),
    )
    df["collected_msk"] = _to_msk(df["collected_at"])
    return df


def products_for_query(conn: sqlite3.Connection, query_id: int) -> pd.DataFrame:
    """Все товары, когда-либо найденные по запросу, со сводкой по позициям.

    ``last_position`` — место в самом свежем сборе запроса (NaN, если в нём товара не было).
    """
    df = pd.read_sql_query(
        """
        WITH last_run AS (
            SELECT MAX(run_id) AS run_id FROM query_runs WHERE query_id = ? AND status = 'ok'
        )
        SELECT o.nm_id,
               p.name, p.brand, p.supplier,
               COUNT(*)           AS times_seen,
               MIN(o.position)    AS best_position,
               MAX(CASE WHEN o.run_id = (SELECT run_id FROM last_run) THEN o.position END) AS last_position,
               MIN(qr.collected_at) AS first_seen_at,
               MAX(qr.collected_at) AS last_seen_at
        FROM observations o
        JOIN query_runs qr ON qr.run_id = o.run_id AND qr.query_id = o.query_id
        LEFT JOIN products p ON p.nm_id = o.nm_id
        WHERE o.query_id = ?
        GROUP BY o.nm_id
        """,
        conn,
        params=(query_id, query_id),
    )
    df["first_seen_msk"] = _to_msk(df["first_seen_at"])
    df["last_seen_msk"] = _to_msk(df["last_seen_at"])
    # Сначала товары из свежей выдачи по порядку, затем остальные по лучшей позиции.
    df["_in_last"] = df["last_position"].notna()
    df = df.sort_values(["_in_last", "last_position", "best_position"], ascending=[False, True, True])
    return df.drop(columns="_in_last").reset_index(drop=True)


def position_history(conn: sqlite3.Connection, query_id: int, nm_ids: Sequence[int]) -> pd.DataFrame:
    """История позиций выбранных товаров по всем успешным сборам запроса.

    Для каждого сбора и каждого товара — ровно одна строка. Если товара в этом сборе
    не было, ``position`` и характеристики пустые (NaN): на графике это разрыв линии,
    а не выдуманная позиция. Сборы, которые завершились ошибкой, в сетку не входят —
    про них мы ничего не знаем.
    """
    nm_ids = [int(x) for x in nm_ids]
    grid = query_collections(conn, query_id)[["run_id", "collected_msk"]]
    if not nm_ids or grid.empty:
        return pd.DataFrame(
            columns=["run_id", "collected_msk", "nm_id", "position", "price_rub", "rating", "feedbacks", "delivery_days", "found"]
        )
    obs = pd.read_sql_query(
        f"""
        SELECT run_id, nm_id, position, price_kop / 100.0 AS price_rub, rating, feedbacks, delivery_days
        FROM observations
        WHERE query_id = ? AND nm_id IN ({_in_clause(nm_ids)})
        """,
        conn,
        params=(query_id, *nm_ids),
    )
    full = grid.merge(pd.DataFrame({"nm_id": nm_ids}), how="cross")
    full = full.merge(obs, on=["run_id", "nm_id"], how="left")
    full["found"] = full["position"].notna()
    return full.sort_values(["nm_id", "collected_msk"]).reset_index(drop=True)


def snapshot(conn: sqlite3.Connection, query_id: int, run_id: int) -> pd.DataFrame:
    """Выдача по запросу в одном сборе + изменение позиции к предыдущему сбору."""
    prev = conn.execute(
        "SELECT MAX(run_id) FROM query_runs WHERE query_id = ? AND status = 'ok' AND run_id < ?",
        (query_id, run_id),
    ).fetchone()[0]
    df = pd.read_sql_query(
        """
        SELECT o.position, o.nm_id, p.name, p.brand, p.supplier,
               o.price_kop / 100.0 AS price_rub, o.rating, o.feedbacks, o.delivery_days,
               prev.position AS prev_position
        FROM observations o
        LEFT JOIN products p ON p.nm_id = o.nm_id
        LEFT JOIN observations prev
               ON prev.query_id = o.query_id AND prev.nm_id = o.nm_id AND prev.run_id = ?
        WHERE o.query_id = ? AND o.run_id = ?
        ORDER BY o.position
        """,
        conn,
        params=(prev if prev is not None else -1, query_id, run_id),
    )
    # Положительное значение — товар поднялся (номер позиции уменьшился).
    df["change"] = df["prev_position"] - df["position"]
    df["is_new"] = df["prev_position"].isna() & (prev is not None)
    df["url"] = df["nm_id"].map(wb_url)
    return df


def latest_characteristics(conn: sqlite3.Connection, query_id: int, nm_ids: Sequence[int]) -> pd.DataFrame:
    """Последние известные характеристики выбранных товаров в выдаче по запросу."""
    nm_ids = [int(x) for x in nm_ids]
    if not nm_ids:
        return pd.DataFrame()
    df = pd.read_sql_query(
        f"""
        WITH ranked AS (
            SELECT o.*, qr.collected_at,
                   ROW_NUMBER() OVER (PARTITION BY o.nm_id ORDER BY o.run_id DESC) AS rn,
                   LEAD(o.position) OVER (PARTITION BY o.nm_id ORDER BY o.run_id DESC) AS prev_seen_position
            FROM observations o
            JOIN query_runs qr ON qr.run_id = o.run_id AND qr.query_id = o.query_id
            WHERE o.query_id = ? AND o.nm_id IN ({_in_clause(nm_ids)})
        ),
        stats AS (
            SELECT nm_id, MIN(position) AS best_position, COUNT(*) AS times_seen
            FROM observations WHERE query_id = ? AND nm_id IN ({_in_clause(nm_ids)})
            GROUP BY nm_id
        )
        SELECT r.nm_id, p.name, p.brand, p.supplier,
               r.position AS last_position, r.prev_seen_position, r.run_id,
               s.best_position, s.times_seen,
               r.price_kop / 100.0 AS price_rub, r.rating, r.feedbacks, r.delivery_days,
               r.collected_at AS last_seen_at
        FROM ranked r
        JOIN stats s ON s.nm_id = r.nm_id
        LEFT JOIN products p ON p.nm_id = r.nm_id
        WHERE r.rn = 1
        """,
        conn,
        params=(query_id, *nm_ids, query_id, *nm_ids),
    )
    latest_run = conn.execute(
        "SELECT MAX(run_id) FROM query_runs WHERE query_id = ? AND status = 'ok'", (query_id,)
    ).fetchone()[0]
    df["in_latest"] = df["run_id"] == latest_run
    df["last_seen_msk"] = _to_msk(df["last_seen_at"])
    df["url"] = df["nm_id"].map(wb_url)
    order = {nm: i for i, nm in enumerate(nm_ids)}
    return df.sort_values("nm_id", key=lambda s: s.map(order)).reset_index(drop=True)


def runs_log(conn: sqlite3.Connection) -> pd.DataFrame:
    df = pd.read_sql_query(
        """
        SELECT id AS run_id, started_at, finished_at, status, top_n, city, dest, host,
               queries_total, queries_ok, items_total, error
        FROM runs ORDER BY id DESC
        """,
        conn,
    )
    df["started_msk"] = _to_msk(df["started_at"])
    df["finished_msk"] = _to_msk(df["finished_at"])
    df["duration_min"] = (df["finished_msk"] - df["started_msk"]).dt.total_seconds() / 60
    return df


def db_summary(conn: sqlite3.Connection) -> dict:
    row = conn.execute(
        """
        SELECT (SELECT COUNT(*) FROM runs WHERE status IN ('ok', 'partial')),
               (SELECT COUNT(*) FROM observations),
               (SELECT COUNT(*) FROM products),
               (SELECT MIN(started_at) FROM runs WHERE status IN ('ok', 'partial')),
               (SELECT MAX(finished_at) FROM runs WHERE status IN ('ok', 'partial')),
               (SELECT top_n FROM runs ORDER BY id DESC LIMIT 1),
               (SELECT city FROM runs ORDER BY id DESC LIMIT 1),
               (SELECT dest FROM runs ORDER BY id DESC LIMIT 1)
        """
    ).fetchone()
    keys = ("runs", "observations", "products", "first_run_at", "last_run_at", "top_n", "city", "dest")
    summary = dict(zip(keys, row))
    for key in ("first_run_at", "last_run_at"):
        summary[key.replace("_at", "_msk")] = (
            pd.Timestamp(summary[key]).tz_convert(MSK) if summary[key] else None
        )
    return summary


def snapshot_summary(conn: sqlite3.Connection, query_id: int, run_id: int) -> dict:
    """Что изменилось в выдаче по сравнению с предыдущим сбором: новые, выбывшие, лидеры роста и падения."""
    prev = conn.execute(
        "SELECT MAX(run_id) FROM query_runs WHERE query_id = ? AND status = 'ok' AND run_id < ?",
        (query_id, run_id),
    ).fetchone()[0]
    result = {"prev_run_id": prev, "new": None, "dropped": None, "riser": None, "faller": None}
    if prev is None:
        return result
    snap = snapshot(conn, query_id, run_id)
    result["new"] = int(snap["is_new"].sum())
    result["dropped"] = conn.execute(
        """
        SELECT COUNT(*) FROM observations p
        WHERE p.query_id = ? AND p.run_id = ?
          AND NOT EXISTS (SELECT 1 FROM observations c WHERE c.query_id = p.query_id AND c.run_id = ? AND c.nm_id = p.nm_id)
        """,
        (query_id, prev, run_id),
    ).fetchone()[0]
    moved = snap.dropna(subset=["change"])
    if not moved.empty:
        up = moved.loc[moved["change"].idxmax()]
        down = moved.loc[moved["change"].idxmin()]
        if up["change"] > 0:
            result["riser"] = {"nm_id": int(up["nm_id"]), "change": int(up["change"]), "position": int(up["position"]), "brand": up["brand"]}
        if down["change"] < 0:
            result["faller"] = {"nm_id": int(down["nm_id"]), "change": int(down["change"]), "position": int(down["position"]), "brand": down["brand"]}
    return result
