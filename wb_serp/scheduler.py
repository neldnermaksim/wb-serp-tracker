"""Простой планировщик: запускает сбор каждый час (для сервера, Docker или локальной машины).

    python -m wb_serp.scheduler            # каждый час в HH:05 по Москве
    python -m wb_serp.scheduler --minute 0 --now
    python -m wb_serp.scheduler --sync --minute 20   # страховка облачного сбора: скачать базу
                                                     # с GitHub, собрать, если в этот час сбора
                                                     # ещё не было, и опубликовать

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


def _run(module: str, args: list[str], timeout: int = RUN_TIMEOUT) -> int:
    cmd = [sys.executable, "-m", module, *args]
    log("запуск: " + " ".join(cmd[1:]))
    try:
        return subprocess.run(cmd, timeout=timeout).returncode
    except subprocess.TimeoutExpired:
        log(f"{module} не уложился в {timeout // 60} мин и был остановлен")
        return 124


def run_once(extra_args: list[str], sync: bool = False) -> int:
    if not sync:
        return _run("wb_serp.collect", extra_args)
    # Режим синхронизации с веткой data: работает вместе с GitHub Actions и не дублирует его сборы.
    if (code := _run("wb_serp.publish", ["pull"], timeout=600)) != 0:
        return code
    code = _run("wb_serp.collect", ["--min-interval", "40", *extra_args])
    push_code = _run("wb_serp.publish", ["push"], timeout=600)
    return code or push_code


def main() -> None:
    parser = argparse.ArgumentParser(description="Запуск сбора выдачи WB каждый час")
    parser.add_argument("--minute", type=int, default=5, help="минута часа для запуска (0–59), по умолчанию 5")
    parser.add_argument("--now", action="store_true", help="сразу выполнить первый сбор, не дожидаясь расписания")
    parser.add_argument("--sync", action="store_true", help="скачивать базу из ветки data перед сбором и публиковать после")
    parser.add_argument("collect_args", nargs="*", help="аргументы для wb_serp.collect, например --top-n 200")
    args = parser.parse_args()

    if args.now:
        log(f"сбор завершён с кодом {run_once(args.collect_args, args.sync)}")
    while True:
        target = next_run(dt.datetime.now(MSK), args.minute)
        log(f"следующий сбор в {target:%H:%M} МСК")
        while (delay := (target - dt.datetime.now(MSK)).total_seconds()) > 0:
            time.sleep(min(delay, 60))
        log(f"сбор завершён с кодом {run_once(args.collect_args, args.sync)}")


if __name__ == "__main__":
    main()
