"""Хранение истории в SQLite.

Данные только добавляются: каждый сбор — новая запись в ``runs``, наблюдения
привязаны к ней. Ни один код в проекте не удаляет и не перезаписывает прошлые
наблюдения, поэтому история позиций копится от сбора к сбору.
"""

from __future__ import annotations

import datetime as dt
import sqlite3
from pathlib import Path
from typing import Iterable, Sequence

from .parsing import Observation

SCHEMA = """
CREATE TABLE IF NOT EXISTS queries (
    id          INTEGER PRIMARY KEY,
    text        TEXT    NOT NULL UNIQUE,      -- исходная формулировка запроса
    sort_order  INTEGER NOT NULL,             -- порядок в исходном списке
    is_active   INTEGER NOT NULL DEFAULT 1,
    added_at    TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS runs (
    id            INTEGER PRIMARY KEY,
    started_at    TEXT    NOT NULL,           -- UTC, ISO 8601
    finished_at   TEXT,
    status        TEXT    NOT NULL,           -- running | ok | partial | failed
    top_n         INTEGER NOT NULL,
    dest          INTEGER NOT NULL,           -- код города доставки WB
    city          TEXT    NOT NULL,
    host          TEXT,                       -- где выполнялся сбор
    queries_total INTEGER,
    queries_ok    INTEGER,
    items_total   INTEGER,
    error         TEXT
);

-- Результат сбора по одному запросу внутри одного запуска.
-- Нужен, чтобы отличать «товара нет в топе» от «запрос не удалось собрать».
CREATE TABLE IF NOT EXISTS query_runs (
    run_id       INTEGER NOT NULL REFERENCES runs(id),
    query_id     INTEGER NOT NULL REFERENCES queries(id),
    collected_at TEXT    NOT NULL,            -- UTC, момент получения выдачи
    status       TEXT    NOT NULL,            -- ok | failed
    items        INTEGER NOT NULL DEFAULT 0,
    wb_total     INTEGER,                     -- сколько товаров WB нашёл всего
    error        TEXT,
    PRIMARY KEY (run_id, query_id)
);

-- Справочник товаров: последние известные название, бренд и продавец.
CREATE TABLE IF NOT EXISTS products (
    nm_id         INTEGER PRIMARY KEY,
    name          TEXT,
    brand         TEXT,
    supplier      TEXT,                       -- название продавца
    supplier_id   INTEGER,
    first_seen_at TEXT NOT NULL,
    last_seen_at  TEXT NOT NULL
);

-- Наблюдения: позиция и характеристики товара в конкретной выдаче.
CREATE TABLE IF NOT EXISTS observations (
    run_id         INTEGER NOT NULL,
    query_id       INTEGER NOT NULL,
    position       INTEGER NOT NULL,          -- 1 = первое место в выдаче
    nm_id          INTEGER NOT NULL,
    price_kop      INTEGER,                   -- цена для покупателя, копейки
    rating         REAL,
    feedbacks      INTEGER,
    delivery_hours INTEGER,                   -- time1 + time2 из API
    delivery_days  INTEGER,                   -- календарных дней: сегодня 0, завтра 1
    PRIMARY KEY (run_id, query_id, position),
    FOREIGN KEY (run_id, query_id) REFERENCES query_runs(run_id, query_id)
) WITHOUT ROWID;

CREATE UNIQUE INDEX IF NOT EXISTS idx_obs_query_nm ON observations(query_id, nm_id, run_id);

-- Плоское представление «как в ТЗ»: одна строка = один товар в одной выдаче.
CREATE VIEW IF NOT EXISTS v_observations AS
SELECT
    q.text                    AS query,
    qr.collected_at           AS collected_at_utc,
    o.position                AS position,
    o.nm_id                   AS nm_id,
    o.price_kop / 100.0       AS price_rub,
    o.rating                  AS rating,
    o.feedbacks               AS feedbacks,
    o.delivery_days           AS delivery_days,
    p.supplier                AS seller,
    p.brand                   AS brand,
    p.name                    AS name,
    o.run_id                  AS run_id
FROM observations o
JOIN queries q     ON q.id = o.query_id
JOIN query_runs qr ON qr.run_id = o.run_id AND qr.query_id = o.query_id
LEFT JOIN products p ON p.nm_id = o.nm_id;
"""


def utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0)


def iso(ts: dt.datetime) -> str:
    return ts.astimezone(dt.timezone.utc).isoformat(timespec="seconds")


def connect(path: Path | str) -> sqlite3.Connection:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=60)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 60000")
    conn.executescript(SCHEMA)
    return conn


def sync_queries(conn: sqlite3.Connection, queries: Sequence[str]) -> dict[str, int]:
    """Добавляет новые запросы, сохраняя формулировки как есть. Возвращает text -> id.

    Запросы, исчезнувшие из списка, помечаются неактивными, но не удаляются —
    их история остаётся доступной.
    """
    now = iso(utc_now())
    with conn:
        for order, text in enumerate(queries, start=1):
            conn.execute(
                """
                INSERT INTO queries (text, sort_order, is_active, added_at) VALUES (?, ?, 1, ?)
                ON CONFLICT(text) DO UPDATE SET sort_order = excluded.sort_order, is_active = 1
                """,
                (text, order, now),
            )
        placeholders = ",".join("?" * len(queries)) or "''"
        conn.execute(f"UPDATE queries SET is_active = 0 WHERE text NOT IN ({placeholders})", list(queries))
    rows = conn.execute("SELECT text, id FROM queries WHERE is_active = 1").fetchall()
    return {text: qid for text, qid in rows}


def start_run(conn: sqlite3.Connection, *, top_n: int, dest: int, city: str, host: str, queries_total: int) -> int:
    with conn:
        cur = conn.execute(
            "INSERT INTO runs (started_at, status, top_n, dest, city, host, queries_total) VALUES (?, 'running', ?, ?, ?, ?, ?)",
            (iso(utc_now()), top_n, dest, city, host, queries_total),
        )
    return int(cur.lastrowid)


def save_query_result(
    conn: sqlite3.Connection,
    *,
    run_id: int,
    query_id: int,
    collected_at: dt.datetime,
    observations: Iterable[Observation],
    wb_total: int | None,
) -> int:
    """Сохраняет выдачу по одному запросу одной транзакцией. Возвращает число товаров."""
    observations = list(observations)
    ts = iso(collected_at)
    with conn:
        conn.execute(
            "INSERT INTO query_runs (run_id, query_id, collected_at, status, items, wb_total) VALUES (?, ?, ?, 'ok', ?, ?)",
            (run_id, query_id, ts, len(observations), wb_total),
        )
        conn.executemany(
            """
            INSERT INTO observations
                (run_id, query_id, position, nm_id, price_kop, rating, feedbacks, delivery_hours, delivery_days)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (run_id, query_id, o.position, o.nm_id, o.price_kop, o.rating, o.feedbacks, o.delivery_hours, o.delivery_days)
                for o in observations
            ],
        )
        conn.executemany(
            """
            INSERT INTO products (nm_id, name, brand, supplier, supplier_id, first_seen_at, last_seen_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(nm_id) DO UPDATE SET
                name        = COALESCE(excluded.name, products.name),
                brand       = COALESCE(excluded.brand, products.brand),
                supplier    = COALESCE(excluded.supplier, products.supplier),
                supplier_id = COALESCE(excluded.supplier_id, products.supplier_id),
                last_seen_at = MAX(products.last_seen_at, excluded.last_seen_at)
            """,
            [(o.nm_id, o.name, o.brand, o.supplier, o.supplier_id, ts, ts) for o in observations],
        )
    return len(observations)


def save_query_failure(conn: sqlite3.Connection, *, run_id: int, query_id: int, collected_at: dt.datetime, error: str) -> None:
    with conn:
        conn.execute(
            "INSERT INTO query_runs (run_id, query_id, collected_at, status, items, error) VALUES (?, ?, ?, 'failed', 0, ?)",
            (run_id, query_id, iso(collected_at), error[:500]),
        )


def finish_run(conn: sqlite3.Connection, run_id: int, *, error: str | None = None) -> str:
    ok, items = conn.execute(
        "SELECT COUNT(*), COALESCE(SUM(items), 0) FROM query_runs WHERE run_id = ? AND status = 'ok'", (run_id,)
    ).fetchone()
    total = conn.execute("SELECT queries_total FROM runs WHERE id = ?", (run_id,)).fetchone()[0]
    if ok == 0:
        status = "failed"
    elif ok < total:
        status = "partial"
    else:
        status = "ok"
    with conn:
        conn.execute(
            "UPDATE runs SET finished_at = ?, status = ?, queries_ok = ?, items_total = ?, error = ? WHERE id = ?",
            (iso(utc_now()), status, ok, items, error[:1000] if error else None, run_id),
        )
    return status


def mark_stale_runs(conn: sqlite3.Connection) -> None:
    """Запуски, оборванные посреди работы (например, выключили компьютер), закрываем с итогами."""
    stale = [row[0] for row in conn.execute("SELECT id FROM runs WHERE status = 'running'")]
    for run_id in stale:
        finish_run(conn, run_id, error="Сбор был прерван до завершения")


def counts(conn: sqlite3.Connection) -> dict[str, int]:
    tables = ("queries", "runs", "query_runs", "products", "observations")
    return {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in tables}
