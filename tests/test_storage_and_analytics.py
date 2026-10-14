"""Проверки на временной базе с синтетическими наблюдениями (только для тестов)."""

import datetime as dt

import pandas as pd
import pytest

from wb_serp import analytics as an
from wb_serp import storage
from wb_serp.parsing import Observation

UTC = dt.timezone.utc
QUERIES = ["постельное белье 2 спальное", "постельное белье 1,5", "постельное белье 2 спальное на резинке 160x200"]


def obs(position, nm_id, price=100000):
    return Observation(position, nm_id, price, 4.8, 10, 30, 2, f"Товар {nm_id}", "Бренд", "Продавец", 1)


@pytest.fixture()
def db(tmp_path):
    path = tmp_path / "serp.db"
    conn = storage.connect(path)
    ids = storage.sync_queries(conn, QUERIES)
    yield path, conn, ids
    conn.close()


def make_run(conn, ids, results, at, failed=()):
    run_id = storage.start_run(conn, top_n=200, dest=1259570991, city="Москва", host="test", queries_total=len(QUERIES))
    for text, observations in results.items():
        storage.save_query_result(conn, run_id=run_id, query_id=ids[text], collected_at=at, observations=observations, wb_total=1000)
    for text in failed:
        storage.save_query_failure(conn, run_id=run_id, query_id=ids[text], collected_at=at, error="HTTP 498")
    return run_id, storage.finish_run(conn, run_id)


def test_queries_saved_verbatim(db):
    _, conn, _ = db
    stored = [r[0] for r in conn.execute("SELECT text FROM queries ORDER BY sort_order")]
    assert stored == QUERIES  # «1,5», латинская x и т. п. — без изменений


def test_repeated_runs_append_history(db):
    _, conn, ids = db
    q = QUERIES[0]
    t1 = dt.datetime(2026, 10, 14, 10, 5, tzinfo=UTC)
    make_run(conn, ids, {q: [obs(1, 11), obs(2, 22)]}, t1)
    before = conn.execute("SELECT * FROM observations ORDER BY run_id, position").fetchall()
    make_run(conn, ids, {q: [obs(1, 22), obs(2, 11)]}, t1 + dt.timedelta(hours=1))
    after = conn.execute("SELECT * FROM observations ORDER BY run_id, position").fetchall()
    assert after[: len(before)] == before  # прежние строки не изменились
    assert len(after) == 4
    history = conn.execute(
        "SELECT run_id, position FROM observations WHERE query_id = ? AND nm_id = 11 ORDER BY run_id", (ids[q],)
    ).fetchall()
    assert history == [(1, 1), (2, 2)]


def test_run_status_and_failures(db):
    _, conn, ids = db
    at = dt.datetime(2026, 10, 14, 10, 5, tzinfo=UTC)
    _, status = make_run(conn, ids, {QUERIES[0]: [obs(1, 11)]}, at, failed=QUERIES[1:])
    assert status == "partial"
    _, status = make_run(conn, ids, {q: [obs(1, 11)] for q in QUERIES}, at)
    assert status == "ok"


def test_interrupted_run_is_closed_later(db):
    _, conn, ids = db
    run_id = storage.start_run(conn, top_n=200, dest=1, city="Москва", host="test", queries_total=3)
    storage.mark_stale_runs(conn)
    status, error = conn.execute("SELECT status, error FROM runs WHERE id = ?", (run_id,)).fetchone()
    assert status == "failed" and "прерван" in error


def test_sync_queries_never_deletes(db):
    _, conn, ids = db
    make_run(conn, ids, {QUERIES[2]: [obs(1, 11)]}, dt.datetime(2026, 10, 14, tzinfo=UTC))
    storage.sync_queries(conn, QUERIES[:2])
    assert conn.execute("SELECT is_active FROM queries WHERE text = ?", (QUERIES[2],)).fetchone() == (0,)
    assert conn.execute("SELECT COUNT(*) FROM observations").fetchone() == (1,)


def test_position_history_leaves_gaps_for_missing_products(db):
    path, conn, ids = db
    q = QUERIES[0]
    t = dt.datetime(2026, 10, 14, 10, 5, tzinfo=UTC)
    make_run(conn, ids, {q: [obs(1, 11), obs(2, 22)]}, t)
    make_run(conn, ids, {q: [obs(1, 22)]}, t + dt.timedelta(hours=1))  # товара 11 нет в выдаче
    make_run(conn, ids, {}, t + dt.timedelta(hours=2), failed=[q])  # сбор упал — про него ничего не знаем
    make_run(conn, ids, {q: [obs(5, 11), obs(1, 22)]}, t + dt.timedelta(hours=3))

    ro = an.connect_readonly(str(path))
    hist = an.position_history(ro, ids[q], [11, 22])
    p11 = hist[hist.nm_id == 11]["position"].tolist()
    assert len(p11) == 3  # три успешных сбора; упавший в сетку не входит
    assert p11[0] == 1 and pd.isna(p11[1]) and p11[2] == 5  # пропуск = NaN, а не выдуманная позиция
    assert hist[hist.nm_id == 11]["found"].tolist() == [True, False, True]


def test_snapshot_change_and_new(db):
    path, conn, ids = db
    q = QUERIES[0]
    t = dt.datetime(2026, 10, 14, 10, 5, tzinfo=UTC)
    make_run(conn, ids, {q: [obs(1, 11), obs(2, 22)]}, t)
    run2, _ = make_run(conn, ids, {q: [obs(1, 22), obs(2, 11), obs(3, 33)]}, t + dt.timedelta(hours=1))
    snap = an.snapshot(an.connect_readonly(str(path)), ids[q], run2).set_index("nm_id")
    assert snap.at[22, "change"] == 1  # поднялся на 1
    assert snap.at[11, "change"] == -1  # опустился на 1
    assert bool(snap.at[33, "is_new"])


def test_products_for_query_orders_by_latest_position(db):
    path, conn, ids = db
    q = QUERIES[0]
    t = dt.datetime(2026, 10, 14, 10, 5, tzinfo=UTC)
    make_run(conn, ids, {q: [obs(1, 11), obs(2, 22), obs(3, 33)]}, t)
    make_run(conn, ids, {q: [obs(1, 33), obs(2, 11)]}, t + dt.timedelta(hours=1))
    products = an.products_for_query(an.connect_readonly(str(path)), ids[q])
    assert products["nm_id"].tolist() == [33, 11, 22]
    assert pd.isna(products.set_index("nm_id").at[22, "last_position"])
    assert products.set_index("nm_id").at[33, "best_position"] == 1


def test_latest_characteristics(db):
    path, conn, ids = db
    q = QUERIES[0]
    t = dt.datetime(2026, 10, 14, 10, 5, tzinfo=UTC)
    make_run(conn, ids, {q: [obs(3, 11, price=150000)]}, t)
    make_run(conn, ids, {q: [obs(1, 11, price=120000)]}, t + dt.timedelta(hours=1))
    latest = an.latest_characteristics(an.connect_readonly(str(path)), ids[q], [11]).iloc[0]
    assert latest["last_position"] == 1 and latest["prev_seen_position"] == 3
    assert latest["price_rub"] == 1200 and bool(latest["in_latest"])
