"""Публикация базы в ветку data — на локальном bare-репозитории вместо GitHub."""

import datetime as dt
import shutil
import subprocess
import uuid

import pytest

from wb_serp import publish, storage
from wb_serp.parsing import Observation

UTC = dt.timezone.utc


def sh(*args, cwd):
    subprocess.run(args, cwd=cwd, check=True, capture_output=True)


@pytest.fixture()
def remote(tmp_path, monkeypatch):
    bare = tmp_path / "remote.git"
    sh("git", "init", "--bare", "-q", str(bare), cwd=tmp_path)
    for var, value in {
        "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
    }.items():
        monkeypatch.setenv(var, value)
    return bare


def worker(tmp_path, remote, name):
    """Отдельная рабочая копия — как отдельный запуск сборщика."""
    path = tmp_path / name
    sh("git", "init", "-q", str(path), cwd=tmp_path)
    sh("git", "remote", "add", "origin", str(remote), cwd=path)
    return path


def add_run(db_path, n_items=2):
    conn = storage.connect(db_path)
    ids = storage.sync_queries(conn, ["постельное белье"])
    run_id = storage.start_run(conn, top_n=200, dest=1, city="Москва", host="test", queries_total=1)
    obs = [Observation(p, 100 + p, 1000, 4.5, 1, 20, 1, "n", "b", "s", 1) for p in range(1, n_items + 1)]
    storage.save_query_result(conn, run_id=run_id, query_id=ids["постельное белье"], collected_at=dt.datetime.now(UTC), observations=obs, wb_total=10)
    storage.finish_run(conn, run_id)
    conn.close()


def runs_in_remote(tmp_path, remote):
    check = worker(tmp_path, remote, f"checker-{uuid.uuid4().hex[:6]}")
    db = check / "data" / "serp.db"
    with pytest.MonkeyPatch.context() as mp:
        mp.chdir(check)
        publish.pull(db, "origin")
    return publish.table_counts(db)["runs"]


def test_first_publish_then_append(tmp_path, remote, monkeypatch):
    a = worker(tmp_path, remote, "a")
    monkeypatch.chdir(a)
    db = a / "data" / "serp.db"
    publish.pull(db, "origin")  # ветки ещё нет
    add_run(db)
    publish.push(db, "origin", None)
    assert runs_in_remote(tmp_path, remote) == 1

    publish.pull(db, "origin")
    add_run(db)
    publish.push(db, "origin", None)
    assert runs_in_remote(tmp_path, remote) == 2


def test_concurrent_writer_cannot_overwrite(tmp_path, remote, monkeypatch):
    a, b = worker(tmp_path, remote, "a"), worker(tmp_path, remote, "b")
    db_a, db_b = a / "data" / "serp.db", b / "data" / "serp.db"
    monkeypatch.chdir(a)
    publish.pull(db_a, "origin")
    add_run(db_a)
    publish.push(db_a, "origin", None)

    # Оба сборщика скачали одну и ту же версию...
    publish.pull(db_a, "origin")
    monkeypatch.chdir(b)
    publish.pull(db_b, "origin")
    # ...B успел опубликовать свой сбор первым (данные отличаются, как у реальных сборов)...
    add_run(db_b, n_items=5)
    publish.push(db_b, "origin", None)
    # ...и A уже не может перезаписать ветку своей версией без сбора B.
    monkeypatch.chdir(a)
    add_run(db_a)
    with pytest.raises(SystemExit, match="другой сборщик"):
        publish.push(db_a, "origin", None)
    assert runs_in_remote(tmp_path, remote) == 2
    # На GitHub остался сбор B (5 товаров), а не версия A.
    check = worker(tmp_path, remote, "final")
    monkeypatch.chdir(check)
    publish.pull(check / "data" / "serp.db", "origin")
    assert publish.table_counts(check / "data" / "serp.db")["observations"] == 2 + 5


def test_refuses_to_publish_shrunk_or_unpulled_db(tmp_path, remote, monkeypatch):
    a = worker(tmp_path, remote, "a")
    monkeypatch.chdir(a)
    db = a / "data" / "serp.db"
    publish.pull(db, "origin")
    add_run(db, n_items=3)
    publish.push(db, "origin", None)

    publish.pull(db, "origin")
    conn = storage.connect(db)
    conn.execute("DELETE FROM observations WHERE position = 3")  # имитация бага, потерявшего данные
    conn.commit()
    conn.close()
    with pytest.raises(SystemExit, match="меньше строк"):
        publish.push(db, "origin", None)

    (db.parent / publish.STATE_FILE).unlink()
    with pytest.raises(SystemExit, match="не была скачана"):
        publish.push(db, "origin", None)
    shutil.rmtree(a / "data")
