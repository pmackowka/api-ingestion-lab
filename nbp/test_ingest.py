from datetime import date

import pytest

from nbp.ingest import parse_args, split_windows


def test_split_windows_covers_range_without_gaps_or_overlap():
    windows = split_windows(date(2026, 1, 1), date(2026, 7, 1))

    assert windows == [
        (date(2026, 1, 1), date(2026, 4, 3)),
        (date(2026, 4, 4), date(2026, 7, 1)),
    ]


def test_split_windows_single_day():
    assert split_windows(date(2026, 1, 2), date(2026, 1, 2)) == [(date(2026, 1, 2), date(2026, 1, 2))]


def test_lookback_days_sets_start_relative_to_end():
    args = parse_args(["--project", "p", "--end", "2026-11-16", "--lookback-days", "7"])
    assert args.start == date(2026, 11, 9)


def test_start_and_lookback_are_mutually_exclusive():
    with pytest.raises(SystemExit):
        parse_args(["--project", "p", "--start", "2026-01-01", "--lookback-days", "7"])
