"""Один сбор выдачи по всем запросам.

    python -m wb_serp.collect                 # все запросы, топ-200
    python -m wb_serp.collect --top-n 100     # другая глубина
    python -m wb_serp.collect --limit 3       # первые 3 запроса (для проверки)
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import logging
import os
import sys
import time
from dataclasses import replace
from pathlib import Path

from . import storage
from .config import MSK, Settings
from .queries import load_queries
from .wb_client import WBSearchClient

log = logging.getLogger("wb_serp")


def _host_label() -> str:
    if os.environ.get("WB_HOST_LABEL"):
        return os.environ["WB_HOST_LABEL"]
    return "github-actions" if os.environ.get("GITHUB_ACTIONS") == "true" else "local"


async def run_collection(settings: Settings, queries: list[str]) -> tuple[int, str]:
    conn = storage.connect(settings.db_path)
    storage.mark_stale_runs(conn)
    query_ids = storage.sync_queries(conn, load_queries(settings.queries_file))
    unknown = [q for q in queries if q not in query_ids]
    if unknown:
        raise SystemExit(f"Запросов нет в {settings.queries_file}: {unknown}")

    run_id = storage.start_run(
        conn, top_n=settings.top_n, dest=settings.dest, city=settings.city, host=_host_label(), queries_total=len(queries)
    )
    log.info(
        "Сбор #%s: %s запросов, топ-%s, город %s (dest=%s), база %s",
        run_id, len(queries), settings.top_n, settings.city, settings.dest, settings.db_path,
    )
    started = time.monotonic()
    fatal_error: str | None = None
    errors: dict[str, str] = {}
    try:
        async with WBSearchClient(
            dest=settings.dest,
            headless=settings.headless,
            request_delay=settings.request_delay,
            max_retries=settings.max_retries,
        ) as client:
            pending = list(queries)
            # Второй проход — только по запросам, которые не удалось собрать с первого раза.
            for attempt in (1, 2):
                failed: list[str] = []
                for i, query in enumerate(pending, 1):
                    t0 = time.monotonic()
                    try:
                        result = await client.search(query, settings.top_n)
                    except Exception as exc:  # noqa: BLE001
                        errors[query] = str(exc)
                        failed.append(query)
                        log.error("[%s/%s] %s — ошибка: %s", i, len(pending), query, exc)
                        continue
                    storage.save_query_result(
                        conn,
                        run_id=run_id,
                        query_id=query_ids[query],
                        collected_at=result.collected_at,
                        observations=result.observations,
                        wb_total=result.wb_total,
                    )
                    errors.pop(query, None)
                    total = f"{result.wb_total:,}".replace(",", " ") if result.wb_total is not None else "?"
                    log.info(
                        "[%s/%s] %s — %s товаров (всего у WB: %s) за %.1f с",
                        i, len(pending), query, len(result.observations), total, time.monotonic() - t0,
                    )
                if not failed or attempt == 2:
                    break
                log.info("Повторяем %s запрос(ов), не собранных с первого раза", len(failed))
                pending = failed
            log.info(
                "Статистика клиента: запросов %s, проверок антибота %s, сессий браузера %s, ответы %s",
                client.stats.requests, client.stats.challenges, client.stats.contexts, client.stats.statuses,
            )
    except Exception as exc:  # noqa: BLE001 — браузер не запустился, нет сети и т. п.
        fatal_error = f"{type(exc).__name__}: {exc}"
        log.exception("Сбор прерван")
    finally:
        for query, error in errors.items():
            storage.save_query_failure(
                conn, run_id=run_id, query_id=query_ids[query], collected_at=storage.utc_now(), error=error
            )
        status = storage.finish_run(conn, run_id, error=fatal_error)
        summary = storage.counts(conn)
        conn.close()
    log.info(
        "Сбор #%s завершён со статусом %s за %.0f с. В базе: %s",
        run_id, status, time.monotonic() - started, summary,
    )
    return run_id, status


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Сбор поисковой выдачи Wildberries")
    parser.add_argument("--top-n", type=int, help="сколько первых товаров выдачи сохранять (по умолчанию 200)")
    parser.add_argument("--db", help="путь к файлу SQLite (по умолчанию data/serp.db)")
    parser.add_argument("--limit", type=int, help="собрать только первые N запросов из списка")
    parser.add_argument("--query", action="append", help="собрать только этот запрос (можно повторять)")
    parser.add_argument("--headful", action="store_true", help="показать окно браузера")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    # Время в логах — московское, независимо от часового пояса машины.
    logging.Formatter.converter = staticmethod(lambda ts: dt.datetime.fromtimestamp(ts, MSK).timetuple())

    settings = Settings.from_env()
    if args.top_n:
        settings = replace(settings, top_n=args.top_n)
    if args.db:
        settings = replace(settings, db_path=Path(args.db))
    if args.headful:
        settings = replace(settings, headless=False)
    if settings.top_n < 1:
        parser.error("--top-n должен быть положительным")

    queries = load_queries(settings.queries_file)
    if args.query:
        queries = args.query
    if args.limit:
        queries = queries[: args.limit]

    _, status = asyncio.run(run_collection(settings, queries))
    return 0 if status in ("ok", "partial") else 1


if __name__ == "__main__":
    sys.exit(main())
