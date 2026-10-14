"""Веб-интерфейс: динамика позиций товаров в поиске Wildberries.

Запуск:  streamlit run app.py
"""

from __future__ import annotations

import datetime as dt
import os
from html import escape
import tempfile
from pathlib import Path

import pandas as pd
import streamlit as st

from wb_serp import analytics as an
from wb_serp import ui
from wb_serp.charts import MAX_SERIES, PALETTE_DARK, PALETTE_LIGHT, position_chart, runs_chart
from wb_serp.images import image_url, load_routes
from wb_serp.config import MSK, ROOT_DIR
from wb_serp.remote import fetch_db

st.set_page_config(
    page_title="WB · позиции в поиске",
    page_icon="🟣",
    layout="wide",
    initial_sidebar_state="collapsed",
)

LOCAL_DB = ROOT_DIR / "data" / "serp.db"
# Где брать базу, если локальной нет (например, на Streamlit Cloud): ветка data репозитория,
# которую каждый час обновляет GitHub Actions.
DEFAULT_DB_URL = "https://raw.githubusercontent.com/neldnermaksim/wb-serp-tracker/data/serp.db.xz"
REMOTE_DIR = Path(tempfile.gettempdir()) / "wb_serp"
REMOTE_TTL_SECONDS = 300

PERIODS = {"Сутки": dt.timedelta(hours=24), "3 дня": dt.timedelta(days=3), "Неделя": dt.timedelta(days=7), "Всё время": None}


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
def q_snapshot_summary(version: str, query_id: int, run_id: int) -> dict:
    return an.snapshot_summary(conn(version), query_id, run_id)


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


def style_changes(df: pd.DataFrame, column: str, t: ui.Tokens):
    def color(value: str) -> str:
        if isinstance(value, str) and value.startswith("▲"):
            return f"color: {t.ok}; font-weight: 700"
        if isinstance(value, str) and value.startswith("▼"):
            return f"color: {t.bad}; font-weight: 700"
        if value == "новый":
            return f"color: {t.new}; font-weight: 700"
        return f"color: {t.muted}"

    return df.style.map(color, subset=[column])


# Значок в таблице повторяет маркер линии на графике (тот же цвет и форма).
MARKER_GLYPHS = ["●", "■", "◆", "▲", "✕", "▼", "⬟", "★"]
WB_LINK = r"https://www\.wildberries\.ru/catalog/(\d+)/detail\.aspx"
REPO_URL = "https://github.com/neldnermaksim/wb-serp-tracker"


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


def mover_value(item: dict | None, up: bool) -> str:
    if not item:
        return "—"
    arrow, cls = ("▲", "up") if up else ("▼", "down")
    return f'<span class="{cls}">{arrow} {abs(item["change"])}</span> · #{item["position"]}'


def mover_sub(item: dict | None) -> str:
    if not item:
        return "без изменений"
    brand = f" · {short(item['brand'], 18)}" if isinstance(item.get("brand"), str) and item["brand"] else ""
    return f"ID {item['nm_id']}{brand}"


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

dark = getattr(getattr(st.context, "theme", None), "type", "light") == "dark"
tk = ui.tokens(dark)
st.markdown(ui.css(tk), unsafe_allow_html=True)

if not summary["runs"]:
    st.title("Позиции товаров в поиске Wildberries")
    st.info("В базе ещё нет ни одного сбора. Запустите `python -m wb_serp.collect`.")
    st.stop()

top_n = int(summary["top_n"] or 200)
last_run = summary["last_run_msk"]
fresh = last_run is not None and (pd.Timestamp.now(tz=MSK) - last_run) < pd.Timedelta(minutes=90)

# ---------------------------------------------------------------- шапка
when = ago(last_run)
st.markdown(
    ui.hero(
        title="Позиции товаров в поиске Wildberries",
        lead=f"{len(queries)} поисковых запросов · первые {top_n} товаров выдачи · история позиций по часам",
        chips=[
            f"Москва, центр",
            "Сбор каждый час",
            plural(summary["runs"], "сбор", "сбора", "сборов"),
            plural(summary["observations"], "наблюдение", "наблюдения", "наблюдений"),
        ],
        status_label="Данные свежие" if fresh else "Последнее обновление",
        status_big=when[:1].upper() + when[1:] if when else "—",
        status_sub=f"последний сбор {fmt_ts(last_run)} МСК",
        fresh=fresh,
    ),
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------- фильтры
query_ids = queries["query_id"].tolist()
query_text = dict(zip(queries["query_id"], queries["text"]))
query_order = dict(zip(queries["query_id"], queries["sort_order"]))

with st.container(key="card_filters"):
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
            "Период", list(PERIODS), default="Всё время", key="period", selection_mode="single", width="stretch"
        ) or "Всё время"

collections = q_collections(version, query_id)
products = q_products(version, query_id)
if collections.empty:
    st.warning("По этому запросу ещё нет успешных сборов.")
    st.stop()

latest = collections.iloc[-1]
first = collections.iloc[0]
st.markdown(
    ui.kpis(
        [
            ui.Kpi("Сборов по запросу", fmt_int(len(collections)), f"с {fmt_ts(first['collected_msk'])}", "refresh",
                   title="Сколько раз выдача по запросу была успешно собрана"),
            ui.Kpi("Товаров за всё время", fmt_int(len(products)), f"хоть раз в топ-{top_n}", "layers",
                   title="Уникальные nm_id, когда-либо попадавшие в собранную выдачу"),
            ui.Kpi("Найдено у WB", fmt_int(latest["wb_total"]), "товаров по запросу", "search",
                   title="Сколько всего товаров WB нашёл по запросу в последнем сборе"),
            ui.Kpi("Последний сбор", pd.Timestamp(latest["collected_msk"]).strftime("%H:%M"),
                   pd.Timestamp(latest["collected_msk"]).strftime("%d.%m.%Y, МСК"), "clock"),
        ]
    ),
    unsafe_allow_html=True,
)

tab_chart, tab_serp, tab_runs, tab_about = st.tabs(["Динамика позиций", "Выдача целиком", "Журнал сборов", "Как это работает"])

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


# ---------------------------------------------------------------- вкладка: динамика позиций
with tab_chart:
    with st.container(key="card_chart"):
        st.markdown(
            ui.section("Как менялись позиции", "1 — первое место · наведите на график: дата, ID и позиция"),
            unsafe_allow_html=True,
        )
        c_sel, c_quick = st.columns([3, 2], vertical_alignment="bottom")
        with c_sel:
            selected = st.multiselect(
                f"Товары (ID) — до {MAX_SERIES} одновременно",
                options=list(labels_all),
                key=sel_key,
                format_func=lambda nm: labels_all.get(nm, str(nm)),
                max_selections=MAX_SERIES,
                placeholder="Начните вводить ID или бренд…",
                help="Все товары, когда-либо найденные по этому запросу. "
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
            st.info("Выберите один или несколько товаров — здесь появится график их позиций.")
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
                f"Вся глубина топ-{top_n}",
                value=False,
                help="Выключено — масштаб по выбранным товарам. Включено — шкала от 1 до глубины сбора.",
            )
            if history.empty:
                st.info("За выбранный период сборов не было — выберите период побольше.")
            else:
                fig = position_chart(history, legend, slots, top_n=top_n, full_depth=full_depth, dark=dark)
                st.plotly_chart(fig, width="stretch", theme=None, config={"displayModeBar": False, "locale": "ru"})
                n_points = history["run_id"].nunique()
                missing = history.groupby("nm_id")["found"].agg(lambda s: int((~s).sum()))
                gaps = [f"{nm} — нет в {int(m)} из {n_points}" for nm, m in missing.items() if m]
                gaps_html = f"<br>Пропуски за период: {escape('; '.join(gaps))}." if gaps else ""
                st.markdown(
                    f"<div class='wb-note'>Точка — один сбор ({plural(n_points, 'сбор', 'сбора', 'сборов')} за период). "
                    "<b>Разрыв линии</b> — в этом сборе товара не было в топе: позиция не выдумывается и не достраивается. "
                    "Выделите область, чтобы приблизить, двойной клик — сбросить; клик по легенде скрывает линию."
                    f"{gaps_html}</div>",
                    unsafe_allow_html=True,
                )

    if selected:
        with st.container(key="card_table"):
            st.markdown(
                ui.section("Характеристики выбранных товаров", "последние известные значения в выдаче по запросу"),
                unsafe_allow_html=True,
            )
            latest_df = q_latest(version, query_id, tuple(selected))
            if not latest_df.empty:
                palette = PALETTE_DARK if dark else PALETTE_LIGHT
                key_color = {i: palette[slots[nm] % MAX_SERIES] for i, nm in enumerate(latest_df["nm_id"])}
                table = pd.DataFrame(
                    {
                        "Линия": [MARKER_GLYPHS[slots[nm] % MAX_SERIES] for nm in latest_df["nm_id"]],
                        "Фото": photos(latest_df["nm_id"]),
                        "Товар": latest_df["url"],
                        "Название": latest_df["name"],
                        "Продавец": latest_df["supplier"],
                        "Позиция": latest_df["last_position"],
                        "Изм.": [
                            change_label(p - c) if pd.notna(p) else ""
                            for p, c in zip(latest_df["prev_seen_position"], latest_df["last_position"])
                        ],
                        "Лучшая": latest_df["best_position"],
                        "Цена": latest_df["price_rub"],
                        "Рейтинг": latest_df["rating"],
                        "Отзывы": latest_df["feedbacks"],
                        "Доставка": latest_df["delivery_days"],
                        "Данные на": [
                            fmt_ts(t) + ("" if fresh_row else " · нет в последней выдаче")
                            for t, fresh_row in zip(latest_df["last_seen_msk"], latest_df["in_latest"])
                        ],
                    }
                )
                styled = style_changes(table, "Изм.", tk).apply(
                    lambda col: [f"color: {key_color[i]}; font-size: 1.1rem" for i in range(len(col))], subset=["Линия"]
                )
                st.dataframe(
                    styled,
                    hide_index=True,
                    width="stretch",
                    row_height=52,
                    column_config={
                        "Линия": st.column_config.TextColumn("", width=34, help="Цвет и форма маркера на графике"),
                        "Фото": st.column_config.ImageColumn("", width=48),
                        "Товар": st.column_config.LinkColumn(
                            "ID товара", display_text=WB_LINK, help="nm_id; ссылка открывает карточку на wildberries.ru"
                        ),
                        "Название": st.column_config.TextColumn(width="medium"),
                        "Продавец": st.column_config.TextColumn(width="small"),
                        "Позиция": st.column_config.NumberColumn(format="%d", help="Место в последнем сборе, где товар был найден"),
                        "Изм.": st.column_config.TextColumn(help="Изменение к предыдущему сбору, где товар тоже был"),
                        "Лучшая": st.column_config.NumberColumn(format="%d", help="Лучшая позиция за всё время"),
                        "Цена": st.column_config.NumberColumn(format="%d ₽", help="Цена для покупателя со всеми скидками"),
                        "Рейтинг": st.column_config.NumberColumn(format="★ %.1f", help="Пусто — у товара ещё нет оценок"),
                        "Отзывы": st.column_config.NumberColumn(format="localized", help="Количество оценок"),
                        "Доставка": st.column_config.NumberColumn(
                            format="%d дн.", help="Календарных дней до доставки в Москву: сегодня — 0, завтра — 1"
                        ),
                    },
                )

            with st.expander("Все наблюдения выбранных товаров и выгрузка в CSV"):
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
                    icon=":material/download:",
                )

# ---------------------------------------------------------------- вкладка: выдача целиком
with tab_serp:
    runs_desc = collections.sort_values("collected_msk", ascending=False).set_index("run_id")
    run_ids = runs_desc.index.tolist()
    run_key = f"serp_run_{query_id}"
    if st.session_state.get(run_key) not in run_ids:
        st.session_state[run_key] = run_ids[0]
    current_run = st.session_state[run_key]
    moves = q_snapshot_summary(version, query_id, int(current_run))
    has_prev = moves["prev_run_id"] is not None
    st.markdown(
        ui.kpis(
            [
                ui.Kpi("Новые в топе", fmt_int(moves["new"]) if has_prev else "—", "к прошлому сбору", "plus", "new",
                       title="Товары, которых не было в топе при предыдущем сборе"),
                ui.Kpi("Выбыли из топа", fmt_int(moves["dropped"]) if has_prev else "—", "к прошлому сбору", "minus", "bad",
                       title="Товары, которые были в топе при предыдущем сборе, а теперь нет"),
                ui.Kpi("Сильнее всех вырос", mover_value(moves["riser"], True), mover_sub(moves["riser"]), "trend_up", "ok", value_html=True),
                ui.Kpi("Сильнее всех упал", mover_value(moves["faller"], False), mover_sub(moves["faller"]), "trend_down", "bad", value_html=True),
            ]
        ),
        unsafe_allow_html=True,
    )

    with st.container(key="card_serp"):
        st.markdown(ui.section("Выдача целиком", "отметьте строки, чтобы добавить товары на график"), unsafe_allow_html=True)
        c_run, c_search = st.columns([2, 3], vertical_alignment="bottom")
        with c_run:
            run_id = st.selectbox(
                "Сбор",
                run_ids,
                format_func=lambda rid: (
                    f"{fmt_ts(runs_desc.at[rid, 'collected_msk'])} МСК · "
                    f"{plural(runs_desc.at[rid, 'items'], 'товар', 'товара', 'товаров')}"
                ),
                key=run_key,
            )
        with c_search:
            needle = st.text_input(
                "Поиск по выдаче", placeholder="ID, название, бренд или продавец", key=f"serp_filter_{query_id}",
                icon=":material/search:",
            )

        snap = q_snapshot(version, query_id, int(run_id))
        if needle:
            hay = (
                snap["nm_id"].astype(str) + " " + snap["name"].fillna("") + " " + snap["brand"].fillna("")
                + " " + snap["supplier"].fillna("")
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
                "Цена": snap["price_rub"],
                "Рейтинг": snap["rating"],
                "Отзывы": snap["feedbacks"],
                "Доставка": snap["delivery_days"],
            }
        )
        event = st.dataframe(
            style_changes(serp_table, "Изм.", tk),
            hide_index=True,
            width="stretch",
            height=600,
            row_height=52,
            on_select="rerun",
            selection_mode="multi-row",
            key=f"serp_table_{query_id}_{run_id}",
            column_config={
                "Позиция": st.column_config.NumberColumn("№", format="%d", width=56),
                "Изм.": st.column_config.TextColumn(width=72, help="Изменение к предыдущему сбору; «новый» — в прошлый раз товара в топе не было"),
                "Фото": st.column_config.ImageColumn("", width=48),
                "Товар": st.column_config.LinkColumn("ID товара", display_text=WB_LINK),
                "Название": st.column_config.TextColumn(width="medium"),
                "Бренд": st.column_config.TextColumn(width="small"),
                "Продавец": st.column_config.TextColumn(width="small"),
                "Цена": st.column_config.NumberColumn(format="%d ₽"),
                "Рейтинг": st.column_config.NumberColumn(format="★ %.1f"),
                "Отзывы": st.column_config.NumberColumn(format="localized"),
                "Доставка": st.column_config.NumberColumn(format="%d дн.", help="Сегодня — 0, завтра — 1"),
            },
        )
        chosen = [int(snap.iloc[i]["nm_id"]) for i in event.selection.rows] if event and event.selection.rows else []
        c_add, c_csv, _ = st.columns([2, 2, 3])
        with c_add:
            if st.button(
                f"Показать на графике ({len(chosen)})", disabled=not chosen, type="primary", width="stretch",
                on_click=add_to_selection, args=(chosen,), icon=":material/show_chart:",
            ):
                st.toast("Товары добавлены — откройте вкладку «Динамика позиций»", icon="📈")
        with c_csv:
            st.download_button(
                "Скачать выдачу CSV",
                serp_table.drop(columns="Фото").assign(**{"Товар": snap["nm_id"].values}).rename(columns={"Товар": "ID товара"})
                .to_csv(index=False).encode("utf-8-sig"),
                file_name=f"wb_serp_{query_id}_{run_id}.csv",
                mime="text/csv",
                width="stretch",
                icon=":material/download:",
            )

# ---------------------------------------------------------------- вкладка: журнал сборов
with tab_runs:
    runs = q_runs(version)
    ok_runs = runs[runs["status"].isin(["ok", "partial"])]
    ok_share = (runs["status"] == "ok").mean() if len(runs) else 0
    st.markdown(
        ui.kpis(
            [
                ui.Kpi("Всего сборов", fmt_int(len(runs)), f"с {fmt_ts(summary['first_run_msk'])}", "calendar"),
                ui.Kpi("Успешных", fmt_int((runs["status"] == "ok").sum()), f"{ok_share:.0%} — все 70 запросов", "check", "ok"),
                ui.Kpi("Последний сбор", ago(last_run) or "—", f"{fmt_ts(last_run)} МСК", "clock"),
                ui.Kpi(
                    "Длительность сбора",
                    f"{ok_runs['duration_min'].mean():.1f} мин" if not ok_runs.empty else "—",
                    "в среднем, 140 запросов к WB",
                    "timer",
                ),
            ]
        ),
        unsafe_allow_html=True,
    )
    with st.container(key="card_runs_chart"):
        st.markdown(
            ui.section("Лента сборов", "столбец — один запуск, высота — сколько из 70 запросов собрано"),
            unsafe_allow_html=True,
        )
        st.plotly_chart(runs_chart(runs, dark=dark), width="stretch", theme=None, config={"displayModeBar": False, "locale": "ru"})
    with st.container(key="card_runs_table"):
        st.markdown(ui.section("Все запуски"), unsafe_allow_html=True)
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
                    "Длительность": runs["duration_min"].round(1),
                    "Глубина": runs["top_n"],
                    "Где": runs["host"].map({"github-actions": "GitHub Actions", "local": "локально"}).fillna(runs["host"]),
                    "Ошибка": runs["error"].fillna(""),
                }
            ),
            hide_index=True,
            width="stretch",
            column_config={
                "Товаров": st.column_config.NumberColumn(format="localized"),
                "Длительность": st.column_config.NumberColumn(format="%.1f мин"),
            },
        )
        st.markdown(
            f"<div class='wb-note'>Источник данных: {escape(source)}. В базе "
            f"{plural(summary['observations'], 'наблюдение', 'наблюдения', 'наблюдений')}, "
            f"{plural(summary['products'], 'товар', 'товара', 'товаров')}.</div>",
            unsafe_allow_html=True,
        )

# ---------------------------------------------------------------- вкладка: как это работает
with tab_about:
    with st.container(key="card_about"):
        st.markdown(
            f"""
#### Что собирается
Каждый час сборщик открывает поиск Wildberries по каждому из {len(queries)} запросов (формулировки — как в
исходной таблице) и сохраняет первые **{top_n}** товаров в том порядке, в каком их показывает сайт
(сортировка «по популярности»). Город доставки фиксирован — **{summary['city']}, центр**
(код WB `dest={summary['dest']}`), чтобы выдача и сроки были сопоставимы.

#### Поля каждого наблюдения

| Поле | Что это |
|---|---|
| Запрос, дата и время | исходная формулировка и момент получения выдачи (МСК) |
| Позиция | место в выдаче, 1 — первое |
| ID товара | артикул WB (nm_id) |
| Цена | цена для покупателя со всеми скидками, ₽ (без «WB Кошелька» — её API не отдаёт) |
| Рейтинг, отзывы | как на карточке: «4,8 · 15 575 оценок»; у товара без оценок рейтинг пустой |
| Доставка | календарных дней до доставки в Москву: сегодня — 0, завтра — 1 |
| Продавец | название продавца (магазина), не бренд |

Если поле недоступно, сохраняется пустое значение — ничего не подставляется.

#### Как читать график
Ось позиций перевёрнута: 1 — вверху. Каждая точка — реальный сбор. Если при очередном сборе товара не
было в топ-{top_n}, линия прерывается — позиция не придумывается. Сборы, завершившиеся ошибкой, не учитываются.

#### Точность
Поля сверены с карточками на сайте: срок доставки, рейтинг, число оценок и цена совпали на 100% из 510 карточек.
Порядок выдачи совпадает с тем, что видит новый покупатель на сайте с адресом «Москва, центр».

#### История не теряется
Данные только добавляются: каждый сбор — новая запись, прошлые наблюдения никогда не перезаписываются и не удаляются.
"""
        )

st.markdown(
    f"""<div class="wb-footer">Данные — поисковая выдача wildberries.ru, собираются автоматически каждый час ·
    <a href="{REPO_URL}" target="_blank">исходный код на GitHub</a></div>""",
    unsafe_allow_html=True,
)
