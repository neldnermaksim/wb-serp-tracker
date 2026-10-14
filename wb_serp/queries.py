"""Список поисковых запросов.

Источник — Google Sheets «Запросы WB» из ТЗ. Локальная копия лежит в queries.txt
(по одной формулировке на строку, как в таблице). Обновить её из таблицы:

    python -m wb_serp.queries --sync
"""

from __future__ import annotations

import argparse
import csv
import io
import urllib.request
from pathlib import Path

from .config import Settings

SHEET_ID = "1K0m4229w_1LONgrNzWpx8lkkDcAlbdZH5ifHenZV3x8"
SHEET_CSV_URL = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv"


def load_queries(path: Path) -> list[str]:
    """Читает запросы как есть: без нормализации регистра, «ё», пробелов внутри строки."""
    queries: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if text and text not in queries:
            queries.append(text)
    if not queries:
        raise ValueError(f"В {path} нет ни одного запроса")
    return queries


def fetch_sheet_queries(url: str = SHEET_CSV_URL) -> list[str]:
    with urllib.request.urlopen(url, timeout=30) as resp:
        text = resp.read().decode("utf-8")
    rows = csv.reader(io.StringIO(text))
    return [row[0].strip() for row in rows if row and row[0].strip()]


def main() -> None:
    parser = argparse.ArgumentParser(description="Список поисковых запросов WB")
    parser.add_argument("--sync", action="store_true", help="перезаписать queries.txt актуальным списком из Google Sheets")
    args = parser.parse_args()
    settings = Settings.from_env()
    if args.sync:
        queries = fetch_sheet_queries()
        settings.queries_file.write_text("\n".join(queries) + "\n", encoding="utf-8")
        print(f"Сохранено {len(queries)} запросов в {settings.queries_file}")
    for i, q in enumerate(load_queries(settings.queries_file), 1):
        print(f"{i:>3}. {q}")


if __name__ == "__main__":
    main()
