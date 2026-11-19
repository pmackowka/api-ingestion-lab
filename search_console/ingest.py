"""Wyniki wyszukiwania Google z Search Console API -> BigQuery."""

import argparse
import urllib.parse
from datetime import date, datetime, timezone

from google.cloud import bigquery

from common import cli
from common.bigquery import replace_date_range
from common.http import authorized_session

API_URL = "https://www.googleapis.com/webmasters/v3/sites/{site}/searchAnalytics/query"
SCOPES = ["https://www.googleapis.com/auth/webmasters.readonly"]

PAGE_SIZE = 25_000

REPORTS = {
    "search_daily": ["date", "country", "device"],
    "search_pages_daily": ["date", "page"],
}

_DIMENSION_COLUMNS = {"date": "report_date", "country": "country", "device": "device", "page": "page"}


def _schema(dimensions: list[str]) -> list[bigquery.SchemaField]:
    """Schemat tabeli: wymiary raportu + wspólne metryki."""
    fields = [
        bigquery.SchemaField(_DIMENSION_COLUMNS[d], "DATE" if d == "date" else "STRING", mode="REQUIRED")
        for d in dimensions
    ]
    return [
        *fields,
        bigquery.SchemaField("clicks", "INT64", mode="REQUIRED"),
        bigquery.SchemaField("impressions", "INT64", mode="REQUIRED"),
        bigquery.SchemaField("position", "FLOAT64", mode="REQUIRED"),
        bigquery.SchemaField("site", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("loaded_at", "TIMESTAMP", mode="REQUIRED"),
    ]


def fetch_report(session, site: str, start: date, end: date, dimensions: list[str], page_size: int = PAGE_SIZE) -> list[dict]:
    """Pobiera raport strona po stronie (paginacja startRow)."""
    url = API_URL.format(site=urllib.parse.quote(site, safe=""))
    rows, start_row = [], 0
    while True:
        body = {
            "startDate": start.isoformat(),
            "endDate": end.isoformat(),
            "dimensions": dimensions,
            "rowLimit": page_size,
            "startRow": start_row,
            "dataState": "all",
        }
        response = session.post(url, json=body, timeout=60)
        response.raise_for_status()
        page = response.json().get("rows", [])
        rows.extend(page)
        if len(page) < page_size:
            return rows
        start_row += page_size


def to_rows(report: list[dict], dimensions: list[str], site: str, loaded_at: datetime) -> list[dict]:
    """`keys` (wartości wymiarów w kolejności z zapytania) -> kolumny."""
    rows = []
    for item in report:
        row = {_DIMENSION_COLUMNS[d]: value for d, value in zip(dimensions, item["keys"], strict=True)}
        row.update(
            clicks=int(item["clicks"]),
            impressions=int(item["impressions"]),
            position=item["position"],
            site=site,
            loaded_at=loaded_at.isoformat(),
        )
        rows.append(row)
    return rows


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Wspólny interfejs CLI (common/cli.py) + --site, którego inne źródła nie mają."""
    parser = cli.make_parser("Search Console API -> BigQuery", default_dataset="raw_search_console")
    parser.add_argument("--site", required=True, help="usługa Search Console, np. sc-domain:pmdata.pl")
    return cli.parse(parser, argv)


def main() -> None:
    args = parse_args()
    session = authorized_session(SCOPES)
    loaded_at = datetime.now(timezone.utc)
    for table, dimensions in REPORTS.items():
        rows = to_rows(fetch_report(session, args.site, args.start, args.end, dimensions), dimensions, args.site, loaded_at)
        if not rows:
            print(f"{table}: brak wierszy w {args.start}..{args.end} — pomijam")
            continue
        replace_date_range(
            rows,
            project=args.project,
            dataset=args.dataset,
            table=table,
            schema=_schema(dimensions),
            date_column="report_date",
            start=args.start,
            end=args.end,
        )
        print(f"{table}: {len(rows)} wierszy, {args.start}..{args.end}")


if __name__ == "__main__":
    main()
