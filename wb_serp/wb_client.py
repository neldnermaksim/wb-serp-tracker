"""Клиент поисковой выдачи Wildberries.

С 2025 года сайт WB закрыт антибот-системой: без cookie ``x_wbaas_token``
поисковый API отвечает 403/498. Токен выдаётся только настоящему браузеру,
прошедшему JS-проверку, он привязан к IP и User-Agent и быстро «выгорает»
(примерно через 20–25 запросов сервер снова требует проверку).

Поэтому запросы выполняются изнутри headless-Chromium (Playwright):
* браузер открывает страницу поиска, проходит проверку и получает токен;
* к поисковому API обращаемся через ``fetch`` прямо на странице — с теми же
  cookie, заголовками и TLS-отпечатком, что и у самого сайта;
* на ответ 498/403 страница заново проходит проверку, запрос повторяется.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
import math
import random
import time
import uuid
from dataclasses import dataclass, field
from urllib.parse import urlencode

from playwright.async_api import Browser, BrowserContext, Page, Playwright, Request, async_playwright

from .config import HOME_URL, PAGE_SIZE, SEARCH_URL, WARMUP_URL
from .parsing import Observation, parse_products

log = logging.getLogger(__name__)

# Заголовки, которые сайт добавляет к запросам своего API (без них — 403).
SITE_HEADER_NAMES = ("deviceid", "x-requested-with", "x-spa-version", "x-userid")
FALLBACK_SPA_VERSION = "14.28.3"

FETCH_JS = """
async ({url, headers}) => {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), 30000);
    try {
        const r = await fetch(url, {credentials: 'include', headers, signal: ctrl.signal});
        return {status: r.status, text: await r.text()};
    } catch (e) {
        return {status: 0, text: String(e)};
    } finally {
        clearTimeout(timer);
    }
}
"""


class WBSearchError(RuntimeError):
    """Не удалось получить страницу выдачи."""


class AntibotError(WBSearchError):
    """Браузер не прошёл антибот-проверку WB."""


@dataclass
class SearchResult:
    query: str
    collected_at: dt.datetime
    observations: list[Observation]
    wb_total: int | None
    pages: int
    duplicates: int = 0


@dataclass
class ClientStats:
    requests: int = 0
    challenges: int = 0
    contexts: int = 0
    retries: int = 0
    statuses: dict[int, int] = field(default_factory=dict)


class WBSearchClient:
    def __init__(self, *, dest: int, headless: bool = True, request_delay: float = 1.0, max_retries: int = 6) -> None:
        self.dest = dest
        self.headless = headless
        self.request_delay = request_delay
        self.max_retries = max_retries
        self.stats = ClientStats()
        self._pw: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None
        self._site_headers: dict[str, str] = {}
        self._last_request_at = 0.0

    # ------------------------------------------------------------------ lifecycle
    async def __aenter__(self) -> "WBSearchClient":
        await self.start()
        return self

    async def __aexit__(self, *exc) -> None:
        await self.close()

    async def start(self) -> None:
        self._pw = await async_playwright().start()
        args = ["--disable-blink-features=AutomationControlled", "--no-first-run"]
        try:
            # «Новый» headless — полноценный Chromium, его WB пропускает.
            self._browser = await self._pw.chromium.launch(headless=self.headless, channel="chromium", args=args)
        except Exception:  # noqa: BLE001 — старые версии Playwright без channel="chromium"
            self._browser = await self._pw.chromium.launch(headless=self.headless, args=args)
        log.info("Браузер запущен: Chromium %s", self._browser.version)
        await self._new_context()

    async def restart(self) -> None:
        """Полный перезапуск браузера — на случай, если он завис или упал."""
        await self.close()
        await self.start()

    async def close(self) -> None:
        for closer in (self._context, self._browser):
            if closer is not None:
                try:
                    await closer.close()
                except Exception:  # noqa: BLE001
                    pass
        if self._pw is not None:
            await self._pw.stop()
        self._pw = self._browser = self._context = self._page = None

    async def _user_agent(self) -> str:
        """UA этого же браузера, но без слова «Headless», по которому WB отсекает ботов."""
        assert self._browser is not None
        page = await self._browser.new_page()
        try:
            ua = await page.evaluate("navigator.userAgent")
        finally:
            await page.close()
        return ua.replace("HeadlessChrome", "Chrome")

    async def _new_context(self) -> None:
        assert self._browser is not None
        if self._context is not None:
            try:
                await self._context.close()
            except Exception:  # noqa: BLE001
                pass
        self.stats.contexts += 1
        self._site_headers = {}
        self._context = await self._browser.new_context(
            locale="ru-RU",
            timezone_id="Europe/Moscow",
            viewport={"width": 1440, "height": 900},
            user_agent=await self._user_agent(),
        )
        # Картинки и видео не нужны — экономим трафик и время.
        await self._context.route(
            "**/*",
            lambda route: route.abort() if route.request.resource_type in ("image", "media") else route.continue_(),
        )
        self._page = await self._context.new_page()
        self._page.on("request", self._remember_site_headers)
        await self._pass_challenge(WARMUP_URL)
        # Ждём, пока сайт сам сделает запрос к API, чтобы взять его заголовки.
        for _ in range(20):
            if "deviceid" in self._site_headers:
                break
            await asyncio.sleep(0.5)
        if "deviceid" not in self._site_headers:
            log.warning("Не удалось подсмотреть заголовки сайта — используем значения по умолчанию")
            self._site_headers = {
                "deviceid": f"site_{uuid.uuid4().hex}",
                "x-requested-with": "XMLHttpRequest",
                "x-spa-version": FALLBACK_SPA_VERSION,
                "x-userid": "0",
            }

    def _remember_site_headers(self, request: Request) -> None:
        if "/__internal/" not in request.url:
            return
        headers = request.headers
        picked = {name: headers[name] for name in SITE_HEADER_NAMES if name in headers}
        if "deviceid" in picked:
            self._site_headers.update(picked)

    async def _token(self) -> str | None:
        assert self._context is not None
        for cookie in await self._context.cookies("https://www.wildberries.ru"):
            if cookie["name"] == "x_wbaas_token":
                return cookie["value"]
        return None

    async def _pass_challenge(self, url: str, timeout: float = 45.0) -> None:
        """Открывает страницу WB и ждёт, пока браузер пройдёт антибот-проверку."""
        assert self._page is not None
        self.stats.challenges += 1
        try:
            await self._page.goto(url, wait_until="domcontentloaded", timeout=60_000)
        except Exception as exc:  # noqa: BLE001
            raise AntibotError(f"Не открылась страница WB: {exc}") from exc
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            await asyncio.sleep(1)
            try:
                title = await self._page.title()
            except Exception:  # noqa: BLE001 — страница перезагружается после проверки
                continue
            # У страницы проверки заголовок «...», у обычной — «Интернет-магазин Wildberries…».
            if "wildberries" in title.lower() and await self._token():
                return
        raise AntibotError("Браузер не прошёл антибот-проверку Wildberries за отведённое время")

    # ------------------------------------------------------------------ requests
    def _search_url(self, query: str, page: int) -> str:
        params = {
            "ab_testing": "false",
            "appType": 1,
            "curr": "rub",
            "dest": self.dest,
            "hide_vflags": 4294967296,
            "inheritFilters": "true",
            "lang": "ru",
            "locale": "ru",
            "page": page,
            "query": query,
            "resultset": "catalog",
            "sort": "popular",
            "spp": 30,
            "suppressSpellcheck": "false",
        }
        return f"{SEARCH_URL}?{urlencode(params)}"

    async def _throttle(self) -> None:
        wait = self._last_request_at + self.request_delay + random.uniform(0, 0.5) - time.monotonic()
        if wait > 0:
            await asyncio.sleep(wait)
        self._last_request_at = time.monotonic()

    async def fetch_page(self, query: str, page: int) -> dict:
        """Одна страница выдачи (до 100 товаров) с повторами и перепрохождением проверки."""
        url = self._search_url(query, page)
        last_error = "нет ответа"
        for attempt in range(1, self.max_retries + 1):
            if attempt > 1:
                self.stats.retries += 1
            try:
                if self._page is None:
                    await self._new_context()
                await self._throttle()
                self.stats.requests += 1
                resp = await self._page.evaluate(FETCH_JS, {"url": url, "headers": self._site_headers})
            except AntibotError as exc:
                last_error = str(exc)
                log.warning("  попытка %s: %s — пересоздаём браузерную сессию", attempt, exc)
                self._page = None
                await asyncio.sleep(5 * attempt)
                continue
            except Exception as exc:  # noqa: BLE001 — упала вкладка/контекст
                last_error = f"ошибка браузера: {exc}"
                log.warning("  попытка %s: %s", attempt, last_error)
                self._page = None
                await asyncio.sleep(3 * attempt)
                continue

            status = int(resp["status"])
            self.stats.statuses[status] = self.stats.statuses.get(status, 0) + 1
            if status == 200:
                try:
                    return json.loads(resp["text"])
                except json.JSONDecodeError:
                    last_error = "WB вернул не-JSON"
            elif status in (401, 403, 498):
                # Токен «выгорел» — проходим проверку заново.
                last_error = f"HTTP {status} (антибот)"
                try:
                    await self._pass_challenge(HOME_URL)
                except AntibotError as exc:
                    last_error = str(exc)
                    self._page = None  # на следующей попытке начнём с чистого контекста
                continue
            elif status == 429 or status >= 500 or status == 0:
                last_error = f"HTTP {status}" if status else f"сеть: {resp['text'][:200]}"
            else:
                raise WBSearchError(f"HTTP {status}: {resp['text'][:200]}")
            await asyncio.sleep(min(60, 2**attempt + random.random()))
        raise WBSearchError(f"Не удалось получить выдачу после {self.max_retries} попыток: {last_error}")

    async def search(self, query: str, top_n: int) -> SearchResult:
        """Первые ``top_n`` товаров выдачи в том порядке, в каком их показывает WB."""
        pages_needed = max(1, math.ceil(top_n / PAGE_SIZE))
        collected_at = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
        observations: list[Observation] = []
        seen: set[int] = set()
        duplicates = 0
        wb_total: int | None = None
        raw_count = 0
        pages = 0
        for page in range(1, pages_needed + 1):
            data = await self.fetch_page(query, page)
            pages += 1
            if wb_total is None and isinstance(data.get("total"), int):
                wb_total = data["total"]
            products = data.get("products") or []
            for obs in parse_products(products, collected_at, start_position=raw_count + 1):
                if obs.position > top_n:
                    break
                if obs.nm_id in seen:
                    # Тот же товар второй раз — оставляем первое (лучшее) место.
                    duplicates += 1
                    continue
                seen.add(obs.nm_id)
                observations.append(obs)
            raw_count += len(products)
            if len(products) < PAGE_SIZE or raw_count >= top_n:
                break  # выдача закончилась или уже набрали top_n
        return SearchResult(query, collected_at, observations, wb_total, pages, duplicates)
