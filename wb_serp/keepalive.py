"""Не даёт приложению на Streamlit Community Cloud уснуть.

Бесплатные приложения засыпают, если их долго никто не открывает, и тогда первый
посетитель видит кнопку «разбудить». Этот скрипт открывает приложение в браузере
(после каждого сбора в GitHub Actions) и, если оно спит, нажимает кнопку.

    python -m wb_serp.keepalive https://<app>.streamlit.app
"""

from __future__ import annotations

import asyncio
import sys

from playwright.async_api import async_playwright

WAKE_BUTTON = "button:has-text('get this app back up')"


async def visit(url: str) -> str:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            await page.goto(url, wait_until="domcontentloaded", timeout=90_000)
            await page.wait_for_timeout(8_000)
            woke = False
            if await page.locator(WAKE_BUTTON).count():
                await page.locator(WAKE_BUTTON).first.click()
                woke = True
                await page.wait_for_timeout(60_000)
            # Приложение встроено во фрейм; ждём, пока в нём появится заголовок.
            for frame in page.frames:
                try:
                    if await frame.locator("h1").count():
                        title = await frame.locator("h1").first.inner_text()
                        return f"{'разбудили, ' if woke else ''}приложение отвечает: {title}"
                except Exception:  # noqa: BLE001
                    continue
            return f"{'разбудили, ' if woke else ''}страница открыта, заголовок не найден"
        finally:
            await browser.close()


def main() -> int:
    if len(sys.argv) < 2 or not sys.argv[1].startswith("http"):
        print("Адрес приложения не задан — пропускаем")
        return 0
    print(asyncio.run(visit(sys.argv[1])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
