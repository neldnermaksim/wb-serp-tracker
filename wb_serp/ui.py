"""Оформление веб-интерфейса: цвета, стили и HTML-блоки (шапка, карточки показателей)."""

from __future__ import annotations

from dataclasses import dataclass
from html import escape

# Фирменный градиент шапки wildberries.ru (снят с сайта).
WB_GRADIENT = (
    "linear-gradient(97deg, #ed3cca 0%, #d02bd9 29%, #ae1ae8 57%, #8306f7 85%, #7c1af8 100%)"
)


@dataclass(frozen=True)
class Tokens:
    bg: str
    card: str
    card_border: str
    shadow: str
    text: str
    muted: str
    accent: str
    accent_soft: str
    ok: str
    ok_soft: str
    warn: str
    warn_soft: str
    bad: str
    bad_soft: str
    new: str
    grid: str


LIGHT = Tokens(
    bg="#f5f3f9",
    card="#ffffff",
    card_border="rgba(120, 90, 170, 0.10)",
    shadow="0 1px 2px rgba(40, 15, 80, .04), 0 10px 30px rgba(70, 30, 140, .07)",
    text="#1a1523",
    muted="#6e6680",
    accent="#a73afd",
    accent_soft="#f4eaff",
    ok="#0b8a47",
    ok_soft="#e3f6ec",
    warn="#9a6100",
    warn_soft="#fff3d6",
    bad="#d0313b",
    bad_soft="#fde8ea",
    new="#2a6fd6",
    grid="rgba(110, 90, 150, 0.12)",
)

DARK = Tokens(
    bg="#110c18",
    card="#1b1525",
    card_border="rgba(200, 170, 255, 0.10)",
    shadow="0 1px 2px rgba(0, 0, 0, .45), 0 10px 30px rgba(0, 0, 0, .35)",
    text="#f2edf9",
    muted="#a99fbb",
    accent="#c38bff",
    accent_soft="rgba(167, 58, 253, .18)",
    ok="#4ade80",
    ok_soft="rgba(74, 222, 128, .14)",
    warn="#fbbf24",
    warn_soft="rgba(251, 191, 36, .14)",
    bad="#f87171",
    bad_soft="rgba(248, 113, 113, .14)",
    new="#7cb2ff",
    grid="rgba(200, 180, 255, 0.10)",
)


def tokens(dark: bool) -> Tokens:
    return DARK if dark else LIGHT


# Иконки в стиле Lucide (MIT), упрощённые до одного path.
ICONS = {
    "refresh": '<path d="M21 12a9 9 0 1 1-2.64-6.36M21 3v6h-6"/>',
    "layers": '<path d="m12 2 9 5-9 5-9-5 9-5Zm-9 10 9 5 9-5M3 17l9 5 9-5"/>',
    "search": '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>',
    "clock": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    "trend_up": '<path d="m3 17 6-6 4 4 8-8M15 7h6v6"/>',
    "trend_down": '<path d="m3 7 6 6 4-4 8 8M15 17h6v-6"/>',
    "plus": '<circle cx="12" cy="12" r="9"/><path d="M12 8v8M8 12h8"/>',
    "minus": '<circle cx="12" cy="12" r="9"/><path d="M8 12h8"/>',
    "check": '<circle cx="12" cy="12" r="9"/><path d="m8 12 3 3 5-6"/>',
    "calendar": '<rect x="3" y="5" width="18" height="16" rx="3"/><path d="M3 10h18M8 3v4M16 3v4"/>',
    "timer": '<circle cx="12" cy="13" r="8"/><path d="M12 9v4l2 2M9 2h6"/>',
}


def icon(name: str, size: int = 20) -> str:
    return (
        f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
        f'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{ICONS[name]}</svg>'
    )


def css(t: Tokens) -> str:
    return f"""
<style>
:root {{
  --wb-bg: {t.bg}; --wb-card: {t.card}; --wb-card-border: {t.card_border}; --wb-shadow: {t.shadow};
  --wb-text: {t.text}; --wb-muted: {t.muted}; --wb-accent: {t.accent}; --wb-accent-soft: {t.accent_soft};
  --wb-ok: {t.ok}; --wb-ok-soft: {t.ok_soft}; --wb-warn: {t.warn}; --wb-warn-soft: {t.warn_soft};
  --wb-bad: {t.bad}; --wb-bad-soft: {t.bad_soft}; --wb-new: {t.new};
  --wb-gradient: {WB_GRADIENT};
}}

/* Каркас страницы */
.block-container {{ max-width: 1320px; padding-top: 1.2rem !important; padding-bottom: 4rem; }}
header[data-testid="stHeader"] {{ background: transparent; }}
h1, h2, h3 {{ letter-spacing: -0.02em; }}

/* Шапка */
.wb-hero {{
  position: relative; overflow: hidden; border-radius: 28px; padding: 28px 32px;
  background: var(--wb-gradient); color: #fff; margin: 0 0 18px 0;
  box-shadow: 0 18px 40px rgba(131, 6, 247, .22);
  display: flex; gap: 24px; align-items: flex-end; justify-content: space-between; flex-wrap: wrap;
}}
.wb-hero::before, .wb-hero::after {{
  content: ""; position: absolute; border-radius: 50%; pointer-events: none;
  background: radial-gradient(circle, rgba(255,255,255,.28) 0%, rgba(255,255,255,0) 70%);
}}
.wb-hero::before {{ width: 420px; height: 420px; right: -120px; top: -220px; }}
.wb-hero::after {{ width: 300px; height: 300px; left: 30%; bottom: -230px; opacity: .7; }}
.wb-hero > * {{ position: relative; z-index: 1; }}
.wb-hero .main {{ flex: 1 1 520px; min-width: 0; }}
.wb-hero .eyebrow {{
  display: inline-flex; align-items: center; gap: 8px; font-size: .78rem; font-weight: 700;
  letter-spacing: .06em; text-transform: uppercase; opacity: .92;
  background: rgba(255,255,255,.18); padding: 6px 12px; border-radius: 999px;
}}
.wb-hero h1 {{
  color: #fff !important; font-size: clamp(1.7rem, 3.2vw, 2.6rem) !important; line-height: 1.1;
  margin: 14px 0 8px 0 !important; padding: 0 !important; font-weight: 800 !important;
}}
.wb-hero .lead {{ font-size: 1rem; opacity: .92; margin: 0; }}
.wb-hero .chips {{ display: flex; flex-wrap: wrap; gap: 8px; margin-top: 16px; }}
.wb-hero .chip {{
  display: inline-flex; align-items: center; gap: 6px; font-size: .85rem; font-weight: 600;
  background: rgba(255,255,255,.16); border: 1px solid rgba(255,255,255,.25);
  padding: 6px 12px; border-radius: 999px; backdrop-filter: blur(6px);
}}
.wb-status {{
  background: rgba(255,255,255,.96); color: #1a1523; border-radius: 20px; padding: 16px 20px;
  min-width: 250px; box-shadow: 0 8px 24px rgba(40, 0, 90, .18);
}}
.wb-status .label {{ display: flex; align-items: center; gap: 8px; font-size: .8rem; font-weight: 700; color: #6e6680; }}
.wb-status .big {{ font-size: 1.5rem; font-weight: 800; margin-top: 4px; letter-spacing: -0.02em; }}
.wb-status .sub {{ font-size: .85rem; color: #6e6680; margin-top: 2px; }}
.dot {{ width: 9px; height: 9px; border-radius: 50%; background: #16a34a; box-shadow: 0 0 0 0 rgba(22,163,74,.5);
        animation: wb-pulse 2s infinite; display: inline-block; }}
.dot.warn {{ background: #f59e0b; box-shadow: 0 0 0 0 rgba(245,158,11,.5); }}
@keyframes wb-pulse {{ 0% {{ box-shadow: 0 0 0 0 rgba(22,163,74,.45); }} 70% {{ box-shadow: 0 0 0 9px rgba(22,163,74,0); }} 100% {{ box-shadow: 0 0 0 0 rgba(22,163,74,0); }} }}

/* Карточки-контейнеры: st.container(key="card_...") */
div[class*="st-key-card"] {{
  background: var(--wb-card); border: 1px solid var(--wb-card-border); border-radius: 24px;
  padding: 20px 22px 18px 22px; box-shadow: var(--wb-shadow);
}}
div[class*="st-key-card"] div[class*="st-key-card"] {{ box-shadow: none; padding: 0; border: 0; }}

/* Заголовок внутри карточки */
.wb-section {{ display: flex; align-items: baseline; justify-content: space-between; gap: 12px; flex-wrap: wrap; margin: 2px 0 6px 0; }}
.wb-section h3 {{ font-size: 1.2rem !important; font-weight: 800 !important; margin: 0 !important; padding: 0 !important; }}
.wb-section .hint {{ color: var(--wb-muted); font-size: .88rem; }}

/* Карточки показателей */
.wb-kpis {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 14px; margin: 4px 0 18px 0; }}
.wb-kpi {{
  background: var(--wb-card); border: 1px solid var(--wb-card-border); border-radius: 22px;
  padding: 16px 18px; box-shadow: var(--wb-shadow); display: flex; gap: 14px; align-items: center; min-width: 0;
}}
.wb-kpi .ico {{
  flex: 0 0 44px; height: 44px; border-radius: 14px; display: grid; place-items: center;
  background: var(--wb-accent-soft); color: var(--wb-accent);
}}
.wb-kpi .ico.ok {{ background: var(--wb-ok-soft); color: var(--wb-ok); }}
.wb-kpi .ico.bad {{ background: var(--wb-bad-soft); color: var(--wb-bad); }}
.wb-kpi .ico.new {{ background: var(--wb-accent-soft); color: var(--wb-new); }}
.wb-kpi .label {{ font-size: .8rem; font-weight: 600; color: var(--wb-muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
.wb-kpi .value {{ font-size: 1.45rem; font-weight: 800; letter-spacing: -0.02em; line-height: 1.2; color: var(--wb-text);
                 white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
.wb-kpi .sub {{ font-size: .78rem; color: var(--wb-muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
.wb-kpi .value .up {{ color: var(--wb-ok); }} .wb-kpi .value .down {{ color: var(--wb-bad); }}

/* Вкладки-«таблетки» (Streamlit 1.65: react-aria, role=tablist / data-testid=stTab) */
div[data-testid="stTabs"] [role="tablist"] {{
  gap: 6px; background: var(--wb-card); padding: 6px; border-radius: 18px; box-shadow: var(--wb-shadow);
  border: 1px solid var(--wb-card-border); width: fit-content; max-width: 100%; overflow-x: auto; scrollbar-width: none;
}}
div[data-testid="stTabs"] [role="tablist"]::before, div[data-testid="stTabs"] [role="tablist"]::after {{ display: none !important; }}
div[data-testid="stTabs"] [data-testid="stTab"] {{
  height: 40px; padding: 0 18px; border-radius: 13px; background: transparent; white-space: nowrap;
  transition: background .15s ease, color .15s ease; border: 0 !important;
}}
div[data-testid="stTabs"] [data-testid="stTab"]:hover {{ background: var(--wb-accent-soft); }}
div[data-testid="stTabs"] [data-testid="stTab"] p {{ font-weight: 700; font-size: .92rem; }}
div[data-testid="stTabs"] [data-testid="stTab"][aria-selected="true"] {{ background: var(--wb-gradient); color: #fff; }}
div[data-testid="stTabs"] [data-testid="stTab"][aria-selected="true"] p {{ color: #fff; }}
div[data-testid="stTabs"] [role="tabpanel"] {{ padding-top: 16px; }}

/* Подписи полей */
div[data-testid="stWidgetLabel"] p {{ font-weight: 700; font-size: .86rem; }}

/* Мелкий текст-подсказка */
.wb-note {{ color: var(--wb-muted); font-size: .86rem; line-height: 1.5; }}
.wb-note b {{ color: var(--wb-text); }}
.wb-legend-gap {{ display: inline-block; width: 26px; height: 0; border-top: 2px dashed var(--wb-muted); vertical-align: middle; margin: 0 4px; }}

/* Подвал */
.wb-footer {{ margin-top: 28px; color: var(--wb-muted); font-size: .85rem; text-align: center; }}
.wb-footer a {{ color: var(--wb-accent); text-decoration: none; font-weight: 600; }}

@media (max-width: 900px) {{
  .wb-kpis {{ grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }}
  .wb-hero {{ padding: 22px 20px; border-radius: 22px; }}
  .wb-status {{ width: 100%; min-width: 0; }}
  div[class*="st-key-card"] {{ padding: 16px 14px; border-radius: 20px; }}
}}
@media (max-width: 480px) {{
  .wb-kpi {{ padding: 12px; gap: 10px; }}
  .wb-kpi .ico {{ flex-basis: 36px; height: 36px; border-radius: 12px; }}
  .wb-kpi .value {{ font-size: 1.15rem; }}
  .wb-kpi .label, .wb-kpi .sub {{ white-space: normal; }}
}}
</style>
"""


def hero(*, title: str, lead: str, chips: list[str], status_label: str, status_big: str, status_sub: str, fresh: bool) -> str:
    chips_html = "".join(f'<span class="chip">{escape(c)}</span>' for c in chips)
    dot = "dot" if fresh else "dot warn"
    return f"""
<div class="wb-hero">
  <div class="main">
    <span class="eyebrow">{icon("search", 14)} Мониторинг поисковой выдачи</span>
    <h1>{escape(title)}</h1>
    <p class="lead">{escape(lead)}</p>
    <div class="chips">{chips_html}</div>
  </div>
  <div class="wb-status">
    <div class="label"><span class="{dot}"></span>{escape(status_label)}</div>
    <div class="big">{escape(status_big)}</div>
    <div class="sub">{escape(status_sub)}</div>
  </div>
</div>
"""


@dataclass
class Kpi:
    label: str
    value: str
    sub: str = ""
    icon: str = "layers"
    tone: str = ""  # "", "ok", "bad", "new"
    value_html: bool = False  # value уже содержит безопасную HTML-разметку
    title: str = ""  # всплывающая подсказка


def kpis(items: list[Kpi]) -> str:
    cards = []
    for k in items:
        value = k.value if k.value_html else escape(k.value)
        cards.append(
            f'<div class="wb-kpi" title="{escape(k.title)}">'
            f'<div class="ico {k.tone}">{icon(k.icon)}</div>'
            f'<div style="min-width:0"><div class="label">{escape(k.label)}</div>'
            f'<div class="value">{value}</div><div class="sub">{escape(k.sub)}</div></div></div>'
        )
    return f'<div class="wb-kpis">{"".join(cards)}</div>'


def section(title: str, hint: str = "") -> str:
    hint_html = f'<span class="hint">{escape(hint)}</span>' if hint else ""
    return f'<div class="wb-section"><h3>{escape(title)}</h3>{hint_html}</div>'
