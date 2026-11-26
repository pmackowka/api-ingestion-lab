"""Święta państwowe w Polsce z Nager.Date (API v4) -> BigQuery."""

import argparse
import json
import urllib.request
from datetime import date, datetime, timezone

from google.cloud import bigquery

from common import cli
from common.bigquery import replace_date_range

API_URL = "https://nagerholidays.com/api/v4/Holidays/{country}/{year}"
COUNTRY = "PL"
USER_AGENT = "api-ingestion-lab"

TARGET_TABLE = "public_holidays"

SCHEMA = [
    bigquery.SchemaField("holiday_date", "DATE", mode="REQUIRED"),
    bigquery.SchemaField("country_code", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("name", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("is_national", "BOOL", mode="REQUIRED"),
    bigquery.SchemaField("holiday_types", "STRING", mode="REPEATED"),
    bigquery.SchemaField("subdivision_codes", "STRING", mode="REPEATED"),
    bigquery.SchemaField("loaded_at", "TIMESTAMP", mode="REQUIRED"),
]


def year_bounds(start: date, end: date) -> tuple[date, date]:
    """Rozszerza [start, end] do pełnych lat, bo API zwraca święta po roku."""
    if start > end:
        raise ValueError(f"start {start} jest po end {end}")
    return date(start.year, 1, 1), date(end.year, 12, 31)


def fetch_year(year: int, country: str = COUNTRY) -> list[dict]:
    """Pobiera święta jednego roku jednym GET-em."""
    url = API_URL.format(country=country, year=year)
    request = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read())


def to_rows(holidays: list[dict], loaded_at: datetime) -> list[dict]:
    """Święto z API -> wiersz; brak województw (null) -> pusta lista."""
    return [
        {
            "holiday_date": h["date"],
            "country_code": h["countryCode"],
            "name": h["name"],
            "is_national": h["nationalHoliday"],
            "holiday_types": h["holidayTypes"] or [],
            "subdivision_codes": h["subdivisionCodes"] or [],
            "loaded_at": loaded_at.isoformat(),
        }
        for h in holidays
    ]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Wspólny interfejs CLI (common/cli.py): --project, --dataset, --start albo --lookback-days, --end."""
    return cli.parse(cli.make_parser("Święta w Polsce (Nager.Date) -> BigQuery", default_dataset="raw_holidays"), argv)


def main() -> None:
    args = parse_args()
    start, end = year_bounds(args.start, args.end)

    loaded_at = datetime.now(timezone.utc)
    rows = []
    for year in range(start.year, end.year + 1):
        holidays = fetch_year(year)
        print(f"{year}: {len(holidays)} świąt")
        rows.extend(to_rows(holidays, loaded_at))

    replace_date_range(
        rows,
        project=args.project,
        dataset=args.dataset,
        table=TARGET_TABLE,
        schema=SCHEMA,
        date_column="holiday_date",
        start=start,
        end=end,
    )
    print(f"Załadowano {len(rows)} wierszy do {args.project}.{args.dataset}.{TARGET_TABLE} ({start}..{end})")


if __name__ == "__main__":
    main()
