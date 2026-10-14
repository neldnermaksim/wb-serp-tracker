"""Сверка данных парсера с тем, что видит покупатель на сайте wildberries.ru.

Открывает страницу поиска в браузере, прокручивает выдачу, читает с карточек
рейтинг, число оценок, цену и дату доставки и сравнивает с тем, что парсер
извлекает из ответа API для тех же товаров.

    python scripts/verify_against_site.py "постельное белье евро" "шелковое постельное белье"
"""

from __future__ import annotations

import asyncio
import datetime as dt
import re
import sys
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from playwright.async_api import async_playwright  # noqa: E402

from wb_serp.config import MSK  # noqa: E402
from wb_serp.parsing import parse_products  # noqa: E402

MONTHS = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря"]
DATE_RE = re.compile(r"(Сегодня|Завтра|Послезавтра|(\d{1,2}) (" + "|".join(MONTHS) + r"))")
RATING_RE = re.compile(r"^(\d[,.]\d)$", re.M)
FEEDBACKS_RE = re.compile(r"([\d\s  ]+?)\s+оцен")
PRICE_RE = re.compile(r"(\d[\d\s  ]*)\s*₽")


def card_delivery_days(text: str, now: dt.datetime) -> int | None:
    m = DATE_RE.search(text)
    if not m:
        return None
    word = m.group(1)
    if word in ("Сегодня", "Завтра", "Послезавтра"):
        return ("Сегодня", "Завтра", "Послезавтра").index(word)
    date = dt.date(now.year, MONTHS.index(m.group(3)) + 1, int(m.group(2)))
    if date < now.date():
        date = date.replace(year=now.year + 1)
    return (date - now.date()).days


def digits(text: str) -> int:
    return int(re.sub(r"\D", "", text))


async def check_query(page, query: str, stats: dict) -> None:
    api: dict[int, dict] = {}

    async def on_response(resp):
        if "u-search/exactmatch" in resp.url and "resultset=catalog" in resp.url and resp.status == 200:
            try:
                for product in (await resp.json()).get("products", []):
                    api[product["id"]] = product
            except Exception:  # noqa: BLE001
                pass

    def handler(resp):
        asyncio.ensure_future(on_response(resp))

    page.on("response", handler)
    await page.goto("https://www.wildberries.ru/catalog/0/search.aspx?search=" + urllib.parse.quote(query), wait_until="domcontentloaded")
    await page.wait_for_timeout(6000)
    for _ in range(15):
        await page.mouse.wheel(0, 2500)
        await page.wait_for_timeout(600)
    now = dt.datetime.now(dt.timezone.utc)
    cards = await page.evaluate(
        "() => Array.from(document.querySelectorAll('[data-nm-id]')).map(a => ({id: +a.getAttribute('data-nm-id'), text: a.innerText}))"
    )
    page.remove_listener("response", handler)
    for card in cards:
        product = api.get(card["id"])
        if not product:
            continue
        (obs,) = parse_products([product], now)
        text = card["text"]
        stats["cards"] += 1

        site_days = card_delivery_days(text, now.astimezone(MSK))
        if site_days is not None and obs.delivery_days is not None:
            stats["delivery"][site_days == obs.delivery_days] += 1

        m = RATING_RE.search(text)
        if m and obs.rating is not None:
            stats["rating"][abs(float(m.group(1).replace(",", ".")) - obs.rating) < 1e-6] += 1

        m = FEEDBACKS_RE.search(text)
        if m and obs.feedbacks is not None:
            stats["feedbacks"][digits(m.group(1)) == obs.feedbacks] += 1

        prices = [digits(p) for p in PRICE_RE.findall(text)]
        if prices and obs.price_kop:
            rub = obs.price_kop / 100
            # Крупно сайт показывает цену «с WB Кошельком» — она на ~2% ниже цены из API.
            stats["price"][any(abs(p - rub) / rub <= 0.03 for p in prices)] += 1
    print(f"  «{query}»: карточек сверено {len(cards)}", flush=True)


async def main(queries: list[str]) -> None:
    stats = {"cards": 0, "delivery": [0, 0], "rating": [0, 0], "feedbacks": [0, 0], "price": [0, 0]}
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, channel="chromium", args=["--disable-blink-features=AutomationControlled"])
        probe = await browser.new_page()
        ua = (await probe.evaluate("navigator.userAgent")).replace("HeadlessChrome", "Chrome")
        await probe.close()
        context = await browser.new_context(locale="ru-RU", timezone_id="Europe/Moscow", viewport={"width": 1440, "height": 900}, user_agent=ua)
        page = await context.new_page()
        for query in queries:
            await check_query(page, query, stats)
        await browser.close()

    print(f"\nВсего карточек: {stats['cards']}")
    for key, title in (("delivery", "срок доставки"), ("rating", "рейтинг"), ("feedbacks", "число оценок"), ("price", "цена")):
        bad, good = stats[key]
        total = good + bad
        share = f"{good / total:.1%}" if total else "—"
        print(f"  {title:15} совпало {good} из {total} ({share})")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:] or ["постельное белье евро", "шелковое постельное белье", "детское постельное белье"]))
