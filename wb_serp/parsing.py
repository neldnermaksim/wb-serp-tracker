"""Разбор ответа поискового API Wildberries в строки наблюдений.

Соответствие полей API тому, что видит покупатель на сайте, проверено сверкой
с карточками товаров (см. scripts/verify_against_site.py):

* цена — ``sizes[].price.product`` в копейках: цена со всеми скидками
  (на сайте рядом показывается ещё «с WB Кошельком», её API не отдаёт);
* рейтинг — ``reviewRating`` (то самое «4,8» на карточке);
* количество отзывов — ``feedbacks`` («15 575 оценок»);
* продавец — ``supplier`` (юрлицо/магазин, не путать с брендом);
* срок доставки — ``time1 + time2`` часов от текущего момента.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any, Iterable

from .config import MSK

# Сайт показывает дату доставки как дату момента «сейчас + time1 + time2 + 1 час»
# (по Москве). Без этого часа расходятся товары, которые «приезжают» в 23:xx —
# сайт показывает уже следующий день. Сверка на 1378 карточках: 1378 совпадений.
DELIVERY_EXTRA_HOURS = 1


@dataclass(frozen=True)
class Observation:
    position: int
    nm_id: int
    price_kop: int | None
    rating: float | None
    feedbacks: int | None
    delivery_hours: int | None
    delivery_days: int | None
    # Атрибуты карточки — хранятся в справочнике products.
    name: str | None
    brand: str | None
    supplier: str | None
    supplier_id: int | None


def _int_or_none(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _str_or_none(value: Any) -> str | None:
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def extract_price_kop(product: dict) -> int | None:
    """Минимальная цена для покупателя среди размеров, в копейках."""
    prices = []
    for size in product.get("sizes") or []:
        price = (size.get("price") or {}).get("product")
        price = _int_or_none(price)
        if price and price > 0:
            prices.append(price)
    return min(prices) if prices else None


def extract_rating(product: dict) -> float | None:
    """Рейтинг как на карточке. У товара без оценок WB присылает 0 — это «нет рейтинга»."""
    for key in ("reviewRating", "nmReviewRating"):
        value = product.get(key)
        if value is None:
            continue
        try:
            rating = round(float(value), 2)
        except (TypeError, ValueError):
            continue
        if rating <= 0:
            return None
        return rating
    return None


def extract_feedbacks(product: dict) -> int | None:
    for key in ("feedbacks", "nmFeedbacks"):
        value = _int_or_none(product.get(key))
        if value is not None and value >= 0:
            return value
    return None


def extract_delivery_hours(product: dict) -> int | None:
    """Сколько часов до доставки по данным WB (time1 + time2)."""
    candidates = [product, *(product.get("sizes") or [])]
    for item in candidates:
        t1, t2 = _int_or_none(item.get("time1")), _int_or_none(item.get("time2"))
        if t1 is not None and t2 is not None:
            return t1 + t2
    return None


def delivery_days(collected_at: dt.datetime, hours: int | None) -> int | None:
    """Срок доставки в календарных днях: сегодня — 0, завтра — 1 и т. д. (по Москве)."""
    if hours is None:
        return None
    now_msk = collected_at.astimezone(MSK)
    arrival = now_msk + dt.timedelta(hours=hours + DELIVERY_EXTRA_HOURS)
    return (arrival.date() - now_msk.date()).days


def parse_products(
    products: Iterable[dict],
    collected_at: dt.datetime,
    start_position: int = 1,
) -> list[Observation]:
    """Превращает список товаров одной страницы выдачи в наблюдения.

    Позиция — порядковый номер товара в выдаче, начиная со ``start_position``.
    Товары без ``id`` пропускаются, но место в выдаче за ними сохраняется.
    """
    result: list[Observation] = []
    for offset, product in enumerate(products):
        nm_id = _int_or_none(product.get("id"))
        if not nm_id:
            continue
        hours = extract_delivery_hours(product)
        result.append(
            Observation(
                position=start_position + offset,
                nm_id=nm_id,
                price_kop=extract_price_kop(product),
                rating=extract_rating(product),
                feedbacks=extract_feedbacks(product),
                delivery_hours=hours,
                delivery_days=delivery_days(collected_at, hours),
                name=_str_or_none(product.get("name")),
                brand=_str_or_none(product.get("brand")),
                supplier=_str_or_none(product.get("supplier")),
                supplier_id=_int_or_none(product.get("supplierId")),
            )
        )
    return result
