import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.collectors.facebook_collector import parse_relative_date


def _now():
    return datetime(2024, 6, 15, 12, 0, 0, tzinfo=timezone.utc)


def test_relative_hours():
    assert parse_relative_date("5 jam", now=_now()) == "2024-06-15"


def test_relative_recent_hours():
    assert parse_relative_date("3 jam", now=_now()) == "2024-06-15"


def test_relative_days():
    assert parse_relative_date("2 hari", now=_now()) == "2024-06-13"


def test_relative_years():
    # heuristic: 1 year = 365 days (leap days shift the answer by a day)
    expected = (_now() - __import__("datetime").timedelta(days=365 * 3)).date().isoformat()
    assert parse_relative_date("3 th", now=_now()) == expected


def test_relative_weeks_and_months():
    assert parse_relative_date("2 minggu", now=_now()) == "2024-06-01"
    expected_m = (_now() - __import__("datetime").timedelta(days=30 * 4)).date().isoformat()
    assert parse_relative_date("4 bulan", now=_now()) == expected_m


def test_absolute_indo_date():
    assert parse_relative_date("12 Januari 2022", now=_now()) == "2022-01-12"


def test_absolute_eng_date():
    assert parse_relative_date("Jan 12, 2022", now=_now()) == "2022-01-12"


def test_just_now():
    assert parse_relative_date("Baru saja", now=_now()) == "2024-06-15"


def test_unparseable_returns_none():
    assert parse_relative_date("sangat bagus sekali", now=_now()) is None
    assert parse_relative_date("", now=_now()) is None
    assert parse_relative_date(None, now=_now()) is None


def test_within_history_window():
    # 2022 post must be newer than history_since 2022-01-01
    d = parse_relative_date("03 April 2022", now=_now())
    assert d is not None and d >= "2022-01-01"