"""Сценарии сбора с подменённым клиентом WB (без обращения к сети)."""

import asyncio
import dataclasses
import datetime as dt
import sqlite3

from wb_serp import collect
from wb_serp.config import Settings
from wb_serp.parsing import Observation
from wb_serp.wb_client import SearchResult, WBSearchError

QUERIES = [f"запрос {i}" for i in range(1, 11)]


class FakeClient:
    """Ведёт себя как WBSearchClient: ok_queries собираются, остальные — падают."""

    instances: list["FakeClient"] = []

    def __init__(self, ok_queries=(), fail_first_attempt=(), **_):
        self.ok_queries = set(ok_queries)
        self.fail_first_attempt = set(fail_first_attempt)
        self.restarts = 0
        self.calls: list[str] = []
        self.stats = type("S", (), {"requests": 0, "challenges": 0, "contexts": 1, "statuses": {}})()
        FakeClient.instances.append(self)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None

    async def restart(self):
        self.restarts += 1

    async def search(self, query, top_n):
        self.calls.append(query)
        if query in self.fail_first_attempt:
            self.fail_first_attempt.discard(query)
            raise WBSearchError("HTTP 498 (антибот)")
        if query not in self.ok_queries:
            raise WBSearchError("HTTP 498 (антибот)")
        now = dt.datetime.now(dt.timezone.utc)
        obs = [Observation(p, 1000 + p, 99900, 4.7, 5, 30, 2, "т", "б", "п", 1) for p in range(1, top_n + 1)]
        return SearchResult(query, now, obs, 5000, 1)


def run(tmp_path, monkeypatch, **client_kwargs):
    queries_file = tmp_path / "queries.txt"
    queries_file.write_text("\n".join(QUERIES), encoding="utf-8")
    settings = dataclasses.replace(
        Settings.from_env(), db_path=tmp_path / "serp.db", queries_file=queries_file, top_n=3
    )
    FakeClient.instances.clear()
    monkeypatch.setattr(collect, "WBSearchClient", lambda **kw: FakeClient(**client_kwargs, **kw))
    run_id, status = asyncio.run(collect.run_collection(settings, QUERIES))
    conn = sqlite3.connect(settings.db_path)
    return run_id, status, conn, FakeClient.instances[0]


def test_all_queries_ok(tmp_path, monkeypatch):
    _, status, conn, _ = run(tmp_path, monkeypatch, ok_queries=QUERIES)
    assert status == "ok"
    assert conn.execute("SELECT COUNT(*) FROM observations").fetchone() == (30,)


def test_failed_query_is_retried_in_second_pass(tmp_path, monkeypatch):
    _, status, conn, client = run(tmp_path, monkeypatch, ok_queries=QUERIES, fail_first_attempt=["запрос 4"])
    assert status == "ok"
    assert client.calls.count("запрос 4") == 2
    assert conn.execute("SELECT COUNT(*) FROM query_runs WHERE status = 'ok'").fetchone() == (10,)


def test_series_of_failures_restarts_browser_then_stops(tmp_path, monkeypatch):
    # Первые 2 запроса собираются, дальше WB «лежит».
    _, status, conn, client = run(tmp_path, monkeypatch, ok_queries=QUERIES[:2])
    assert client.restarts == 1  # после 3 ошибок подряд — перезапуск браузера
    assert len(client.calls) == 2 + 6  # после 6 ошибок подряд — остановка, а не 60 бесполезных попыток
    assert status == "partial"
    row = conn.execute("SELECT queries_ok, error FROM runs").fetchone()
    assert row[0] == 2 and "подряд" in row[1]
    # Собранное до сбоя сохранено, неудачные запросы помечены.
    assert conn.execute("SELECT COUNT(*) FROM query_runs WHERE status = 'failed'").fetchone() == (6,)
    assert conn.execute("SELECT COUNT(*) FROM observations").fetchone() == (6,)


def test_min_interval_skips_backup_run(tmp_path, monkeypatch):
    run(tmp_path, monkeypatch, ok_queries=QUERIES)
    queries_file = tmp_path / "queries.txt"
    monkeypatch.setenv("WB_DB_PATH", str(tmp_path / "serp.db"))
    monkeypatch.setenv("WB_QUERIES_FILE", str(queries_file))
    FakeClient.instances.clear()
    assert collect.main(["--min-interval", "40"]) == 0
    assert FakeClient.instances == []  # клиент даже не создавался
    conn = sqlite3.connect(tmp_path / "serp.db")
    assert conn.execute("SELECT COUNT(*) FROM runs").fetchone() == (1,)
