"""Графики (Plotly), оформленные под светлую и тёмную тему интерфейса."""

from __future__ import annotations

import math
from typing import Mapping

import pandas as pd
import plotly.graph_objects as go

from .ui import tokens

# Категориальная палитра: порядок слотов фиксирован и проверен на различимость
# при всех типах цветовой слепоты (соседние пары ΔE ≥ 8). Светлая и тёмная версии.
PALETTE_LIGHT = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"]
PALETTE_DARK = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"]
MAX_SERIES = len(PALETTE_LIGHT)
# Разные маркеры дублируют цвет — линии различимы и без цвета (печать, дальтонизм).
MARKERS = ["circle", "square", "diamond", "triangle-up", "x", "triangle-down", "pentagon", "star"]
FONT = "Manrope, -apple-system, Segoe UI, Roboto, sans-serif"


def _fmt_price(value: float | None) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "цена —"
    return f"{value:,.0f} ₽".replace(",", " ")


def _base_layout(fig: go.Figure, dark: bool, height: int) -> None:
    t = tokens(dark)
    fig.update_layout(
        height=height,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font={"family": FONT, "color": t.muted, "size": 12},
        margin={"l": 6, "r": 6, "t": 36, "b": 6},
        hoverlabel={
            "bgcolor": t.card,
            "bordercolor": t.card_border if not dark else "#3a2e4d",
            "font": {"family": FONT, "color": t.text, "size": 13},
            "namelength": -1,
        },
    )
    # automargin: поля под подписи осей рассчитываются автоматически, иначе подписи обрезаются.
    axis = {"gridcolor": t.grid, "zeroline": False, "linecolor": t.grid, "tickfont": {"color": t.muted}, "automargin": True}
    fig.update_xaxes(**axis)
    fig.update_yaxes(**axis)


def position_chart(
    history: pd.DataFrame,
    labels: Mapping[int, str],
    slots: Mapping[int, int],
    *,
    top_n: int,
    full_depth: bool = False,
    dark: bool = False,
) -> go.Figure:
    """Линии позиций: ось Y перевёрнута (1 — вверху), пропуски — разрывы линий."""
    palette = PALETTE_DARK if dark else PALETTE_LIGHT
    t = tokens(dark)
    fig = go.Figure()

    for nm_id in labels:
        part = history[history["nm_id"] == nm_id].sort_values("collected_msk")
        if part.empty:
            continue
        slot = slots.get(nm_id, 0) % MAX_SERIES
        color = palette[slot]
        price = [_fmt_price(v) for v in part["price_rub"]]
        fig.add_trace(
            go.Scatter(
                x=part["collected_msk"],
                y=part["position"],
                name=labels[nm_id],
                mode="lines+markers",
                connectgaps=False,  # товара нет в выдаче — линия прерывается
                line={"color": color, "width": 2.5, "shape": "linear"},
                marker={
                    "color": color,
                    "size": 9,
                    "symbol": MARKERS[slot],
                    "line": {"color": t.card, "width": 2},
                },
                customdata=list(zip([nm_id] * len(part), price)),
                hovertemplate="ID %{customdata[0]} — позиция <b>%{y}</b> · %{customdata[1]}<extra></extra>",
            )
        )

    positions = history["position"].dropna()
    if full_depth or positions.empty:
        y_range = [top_n + 0.5, 0.5]
    else:
        lo, hi = positions.min(), positions.max()
        pad = max(1.0, (hi - lo) * 0.08)
        y_range = [hi + pad, max(0.5, lo - pad)]

    _base_layout(fig, dark, 470)
    fig.update_layout(
        hovermode="x unified",
        # Легенда сверху слева; панель инструментов Plotly показывается только при наведении справа.
        legend={
            "orientation": "h", "yanchor": "bottom", "y": 1.0, "xanchor": "left", "x": 0, "title": None,
            "font": {"color": t.text, "size": 12}, "itemclick": "toggle", "itemdoubleclick": "toggleothers",
        },
        dragmode="zoom",
    )
    fig.update_yaxes(
        title={"text": "Позиция (1 — вверху)", "font": {"color": t.muted, "size": 12}},
        range=y_range,  # range «сверху вниз» = перевёрнутая ось
        tickformat="d",
    )
    times = history["collected_msk"].dropna().unique()
    if len(times) == 1:
        # Один сбор: без явного диапазона Plotly растягивает ось на секунды и дублирует подписи.
        only = pd.Timestamp(times[0])
        fig.update_xaxes(range=[only - pd.Timedelta(hours=1), only + pd.Timedelta(hours=1)])
    fig.update_xaxes(
        title=None,
        tickformat="%H:%M\n%d.%m",
        hoverformat="%d.%m.%Y, %H:%M МСК",
        showspikes=True,
        spikemode="across",
        spikethickness=1,
        spikedash="dot",
        spikecolor=t.muted,
    )
    return fig


def runs_chart(runs: pd.DataFrame, *, dark: bool = False) -> go.Figure:
    """Лента запусков: по столбцу на сбор, высота — сколько запросов собрано из 70."""
    t = tokens(dark)
    color = runs["status"].map({"ok": t.ok, "partial": t.warn, "failed": t.bad}).fillna(t.muted)
    label = runs["status"].map({"ok": "успешно", "partial": "частично", "failed": "ошибка"}).fillna(runs["status"])
    fig = go.Figure(
        go.Bar(
            x=runs["started_msk"],
            y=runs["queries_ok"].fillna(0),
            marker={"color": color, "cornerradius": 4},
            width=1000 * 60 * 25,  # 25 минут в миллисекундах — столбцы не слипаются при часовом шаге
            customdata=list(zip(runs["run_id"], label, runs["queries_total"].fillna(0).astype(int), runs["items_total"].fillna(0).astype(int))),
            hovertemplate=(
                "Сбор #%{customdata[0]} — %{customdata[1]}<br>"
                "Запросов: %{y} из %{customdata[2]} · товаров: %{customdata[3]:,}<extra></extra>"
            ),
        )
    )
    _base_layout(fig, dark, 220)
    fig.update_layout(margin={"l": 6, "r": 6, "t": 10, "b": 6}, bargap=0.3, separators=", ")
    fig.update_yaxes(title=None, rangemode="tozero", dtick=10)
    fig.update_xaxes(title=None, tickformat="%H:%M\n%d.%m", hoverformat="%d.%m.%Y, %H:%M МСК")
    return fig
