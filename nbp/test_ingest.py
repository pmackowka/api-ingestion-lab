from datetime import date

from ingest import split_windows


def test_split_windows_covers_range_without_gaps_or_overlap():
    windows = split_windows(date(2026, 1, 1), date(2026, 7, 1))

    # 182 dni -> 93 + 89
    assert windows == [
        (date(2026, 1, 1), date(2026, 4, 3)),
        (date(2026, 4, 4), date(2026, 7, 1)),
    ]


def test_split_windows_single_day():
    assert split_windows(date(2026, 1, 2), date(2026, 1, 2)) == [(date(2026, 1, 2), date(2026, 1, 2))]
