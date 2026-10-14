"""Ссылки на фото товаров WB.

Фото лежат на серверах basket-NN.wbbasket.ru; какой сервер обслуживает товар,
определяется «томом» (nm_id // 100000) по официальной таблице маршрутизации WB.
"""

from __future__ import annotations

import requests

ROUTES_URL = "https://cdn.wbbasket.ru/api/v3/upstreams"

Route = tuple[int, int, str]


def load_routes(timeout: float = 15) -> list[Route]:
    data = requests.get(ROUTES_URL, timeout=timeout).json()
    hosts = data["origin"]["mediabasket_route_map"][0]["hosts"]
    return [(int(h["vol_range_from"]), int(h["vol_range_to"]), h["host"]) for h in hosts]


def image_url(nm_id: int, routes: list[Route], size: str = "c246x328") -> str | None:
    vol = int(nm_id) // 100000
    for start, end, host in routes:
        if start <= vol <= end:
            return f"https://{host}/vol{vol}/part{int(nm_id) // 1000}/{int(nm_id)}/images/{size}/1.webp"
    return None
