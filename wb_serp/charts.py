"""График динамики позиций (Plotly)."""

from __future__ import annotations

import math
from typing import Mapping

import pandas as pd
import plotly.graph_objects as go

# Категориальная палитра: порядок слотов фиксирован и проверен на различимость
# при всех типах цветовой слепоты (соседние пары ΔE ≥ 8). Светлая и тёмная версии.
PALETTE_LIGHT = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"]
PALETTE_DARK = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"]
MAX_SERIES = len(PALETTE_LIGHT)
# Разные маркеры дублируют цвет — линии различимы и без цвета (печать, дальтонизм).
MARKERS = ["circle", "square", "diamond", "triangle-up", "x", "triangle-down", "pentagon", "star"]


def _fmt_price(value: float | None) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "цена —"
    return f"{value:,.0f} ₽".replace(",", " ")


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
    surface = "#0e1117" if dark else "#ffffff"
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
                line={"color": color, "width": 2},
                marker={
                    "color": color,
                    "size": 8,
                    "symbol": MARKERS[slot],
                    "line": {"color": surface, "width": 1.5},
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

    fig.update_layout(
        height=480,
        margin={"l": 8, "r": 8, "t": 8, "b": 8},
        hovermode="x unified",
        hoverlabel={"namelength": -1},
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.02, "xanchor": "left", "x": 0, "title": None},
        dragmode="zoom",
    )
    fig.update_yaxes(
        title="Позиция в выдаче (1 — вверху)",
        range=y_range,  # range «сверху вниз» = перевёрнутая ось
        zeroline=False,
        tickformat="d",
        gridcolor="rgba(128,128,128,0.18)",
    )
    times = history["collected_msk"].dropna().unique()
    if len(times) == 1:
        # Один сбор: без явного диапазона Plotly растягивает ось на секунды и дублирует подписи.
        only = pd.Timestamp(times[0])
        fig.update_xaxes(range=[only - pd.Timedelta(hours=1), only + pd.Timedelta(hours=1)])
    fig.update_xaxes(
        title=None,
        tickformat="%H:%M\n%d.%m",
        hoverformat="%d.%m.%Y %H:%M МСК",
        gridcolor="rgba(128,128,128,0.12)",
        showspikes=True,
        spikemode="across",
        spikethickness=1,
        spikedash="dot",
        spikecolor="rgba(128,128,128,0.6)",
    )
    return fig
