"""Настройки сборщика. Любой параметр можно переопределить переменной окружения."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT_DIR = Path(__file__).resolve().parent.parent

# Часовой пояс, в котором считаются «сегодня/завтра» для срока доставки
# и в котором время показывается в интерфейсе.
MSK = ZoneInfo("Europe/Moscow")

# Код города доставки WB. Значение 1259570991 возвращает гео-сервис WB
# (user-geo-data.wildberries.ru/get-geo-info) для адреса «Москва» с координатами центра
# (55.753737, 37.6201). Фиксируем его, чтобы выдача и сроки доставки были сопоставимы.
MOSCOW_DEST = 1259570991

# Публичный поисковый эндпоинт, которым пользуется сайт wildberries.ru.
SEARCH_URL = "https://www.wildberries.ru/__internal/u-search/exactmatch/ru/common/v18/search"
# Страница поиска — на ней проходит антибот-проверка и выдаётся cookie x_wbaas_token.
WARMUP_URL = "https://www.wildberries.ru/catalog/0/search.aspx?search=%D0%BF%D0%BE%D1%81%D1%82%D0%B5%D0%BB%D1%8C%D0%BD%D0%BE%D0%B5%20%D0%B1%D0%B5%D0%BB%D1%8C%D0%B5"
HOME_URL = "https://www.wildberries.ru/"

# WB отдаёт по 100 товаров на страницу выдачи.
PAGE_SIZE = 100


def _env_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    return int(value) if value not in (None, "") else default


def _env_float(name: str, default: float) -> float:
    value = os.environ.get(name)
    return float(value) if value not in (None, "") else default


@dataclass(frozen=True)
class Settings:
    db_path: Path
    queries_file: Path
    top_n: int
    dest: int
    city: str
    request_delay: float  # пауза между запросами к WB, секунды
    max_retries: int  # попыток на одну страницу выдачи
    headless: bool

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            db_path=Path(os.environ.get("WB_DB_PATH", ROOT_DIR / "data" / "serp.db")),
            queries_file=Path(os.environ.get("WB_QUERIES_FILE", ROOT_DIR / "queries.txt")),
            top_n=_env_int("WB_TOP_N", 200),
            dest=_env_int("WB_DEST", MOSCOW_DEST),
            city=os.environ.get("WB_CITY", "Москва"),
            request_delay=_env_float("WB_REQUEST_DELAY", 1.0),
            max_retries=_env_int("WB_MAX_RETRIES", 6),
            headless=os.environ.get("WB_HEADLESS", "1") != "0",
        )
