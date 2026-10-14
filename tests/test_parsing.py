import datetime as dt

from wb_serp.parsing import delivery_days, parse_products

UTC = dt.timezone.utc


def product(**overrides):
    base = {
        "id": 307757080,
        "name": "Постельное белье 1.5 спальное с принтом",
        "brand": "SalvaHome",
        "supplier": "SalvaHome",
        "supplierId": 1168274,
        "reviewRating": 4.8,
        "rating": 5,
        "feedbacks": 15575,
        "time1": 3,
        "time2": 56,
        "sizes": [{"price": {"basic": 518500, "product": 77400}, "time1": 3, "time2": 56}],
    }
    base.update(overrides)
    return base


# Реальные пары из сверки с сайтом 14.10.2026 16:05 МСК (13:05 UTC):
# time1 + time2 часов -> дата, которую показывала карточка.
def test_delivery_days_matches_site_examples():
    now = dt.datetime(2026, 10, 14, 13, 5, tzinfo=UTC)
    assert delivery_days(now, 1 + 50) == 2  # «Послезавтра»
    assert delivery_days(now, 3 + 56) == 3  # «17 октября»
    assert delivery_days(now, 2 + 99) == 4  # «18 октября»
    assert delivery_days(now, 47 + 56) == 5  # «19 октября»: прибытие в 23:05 — сайт показывает следующий день


def test_delivery_days_today_tomorrow_and_missing():
    morning = dt.datetime(2026, 10, 14, 6, 0, tzinfo=UTC)  # 09:00 МСК
    assert delivery_days(morning, 5) == 0  # сегодня
    assert delivery_days(morning, 20) == 1  # завтра
    assert delivery_days(morning, None) is None


def test_delivery_days_uses_moscow_date_not_utc():
    # 22:30 UTC = 01:30 МСК следующего дня: «сегодня» считается по Москве.
    late_utc = dt.datetime(2026, 10, 14, 22, 30, tzinfo=UTC)
    assert delivery_days(late_utc, 10) == 0


def test_parse_products_maps_fields_and_positions():
    obs = parse_products([product(), product(id=909819446, feedbacks=32, reviewRating=4.6)], dt.datetime.now(UTC), start_position=101)
    assert [o.position for o in obs] == [101, 102]
    first = obs[0]
    assert first.nm_id == 307757080
    assert first.price_kop == 77400
    assert first.rating == 4.8
    assert first.feedbacks == 15575
    assert first.delivery_hours == 59
    assert first.supplier == "SalvaHome"


def test_missing_fields_become_null_not_invented():
    raw = {"id": 1, "sizes": [{}], "supplier": "", "reviewRating": 0, "feedbacks": 0}
    (obs,) = parse_products([raw], dt.datetime.now(UTC))
    assert obs.price_kop is None
    assert obs.rating is None  # 0 у товара без оценок — это «нет рейтинга»
    assert obs.feedbacks == 0
    assert obs.delivery_hours is None and obs.delivery_days is None
    assert obs.supplier is None


def test_price_is_minimum_over_sizes():
    raw = product(sizes=[{"price": {"product": 150000}}, {"price": {"product": 99900}}, {"name": "без цены"}])
    (obs,) = parse_products([raw], dt.datetime.now(UTC))
    assert obs.price_kop == 99900


def test_products_without_id_are_skipped_but_keep_their_slot():
    obs = parse_products([product(), {"name": "без id"}, product(id=2)], dt.datetime.now(UTC))
    assert [(o.nm_id, o.position) for o in obs] == [(307757080, 1), (2, 3)]
