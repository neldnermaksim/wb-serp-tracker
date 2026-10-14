"""Синхронизация базы с веткой ``data`` репозитория на GitHub.

    python -m wb_serp.publish pull   # скачать актуальную базу в data/serp.db
    python -m wb_serp.publish push   # проверить и опубликовать data/serp.db

Ветка ``data`` содержит один коммит со сжатой базой ``serp.db.xz``. Каждый
публикуемый файл — полная база со всей историей, поэтому старые коммиты не нужны
и ветка перезаписывается целиком (размер репозитория не растёт).

Защита от потери истории:
* если ветка есть, но скачать её не удалось — сбор останавливается, а не
  начинается с пустой базы;
* перед публикацией проверяется целостность SQLite и то, что ни в одной таблице
  не стало меньше строк, чем было в скачанной базе.
"""

from __future__ import annotations

import argparse
import json
import lzma
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

from .config import Settings

BRANCH = "data"
REMOTE_FILE = "serp.db.xz"
COUNTS_FILE = ".pulled_counts.json"
TABLES = ("queries", "runs", "query_runs", "products", "observations")
# Индекс нужен только для быстрых выборок — в публикуемой копии его нет (файл меньше),
# сборщик и веб-интерфейс создают его заново после загрузки.
DROP_FOR_PUBLISH = ("idx_obs_query_nm",)


def git(*args: str, check: bool = True, capture: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], check=check, capture_output=capture, text=True)


def table_counts(path: Path) -> dict[str, int]:
    conn = sqlite3.connect(path)
    try:
        return {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in TABLES}
    finally:
        conn.close()


def remote_branch_exists(remote: str) -> bool:
    result = git("ls-remote", "--exit-code", "--heads", remote, BRANCH, check=False)
    if result.returncode == 0:
        return True
    if result.returncode == 2:  # ветки нет — самый первый запуск
        return False
    raise SystemExit(f"Не удалось связаться с {remote}: {result.stderr.strip()}")


def pull(db_path: Path, remote: str) -> None:
    counts_path = db_path.parent / COUNTS_FILE
    if not remote_branch_exists(remote):
        print(f"Ветки {BRANCH} ещё нет — начинаем новую базу")
        counts_path.unlink(missing_ok=True)
        return
    git("fetch", "--depth=1", remote, f"+refs/heads/{BRANCH}:refs/remotes/{remote}/{BRANCH}")
    blob = subprocess.run(["git", "show", f"{remote}/{BRANCH}:{REMOTE_FILE}"], check=True, capture_output=True).stdout
    db_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = db_path.with_suffix(".download")
    tmp.write_bytes(lzma.decompress(blob))
    check_integrity(tmp)
    tmp.replace(db_path)
    counts = table_counts(db_path)
    counts_path.write_text(json.dumps(counts))
    print(f"База скачана: {db_path} ({db_path.stat().st_size / 1e6:.1f} МБ), {counts}")


def check_integrity(path: Path) -> None:
    conn = sqlite3.connect(path)
    try:
        result = conn.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        conn.close()
    if result != "ok":
        raise SystemExit(f"База {path} повреждена: {result}")


def push(db_path: Path, remote: str, message: str | None) -> None:
    if not db_path.exists():
        raise SystemExit(f"Нет базы {db_path}")
    check_integrity(db_path)
    counts = table_counts(db_path)
    counts_path = db_path.parent / COUNTS_FILE
    if counts_path.exists():
        before = json.loads(counts_path.read_text())
        shrunk = {t: (before[t], counts[t]) for t in TABLES if counts.get(t, 0) < before.get(t, 0)}
        if shrunk:
            raise SystemExit(f"Отказ публиковать: в базе стало меньше строк, чем было — {shrunk}")
    elif remote_branch_exists(remote):
        raise SystemExit("Ветка data уже существует, а база не была скачана командой pull — публикация отменена")

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_db = Path(tmpdir) / "serp.db"
        src = sqlite3.connect(db_path)
        dst = sqlite3.connect(tmp_db)
        src.backup(dst)  # согласованная копия, даже если базу кто-то читает
        src.close()
        for index in DROP_FOR_PUBLISH:
            dst.execute(f"DROP INDEX IF EXISTS {index}")
        dst.execute("VACUUM")
        dst.close()
        packed = Path(tmpdir) / REMOTE_FILE
        with open(tmp_db, "rb") as f_in, lzma.open(packed, "wb", preset=9) as f_out:
            shutil.copyfileobj(f_in, f_out)
        size_mb = packed.stat().st_size / 1e6
        if size_mb > 95:
            raise SystemExit(f"Сжатая база {size_mb:.0f} МБ — больше лимита GitHub на файл (100 МБ)")

        blob = git("hash-object", "-w", str(packed)).stdout.strip()
        tree = subprocess.run(
            ["git", "mktree"], input=f"100644 blob {blob}\t{REMOTE_FILE}\n", check=True, capture_output=True, text=True
        ).stdout.strip()
        runs = counts["runs"]
        msg = message or f"data: {runs} сборов, {counts['observations']} наблюдений"
        commit = git("commit-tree", tree, "-m", msg).stdout.strip()
        git("push", "--force", remote, f"{commit}:refs/heads/{BRANCH}", capture=False)
    counts_path.write_text(json.dumps(counts))
    print(f"Опубликовано в ветку {BRANCH}: {size_mb:.1f} МБ, {counts}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Синхронизация базы с веткой data на GitHub")
    parser.add_argument("action", choices=["pull", "push"])
    parser.add_argument("--remote", default="origin")
    parser.add_argument("--db", help="путь к базе (по умолчанию data/serp.db)")
    parser.add_argument("-m", "--message", help="сообщение коммита при push")
    args = parser.parse_args()
    db_path = Path(args.db) if args.db else Settings.from_env().db_path
    if args.action == "pull":
        pull(db_path, args.remote)
    else:
        push(db_path, args.remote, args.message)


if __name__ == "__main__":
    sys.exit(main())
