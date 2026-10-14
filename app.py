"""Веб-интерфейс: динамика позиций товаров в поиске Wildberries.

Запуск:  streamlit run app.py
"""

from __future__ import annotations

import datetime as dt
import os
import tempfile
from pathlib import Path

import pandas as pd
import streamlit as st

from wb_serp import analytics as an
from wb_serp.charts import MAX_SERIES, PALETTE_DARK, PALETTE_LIGHT, position_chart
from wb_serp.images import image_url, load_routes
from wb_serp.config import MSK, ROOT_DIR
from wb_serp.remote import fetch_db

st.set_page_config(
    page_title="WB: позиции в поиске",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="collapsed",
)

LOCAL_DB = ROOT_DIR / "data" / "serp.db"
# Где брать базу, если локальной нет (например, на Streamlit Cloud): ветка data репозитория,
# которую каждый час обновляет GitHub Actions.
DEFAULT_DB_URL = "https://raw.githubusercontent.com/neldnermaksim/wb-serp-tracker/data/serp.db.xz"
REMOTE_DIR = Path(tempfile.gettempdir()) / "wb_serp"
REMOTE_TTL_SECONDS = 300

PERIODS = {"24 часа": dt.timedelta(hours=24), "3 дня": dt.timedelta(days=3), "7 дней": dt.timedelta(days=7), "Всё время": None}


# ---------------------------------------------------------------- источник данных
def _setting(name: str, default: str | None = None) -> str | None:
    if os.environ.get(name):
        return os.environ[name]
    try:
        return st.secrets.get(name, default)  # type: ignore[no-any-return]
    except Exception:  # noqa: BLE001 — secrets.toml может отсутствовать
        return default


@st.cache_resource(ttl=REMOTE_TTL_SECONDS, show_spinner="Загружаем свежие данные…")
def _download_db(url: str) -> str:
    # Раз в REMOTE_TTL_SECONDS проверяем, не появилась ли новая версия (по ETag).
    return str(fetch_db(url, REMOTE_DIR))


def resolve_db() -> tuple[str | None, str]:
    explicit = _setting("WB_DB_PATH")
    if explicit and Path(explicit).exists():
        return explicit, "локальный файл"
    if LOCAL_DB.exists():
        return str(LOCAL_DB), "локальный файл"
    url = _setting("WB_DB_URL", DEFAULT_DB_URL)
    try:
        path = _download_db(url)
        return path, "GitHub (обновляется каждый час)"
    except Exception as exc:  # noqa: BLE001
        cached = REMOTE_DIR / "serp.db"
        if cached.exists():
            st.warning(f"Не удалось обновить данные ({exc}). Показана последняя загруженная версия.")
            return str(cached), "кэш"
        return None, str(exc)


def db_version(path: str) -> str:
    """Ключ кэша: меняется, когда файл базы обновился."""
    stat = os.stat(path)
    return f"{path}|{stat.st_mtime_ns}|{stat.st_size}"


@st.cache_resource(max_entries=3)
def _conn(version: str):
    return an.connect_readonly(version.split("|")[0])


def conn(version: str):
    return _conn(version)


@st.cache_data(show_spinner=False)
def q_summary(version: str) -> dict:
    return an.db_summary(conn(version))


@st.cache_data(show_spinner=False)
def q_queries(version: str) -> pd.DataFrame:
    return an.queries_overview(conn(version))


@st.cache_data(show_spinner=False)
def q_collections(version: str, query_id: int) -> pd.DataFrame:
    return an.query_collections(conn(version), query_id)


@st.cache_data(show_spinner=False)
def q_products(version: str, query_id: int) -> pd.DataFrame:
    return an.products_for_query(conn(version), query_id)


@st.cache_data(show_spinner=False)
def q_history(version: str, query_id: int, nm_ids: tuple[int, ...]) -> pd.DataFrame:
    return an.position_history(conn(version), query_id, nm_ids)


@st.cache_data(show_spinner=False)
def q_latest(version: str, query_id: int, nm_ids: tuple[int, ...]) -> pd.DataFrame:
    return an.latest_characteristics(conn(version), query_id, nm_ids)


@st.cache_data(show_spinner=False)
def q_snapshot(version: str, query_id: int, run_id: int) -> pd.DataFrame:
    return an.snapshot(conn(version), query_id, run_id)


@st.cache_data(show_spinner=False)
def q_runs(version: str) -> pd.DataFrame:
    return an.runs_log(conn(version))


@st.cache_data(ttl=24 * 3600, show_spinner=False)
def image_routes() -> list:
    try:
        return load_routes()
    except Exception:  # noqa: BLE001 — без фото интерфейс тоже работает
        return []


def photos(nm_ids) -> list:
    routes = image_routes()
    return [image_url(nm, routes) if routes else None for nm in nm_ids]


# ---------------------------------------------------------------- форматирование
def fmt_ts(ts) -> str:
    if ts is None or pd.isna(ts):
        return "—"
    return pd.Timestamp(ts).tz_convert(MSK).strftime("%d.%m.%Y %H:%M")


def ago(ts) -> str:
    if ts is None or pd.isna(ts):
        return ""
    minutes = int((pd.Timestamp.now(tz=MSK) - pd.Timestamp(ts)).total_seconds() // 60)
    if minutes < 1:
        return "только что"
    if minutes < 60:
        return f"{minutes} мин назад"
    hours = minutes // 60
    if hours < 24:
        return f"{hours} ч {minutes % 60} мин назад"
    return f"{hours // 24} дн назад"


def fmt_int(value) -> str:
    if value is None or pd.isna(value):
        return "—"
    return f"{int(value):,}".replace(",", " ")


def plural(n, one: str, few: str, many: str) -> str:
    """«1 сбор», «3 сбора», «11 сборов»."""
    n = abs(int(n))
    if n % 10 == 1 and n % 100 != 11:
        word = one
    elif 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        word = few
    else:
        word = many
    return f"{fmt_int(n)} {word}"


def short(text, limit: int = 38) -> str:
    if not isinstance(text, str) or not text:
        return ""
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def change_label(change, is_new: bool = False) -> str:
    if is_new:
        return "новый"
    if change is None or pd.isna(change):
        return ""
    change = int(change)
    if change > 0:
        return f"▲ {change}"
    if change < 0:
        return f"▼ {-change}"
    return "="


def style_changes(df: pd.DataFrame, column: str):
    def color(value: str) -> str:
        if isinstance(value, str) and value.startswith("▲"):
            return "color: #0f8a3c; font-weight: 600"
        if isinstance(value, str) and value.startswith("▼"):
            return "color: #d03b3b; font-weight: 600"
        if value == "новый":
            return "color: #2a78d6; font-weight: 600"
        return "color: #8a8a8a"

    return df.style.map(color, subset=[column])


# Значок в таблице повторяет маркер линии на графике (тот же цвет и форма).
MARKER_GLYPHS = ["●", "■", "◆", "▲", "✕", "▼", "⬟", "★"]


def product_label(row) -> str:
    """Подпись товара в списке выбора: «ID · бренд · #позиция» — коротко, чтобы влезала в «чип»."""
    parts = [str(int(row.nm_id))]
    if isinstance(row.brand, str) and row.brand:
        parts.append(short(row.brand, 16))
    if pd.notna(row.last_position):
        parts.append(f"#{int(row.last_position)}")
    else:
        parts.append(f"был #{int(row.best_position)}")
    return " · ".join(parts)


# ---------------------------------------------------------------- стили
st.markdown(
    """
    <style>
      .block-container {padding-top: 1.6rem; padding-bottom: 3rem; max-width: 1400px;}
      h1 {font-size: 1.85rem !important; margin-bottom: 0 !important;}
      .subtitle {color: var(--text-color); opacity: .68; font-size: .95rem; margin: .1rem 0 1rem 0;}
      .pill {display: inline-block; padding: .12rem .55rem; border-radius: 999px; font-size: .8rem;
             background: rgba(128,128,128,.12); margin-right: .35rem;}
      .pill.ok {background: rgba(15,138,60,.14); color: var(--ok-color);}
      .pill.warn {background: rgba(237,161,0,.18); color: var(--warn-color);}
      div[data-testid="stMetricValue"] {font-size: 1.55rem;}
      div[data-testid="stMetricLabel"] p {font-size: .85rem; opacity: .75;}
      .hint {font-size: .85rem; opacity: .7;}
    </style>
    """,
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------- данные
db_path, source = resolve_db()
if not db_path:
    st.title("Позиции товаров в поиске Wildberries")
    st.error(f"База данных пока недоступна: {source}")
    st.stop()

version = db_version(db_path)
summary = q_summary(version)
queries = q_queries(version)
queries = queries[queries["is_active"] == 1].reset_index(drop=True)

if not summary["runs"]:
    st.title("Позиции товаров в поиске Wildberries")
    st.info("В базе ещё нет ни одного сбора. Запустите `python -m wb_serp.collect`.")
    st.stop()

dark = getattr(getattr(st.context, "theme", None), "type", "light") == "dark"
top_n = int(summary["top_n"] or 200)
last_run = summary["last_run_msk"]

# Цвета статусов подбираются под тему, чтобы текст оставался контрастным.
st.markdown(
    f"<style>:root {{--ok-color: {'#5cd68a' if dark else '#0f7a35'}; --warn-color: {'#f0b429' if dark else '#8a5a00'};}}</style>",
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------- шапка
st.title("Позиции товаров в поиске Wildberries")
status_class = "ok" if last_run is not None and ago(last_run).endswith(("мин назад", "только что")) else "warn"
st.markdown(
    f"""<div class="subtitle">
      <span class="pill">📍 {summary['city']} (центр)</span>
      <span class="pill">🔝 топ-{top_n}</span>
      <span class="pill">⏱ сбор каждый час</span>
      <span class="pill {status_class}">последний сбор: {fmt_ts(last_run)} МСК · {ago(last_run)}</span>
      <span class="pill">{plural(summary['runs'], 'сбор', 'сбора', 'сборов')} · {plural(summary['observations'], 'наблюдение', 'наблюдения', 'наблюдений')}</span>
    </div>""",
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------- фильтры (одна строка над всем остальным)
query_ids = queries["query_id"].tolist()
query_text = dict(zip(queries["query_id"], queries["text"]))
query_order = dict(zip(queries["query_id"], queries["sort_order"]))

c_query, c_period = st.columns([3, 2], vertical_alignment="bottom")
with c_query:
    if "query_id" not in st.session_state or st.session_state["query_id"] not in query_ids:
        st.session_state["query_id"] = query_ids[0]
    query_id = st.selectbox(
        "Поисковый запрос",
        query_ids,
        key="query_id",
        format_func=lambda qid: f"{query_order[qid]}. {query_text[qid]}",
        help="70 запросов из ТЗ в исходных формулировках. Можно начать печатать для поиска.",
    )
with c_period:
    period_name = st.segmented_control(
        "Период", list(PERIODS), default="Всё время", key="period", selection_mode="single"
    ) or "Всё время"

collections = q_collections(version, query_id)
products = q_products(version, query_id)

if collections.empty:
    st.warning("По этому запросу ещё нет успешных сборов.")
    st.stop()

latest = collections.iloc[-1]
k1, k2, k3, k4 = st.columns(4)
k1.metric("Сборов по запросу", fmt_int(len(collections)), help="Сколько раз выдача по запросу была успешно собрана")
k2.metric("Товаров за всё время", fmt_int(len(products)), help="Уникальные nm_id, хоть раз попадавшие в топ")
k3.metric("Всего товаров у WB", fmt_int(latest["wb_total"]), help="Сколько товаров WB нашёл по запросу в последнем сборе")
k4.metric("Последний сбор запроса", fmt_ts(latest["collected_msk"]), help="Московское время")

tab_chart, tab_serp, tab_runs, tab_about = st.tabs(
    ["📈 Динамика позиций", "📋 Выдача целиком", "🗂 Журнал сборов", "ℹ️ Как это работает"]
)

# ---------------------------------------------------------------- выбор товаров
sel_key = f"selected_{query_id}"
slot_key = f"slots_{query_id}"
labels_all = {int(r.nm_id): product_label(r) for r in products.itertuples()}
in_latest = products[products["last_position"].notna()].sort_values("last_position")["nm_id"].astype(int).tolist()

if sel_key not in st.session_state:
    st.session_state[sel_key] = in_latest[:5] or list(labels_all)[:5]
# Если товар пропал из справочника (другая база) — убираем из выбора.
st.session_state[sel_key] = [x for x in st.session_state[sel_key] if x in labels_all][:MAX_SERIES]


QUICK_PICKS = {"Топ-3": 3, "Топ-5": 5, "Топ-8": 8, "Очистить": 0}


def apply_quick_pick(widget_key: str) -> None:
    choice = st.session_state.get(widget_key)
    if choice in QUICK_PICKS:
        st.session_state[sel_key] = in_latest[: QUICK_PICKS[choice]]
    st.session_state[widget_key] = None  # кнопка-«таблетка» не остаётся нажатой


def add_to_selection(nm_ids: list[int]) -> None:
    merged = list(dict.fromkeys([*st.session_state[sel_key], *nm_ids]))
    st.session_state[sel_key] = merged[:MAX_SERIES]


def assign_slots(selected: list[int]) -> dict[int, int]:
    """Цвет закрепляется за товаром, а не за его местом в списке, — при изменении выбора не «перекрашивается»."""
    slots: dict[int, int] = {k: v for k, v in st.session_state.get(slot_key, {}).items() if k in selected}
    for nm in selected:
        if nm not in slots:
            free = [s for s in range(MAX_SERIES) if s not in slots.values()]
            slots[nm] = free[0] if free else 0
    st.session_state[slot_key] = slots
    return slots


# ---------------------------------------------------------------- вкладка: график
with tab_chart:
    c_sel, c_quick = st.columns([4, 2], vertical_alignment="bottom")
    with c_sel:
        selected = st.multiselect(
            f"Товары (ID) — до {MAX_SERIES} одновременно",
            options=list(labels_all),
            key=sel_key,
            format_func=lambda nm: labels_all.get(nm, str(nm)),
            max_selections=MAX_SERIES,
            placeholder="Начните вводить ID или бренд…",
            help="В списке все товары, когда-либо найденные по этому запросу. "
            "Сначала идут товары из последней выдачи по порядку позиций.",
        )
    with c_quick:
        st.pills(
            "Быстрый выбор",
            list(QUICK_PICKS),
            key=f"quick_{query_id}",
            on_change=apply_quick_pick,
            args=(f"quick_{query_id}",),
            help="Товары с первых мест последнего сбора",
        )

    if not selected:
        st.info("Выберите один или несколько товаров, чтобы увидеть, как менялись их позиции.")
    else:
        slots = assign_slots(selected)
        history = q_history(version, query_id, tuple(selected))
        period = PERIODS[period_name]
        if period is not None:
            history = history[history["collected_msk"] >= pd.Timestamp.now(tz=MSK) - period]

        prod_info = products.set_index("nm_id")
        legend = {}
        for nm in selected:
            brand = prod_info.at[nm, "brand"] if nm in prod_info.index else None
            legend[nm] = f"{nm} · {short(brand, 18)}" if isinstance(brand, str) and brand else str(nm)

        full_depth = st.toggle(
            f"Показывать всю глубину топ-{top_n}",
            value=False,
            help="Выключено — масштаб по данным выбранных товаров. Включено — шкала от 1 до глубины сбора.",
        )
        if history.empty:
            st.info("За выбранный период сборов не было — выберите период побольше.")
        else:
            fig = position_chart(history, legend, slots, top_n=top_n, full_depth=full_depth, dark=dark)
            st.plotly_chart(
                fig,
                width="stretch",
                config={"displaylogo": False, "locale": "ru", "modeBarButtonsToRemove": ["select2d", "lasso2d"]},
            )
            missing = history.groupby("nm_id")["found"].agg(lambda s: int((~s).sum()))
            n_points = history["run_id"].nunique()
            st.markdown(
                f"<div class='hint'>Позиция 1 — вверху. Точка — один сбор ({n_points} за период). "
                "<b>Разрыв линии</b> — в этом сборе товара не было в топе: позиция не выдумывается и не "
                "достраивается. Наведите курсор, чтобы увидеть дату, ID и позицию; выделите область, чтобы "
                "приблизить, двойной клик — сбросить масштаб.</div>",
                unsafe_allow_html=True,
            )
            gaps = [f"{nm}: не найден в {int(m)} из {n_points}" for nm, m in missing.items() if m]
            if gaps:
                st.caption("Пропуски за период — " + "; ".join(gaps))

        st.subheader("Характеристики выбранных товаров", anchor=False)
        latest_df = q_latest(version, query_id, tuple(selected))
        if not latest_df.empty:
            palette = PALETTE_DARK if dark else PALETTE_LIGHT
            key_glyph = [MARKER_GLYPHS[slots[nm] % MAX_SERIES] for nm in latest_df["nm_id"]]
            key_color = {i: palette[slots[nm] % MAX_SERIES] for i, nm in enumerate(latest_df["nm_id"])}
            table = pd.DataFrame(
                {
                    "Линия": key_glyph,
                    "Фото": photos(latest_df["nm_id"]),
                    "Товар": latest_df["url"],
                    "Название": latest_df["name"],
                    "Бренд": latest_df["brand"],
                    "Продавец": latest_df["supplier"],
                    "Позиция": latest_df["last_position"],
                    "Изм.": [
                        change_label(p - c) if pd.notna(p) else ""
                        for p, c in zip(latest_df["prev_seen_position"], latest_df["last_position"])
                    ],
                    "Лучшая": latest_df["best_position"],
                    "Цена, ₽": latest_df["price_rub"],
                    "Рейтинг": latest_df["rating"],
                    "Отзывы": latest_df["feedbacks"],
                    "Доставка, дн.": latest_df["delivery_days"],
                    "Данные на": [
                        fmt_ts(t) + ("" if fresh else " · нет в последней выдаче")
                        for t, fresh in zip(latest_df["last_seen_msk"], latest_df["in_latest"])
                    ],
                }
            )
            styled = style_changes(table, "Изм.").apply(
                lambda col: [f"color: {key_color[i]}; font-size: 1.1rem" for i in range(len(col))], subset=["Линия"]
            )
            st.dataframe(
                styled,
                hide_index=True,
                width="stretch",
                column_config={
                    "Линия": st.column_config.TextColumn("", width=36, help="Цвет и форма маркера на графике"),
                    "Фото": st.column_config.ImageColumn("Фото", width="small"),
                    "Товар": st.column_config.LinkColumn(
                        "ID товара",
                        display_text=r"https://www\.wildberries\.ru/catalog/(\d+)/detail\.aspx",
                        help="nm_id; ссылка открывает карточку на wildberries.ru",
                    ),
                    "Название": st.column_config.TextColumn(width="medium"),
                    "Продавец": st.column_config.TextColumn(width="small"),
                    "Бренд": st.column_config.TextColumn(width="small"),
                    "Позиция": st.column_config.NumberColumn(format="%d", help="Место в последнем сборе, где товар был найден"),
                    "Изм.": st.column_config.TextColumn(help="Изменение позиции к предыдущему сбору, где товар тоже был"),
                    "Лучшая": st.column_config.NumberColumn(format="%d", help="Лучшая позиция за всё время"),
                    "Цена, ₽": st.column_config.NumberColumn(format="%d ₽", help="Цена для покупателя со всеми скидками"),
                    "Рейтинг": st.column_config.NumberColumn(format="★ %.1f", help="Пусто — у товара ещё нет оценок"),
                    "Отзывы": st.column_config.NumberColumn(format="localized", help="Количество оценок"),
                    "Доставка, дн.": st.column_config.NumberColumn(
                        format="%d", help="Календарных дней до доставки в Москву: сегодня — 0, завтра — 1"
                    ),
                },
            )

        with st.expander("Все наблюдения выбранных товаров"):
            obs = q_history(version, query_id, tuple(selected))
            obs = obs[obs["found"]].sort_values(["collected_msk", "position"], ascending=[False, True])
            export = pd.DataFrame(
                {
                    "Запрос": query_text[query_id],
                    "Дата и время сбора (МСК)": obs["collected_msk"].dt.strftime("%d.%m.%Y %H:%M"),
                    "Позиция": obs["position"].astype(int),
                    "ID товара": obs["nm_id"],
                    "Цена, ₽": obs["price_rub"],
                    "Рейтинг": obs["rating"],
                    "Отзывы": obs["feedbacks"],
                    "Доставка, дн.": obs["delivery_days"],
                    "Продавец": obs["nm_id"].map(prod_info["supplier"]),
                }
            )
            st.dataframe(
                export,
                hide_index=True,
                width="stretch",
                column_config={
                    "ID товара": st.column_config.NumberColumn(format="%d"),
                    "Цена, ₽": st.column_config.NumberColumn(format="%d ₽"),
                    "Рейтинг": st.column_config.NumberColumn(format="%.1f"),
                },
            )
            st.download_button(
                "Скачать CSV",
                export.to_csv(index=False).encode("utf-8-sig"),
                file_name=f"wb_positions_{query_id}.csv",
                mime="text/csv",
            )

# ---------------------------------------------------------------- вкладка: выдача целиком
with tab_serp:
    runs_desc = collections.sort_values("collected_msk", ascending=False)
    c_run, c_search = st.columns([2, 3], vertical_alignment="bottom")
    with c_run:
        run_id = st.selectbox(
            "Сбор",
            runs_desc["run_id"].tolist(),
            format_func=lambda rid: (
                f"{fmt_ts(runs_desc.set_index('run_id').at[rid, 'collected_msk'])} МСК · "
                f"{plural(runs_desc.set_index('run_id').at[rid, 'items'], 'товар', 'товара', 'товаров')}"
            ),
            key=f"serp_run_{query_id}",
        )
    with c_search:
        needle = st.text_input("Фильтр", placeholder="ID, название, бренд или продавец", key=f"serp_filter_{query_id}")

    snap = q_snapshot(version, query_id, int(run_id))
    if needle:
        hay = (
            snap["nm_id"].astype(str) + " " + snap["name"].fillna("") + " " + snap["brand"].fillna("") + " " + snap["supplier"].fillna("")
        ).str.lower()
        snap = snap[hay.str.contains(needle.lower(), regex=False)]

    serp_table = pd.DataFrame(
        {
            "Позиция": snap["position"],
            "Изм.": [change_label(c, n) for c, n in zip(snap["change"], snap["is_new"])],
            "Фото": photos(snap["nm_id"]),
            "Товар": snap["url"],
            "Название": snap["name"],
            "Бренд": snap["brand"],
            "Продавец": snap["supplier"],
            "Цена, ₽": snap["price_rub"],
            "Рейтинг": snap["rating"],
            "Отзывы": snap["feedbacks"],
            "Доставка, дн.": snap["delivery_days"],
        }
    )
    event = st.dataframe(
        style_changes(serp_table, "Изм."),
        hide_index=True,
        width="stretch",
        height=560,
        on_select="rerun",
        selection_mode="multi-row",
        key=f"serp_table_{query_id}_{run_id}",
        column_config={
            "Позиция": st.column_config.NumberColumn(format="%d", width="small"),
            "Изм.": st.column_config.TextColumn(width="small", help="Изменение к предыдущему сбору; «новый» — в прошлый раз товара в топе не было"),
            "Фото": st.column_config.ImageColumn("Фото", width="small"),
            "Товар": st.column_config.LinkColumn(
                "ID товара", display_text=r"https://www\.wildberries\.ru/catalog/(\d+)/detail\.aspx"
            ),
            "Название": st.column_config.TextColumn(width="large"),
            "Цена, ₽": st.column_config.NumberColumn(format="%d ₽"),
            "Рейтинг": st.column_config.NumberColumn(format="★ %.1f"),
            "Отзывы": st.column_config.NumberColumn(format="localized"),
            "Доставка, дн.": st.column_config.NumberColumn(format="%d", help="Сегодня — 0, завтра — 1"),
        },
    )
    chosen = [int(snap.iloc[i]["nm_id"]) for i in event.selection.rows] if event and event.selection.rows else []
    c_info, c_btn = st.columns([3, 1], vertical_alignment="center")
    with c_info:
        st.markdown(
            "<div class='hint'>Отметьте строки слева, чтобы добавить товары на график "
            f"(до {MAX_SERIES} одновременно).</div>",
            unsafe_allow_html=True,
        )
    with c_btn:
        if st.button(
            f"Добавить на график ({len(chosen)})", disabled=not chosen, type="primary", width="stretch",
            on_click=add_to_selection, args=(chosen,),
        ):
            st.toast("Товары добавлены — откройте вкладку «Динамика позиций»", icon="📈")
    st.download_button(
        "Скачать выдачу CSV",
        serp_table.drop(columns="Фото").assign(**{"Товар": snap["nm_id"].values}).rename(columns={"Товар": "ID товара"}).to_csv(index=False).encode("utf-8-sig"),
        file_name=f"wb_serp_{query_id}_{run_id}.csv",
        mime="text/csv",
    )

# ---------------------------------------------------------------- вкладка: журнал сборов
with tab_runs:
    runs = q_runs(version)
    ok_runs = runs[runs["status"].isin(["ok", "partial"])]
    r1, r2, r3, r4 = st.columns(4)
    r1.metric("Всего сборов", fmt_int(len(runs)))
    r2.metric("Успешных", fmt_int((runs["status"] == "ok").sum()))
    r3.metric("Первый сбор", fmt_ts(summary["first_run_msk"]))
    r4.metric(
        "Средняя длительность",
        f"{ok_runs['duration_min'].mean():.1f} мин" if not ok_runs.empty else "—",
    )
    status_map = {"ok": "✅ успешно", "partial": "⚠️ частично", "failed": "❌ ошибка", "running": "⏳ идёт"}
    st.dataframe(
        pd.DataFrame(
            {
                "№": runs["run_id"],
                "Начало (МСК)": runs["started_msk"].dt.strftime("%d.%m.%Y %H:%M"),
                "Статус": runs["status"].map(status_map).fillna(runs["status"]),
                "Запросов собрано": [
                    f"{int(o) if pd.notna(o) else 0} из {int(t) if pd.notna(t) else 0}"
                    for o, t in zip(runs["queries_ok"], runs["queries_total"])
                ],
                "Товаров": runs["items_total"],
                "Длительность, мин": runs["duration_min"].round(1),
                "Глубина": runs["top_n"],
                "Где": runs["host"].map({"github-actions": "GitHub Actions", "local": "локально"}).fillna(runs["host"]),
                "Ошибка": runs["error"].fillna(""),
            }
        ),
        hide_index=True,
        width="stretch",
        column_config={"Товаров": st.column_config.NumberColumn(format="localized")},
    )
    st.caption(
        f"Источник данных: {source}. В базе {plural(summary['observations'], 'наблюдение', 'наблюдения', 'наблюдений')}, "
        f"{plural(summary['products'], 'товар', 'товара', 'товаров')}."
    )

# ---------------------------------------------------------------- вкладка: как это работает
with tab_about:
    st.markdown(
        f"""
**Что собирается.** Каждый час сборщик открывает поиск Wildberries по каждому из 70 запросов
(формулировки — как в исходной таблице) и сохраняет первые **{top_n}** товаров в том порядке,
в каком их показывает сайт (сортировка «по популярности»). Город доставки фиксирован —
**{summary['city']}, центр** (код WB `dest={summary['dest']}`), чтобы сроки и выдача были сопоставимы.

**Поля каждого наблюдения**

| Поле | Что это |
|---|---|
| Запрос, дата и время | исходная формулировка и момент получения выдачи (МСК) |
| Позиция | место в выдаче, 1 — первое |
| ID товара | артикул WB (nm_id) |
| Цена | цена для покупателя со всеми скидками, ₽ (без учёта WB Кошелька — её API не отдаёт) |
| Рейтинг, отзывы | как на карточке: «4,8 · 15 575 оценок»; у товара без оценок рейтинг пустой |
| Доставка | календарных дней до доставки в Москву: сегодня — 0, завтра — 1 |
| Продавец | название продавца (магазина), не бренд |

Если поле недоступно, сохраняется пустое значение — ничего не подставляется.

**Как читать график.** Ось позиций перевёрнута: 1 — вверху. Каждая точка — реальный сбор.
Если при очередном сборе товара не было в топ-{top_n}, линия прерывается — позиция не
придумывается. Сборы, завершившиеся ошибкой, на графике не участвуют.

**История не теряется.** Данные только добавляются: каждый сбор — новая запись, прошлые
наблюдения никогда не перезаписываются и не удаляются.
"""
    )
