from datetime import date, datetime, timezone

import pytest

from holidays.ingest import to_rows, year_bounds

LOADED_AT = datetime(2026, 11, 26, 12, 0, tzinfo=timezone.utc)


def test_year_bounds_expands_to_full_years():
    assert year_bounds(date(2025, 12, 20), date(2026, 1, 3)) == (date(2025, 1, 1), date(2026, 12, 31))


def test_year_bounds_rejects_reversed_range():
    with pytest.raises(ValueError):
        year_bounds(date(2026, 2, 1), date(2026, 1, 1))


def test_to_rows_maps_null_subdivisions_to_empty_list():
    holiday = {"date": "2026-04-05", "name": "Easter Sunday", "countryCode": "PL", "nationalHoliday": True,
               "subdivisionCodes": None, "holidayTypes": ["Public"]}

    row = to_rows([holiday], LOADED_AT)[0]

    assert (row["holiday_date"], row["is_national"], row["holiday_types"]) == ("2026-04-05", True, ["Public"])
    assert row["subdivision_codes"] == []
