"""Kursy średnie NBP (tabela A) -> BigQuery."""

import argparse
import json
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from google.cloud import bigquery

from common import cli
from common.bigquery import replace_date_range

API_URL = "https://api.nbp.pl/api/exchangerates/tables/A/{start}/{end}/"
WINDOW_DAYS = 93

TARGET_TABLE = "exchange_rates_a"

SCHEMA = [
    bigquery.SchemaField("effective_date", "DATE", mode="REQUIRED"),
    bigquery.SchemaField("table_no", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("currency_code", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("currency_name", "STRING"),
    bigquery.SchemaField("mid", "NUMERIC", mode="REQUIRED"),
    bigquery.SchemaField("loaded_at", "TIMESTAMP", mode="REQUIRED"),
]


def split_windows(start: date, end: date, window_days: int = WINDOW_DAYS) -> list[tuple[date, date]]:
    """Dzieli [start, end] (obie granice włącznie) na sąsiadujące okna po maks. window_days dni."""
    if start > end:
        raise ValueError(f"start {start} jest po end {end}")
    windows = []
    cursor = start
    while cursor <= end:
        window_end = min(cursor + timedelta(days=window_days - 1), end)
        windows.append((cursor, window_end))
        cursor = window_end + timedelta(days=1)
    return windows


def fetch_window(start: date, end: date) -> list[dict]:
    """Pobiera tabele A z jednego okna jednym GET-em."""
    url = API_URL.format(start=start.isoformat(), end=end.isoformat())
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read(), parse_float=Decimal)
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return []
        raise


def to_rows(tables: list[dict], loaded_at: datetime) -> list[dict]:
    """Spłaszcza odpowiedź API: jedna tabela z N walutami -> N wierszy."""
    rows = []
    for table in tables:
        for rate in table["rates"]:
            rows.append(
                {
                    "effective_date": table["effectiveDate"],
                    "table_no": table["no"],
                    "currency_code": rate["code"],
                    "currency_name": rate["currency"],
                    "mid": str(rate["mid"]),
                    "loaded_at": loaded_at.isoformat(),
                }
            )
    return rows


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Wspólny interfejs CLI (common/cli.py): --project, --dataset, --start albo --lookback-days, --end."""
    return cli.parse(cli.make_parser("Kursy NBP (tabela A) -> BigQuery", default_dataset="raw_nbp"), argv)


def main() -> None:
    args = parse_args()

    loaded_at = datetime.now(timezone.utc)
    rows = []
    for window_start, window_end in split_windows(args.start, args.end):
        tables = fetch_window(window_start, window_end)
        print(f"{window_start}..{window_end}: {len(tables)} dni notowań")
        rows.extend(to_rows(tables, loaded_at))

    if not rows:
        print("Brak notowań w zakresie — nic do załadowania.")
        return

    replace_date_range(
        rows,
        project=args.project,
        dataset=args.dataset,
        table=TARGET_TABLE,
        schema=SCHEMA,
        date_column="effective_date",
        start=args.start,
        end=args.end,
    )
    print(f"Załadowano {len(rows)} wierszy do {args.project}.{args.dataset}.{TARGET_TABLE}")


if __name__ == "__main__":
    main()
