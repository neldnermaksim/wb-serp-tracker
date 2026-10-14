"""Простой планировщик: запускает сбор каждый час (для сервера, Docker или локальной машины).

    python -m wb_serp.scheduler            # каждый час в HH:05 по Москве
    python -m wb_serp.scheduler --minute 0 --now

Каждый сбор выполняется отдельным процессом: если он упадёт или зависнет,
планировщик продолжит работу и запустит следующий сбор по расписанию.
В облаке ту же роль выполняет GitHub Actions (.github/workflows/collect.yml).
"""

from __future__ import annotations

import argparse
import datetime as dt
import subprocess
import sys
import time

from .config import MSK

RUN_TIMEOUT = 50 * 60  # сбор не должен наезжать на следующий час


def next_run(now: dt.datetime, minute: int) -> dt.datetime:
    candidate = now.replace(minute=minute, second=0, microsecond=0)
    if candidate <= now:
        candidate += dt.timedelta(hours=1)
    return candidate


def log(message: str) -> None:
    print(f"{dt.datetime.now(MSK):%Y-%m-%d %H:%M:%S} [scheduler] {message}", flush=True)


def run_once(extra_args: list[str]) -> int:
    cmd = [sys.executable, "-m", "wb_serp.collect", *extra_args]
    log("запуск: " + " ".join(cmd[1:]))
    try:
        return subprocess.run(cmd, timeout=RUN_TIMEOUT).returncode
    except subprocess.TimeoutExpired:
        log(f"сбор не уложился в {RUN_TIMEOUT // 60} мин и был остановлен")
        return 124


def main() -> None:
    parser = argparse.ArgumentParser(description="Запуск сбора выдачи WB каждый час")
    parser.add_argument("--minute", type=int, default=5, help="минута часа для запуска (0–59), по умолчанию 5")
    parser.add_argument("--now", action="store_true", help="сразу выполнить первый сбор, не дожидаясь расписания")
    parser.add_argument("collect_args", nargs="*", help="аргументы для wb_serp.collect, например --top-n 200")
    args = parser.parse_args()

    if args.now:
        log(f"сбор завершён с кодом {run_once(args.collect_args)}")
    while True:
        target = next_run(dt.datetime.now(MSK), args.minute)
        log(f"следующий сбор в {target:%H:%M} МСК")
        while (delay := (target - dt.datetime.now(MSK)).total_seconds()) > 0:
            time.sleep(min(delay, 60))
        log(f"сбор завершён с кодом {run_once(args.collect_args)}")


if __name__ == "__main__":
    main()
