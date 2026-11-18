"""Wyniki wyszukiwania Google z Search Console API -> BigQuery.

Uruchomienie:
    uv run python -m search_console.ingest --project <projekt-gcp> --site sc-domain:pmdata.pl --start 2025-01-01   # backfill
    uv run python -m search_console.ingest --project <projekt-gcp> --site sc-domain:pmdata.pl --lookback-days 7    # harmonogram
"""

import argparse
import urllib.parse
from datetime import date, datetime, timezone

from google.cloud import bigquery

from common import cli
from common.bigquery import replace_date_range
from common.http import authorized_session

API_URL = "https://www.googleapis.com/webmasters/v3/sites/{site}/searchAnalytics/query"
SCOPES = ["https://www.googleapis.com/auth/webmasters.readonly"]

# Maksimum API na jedno zapytanie; większy raport stronicujemy przez startRow.
PAGE_SIZE = 25_000

# Dwie tabele, bo Search Console liczy inaczej zależnie od wymiarów (sprawdzone na żywo, 2025-01..2026-11):
# - bez `page`: sumy dla całej usługi (byProperty) — 679 wyświetleń, zgodnie z panelem;
# - z `page`: każda podstrona widoczna w wyniku dostaje swoje wyświetlenie (byPage) — 1089 wyświetleń.
# Dokumentacja: dla dokładnych sum usługi pomiń page i query. Sumy z tabeli stron nie są więc sumą usługi.
# Wymiaru `query` nie ładujemy: Google anonimizuje rzadkie zapytania — widać 38 z 679 wyświetleń.
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
        # Średnia pozycja w wierszu. Przy agregacji licz średnią ważoną wyświetleniami,
        # nie zwykłą średnią: SUM(position * impressions) / SUM(impressions).
        # CTR nie zapisujemy — to clicks / impressions, policzysz w SQL.
        bigquery.SchemaField("position", "FLOAT64", mode="REQUIRED"),
        bigquery.SchemaField("site", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("loaded_at", "TIMESTAMP", mode="REQUIRED"),
    ]


def fetch_report(session, site: str, start: date, end: date, dimensions: list[str], page_size: int = PAGE_SIZE) -> list[dict]:
    """Krok 1: pobiera raport strona po stronie (paginacja startRow).

    Inaczej niż w GA4: odpowiedź nie podaje liczby wszystkich wierszy (rowCount), więc koniec
    poznajemy po stronie krótszej niż limit. Ten sam cel, inny sygnał końca — typowe między API.
    """
    # siteUrl idzie w ścieżce URL: "sc-domain:pmdata.pl" -> "sc-domain%3Apmdata.pl" (safe="" koduje też ":" i "/").
    url = API_URL.format(site=urllib.parse.quote(site, safe=""))
    rows, start_row = [], 0
    while True:
        body = {
            "startDate": start.isoformat(),
            "endDate": end.isoformat(),
            "dimensions": dimensions,
            "rowLimit": page_size,
            "startRow": start_row,
            # "all" = także świeże, wstępne dane z ostatnich dni ("final" kończy się ok. 2 dni wcześniej).
            # Wstępne wartości poprawi lookback przy kolejnych uruchomieniach — jak w pogodzie.
            "dataState": "all",
        }
        response = session.post(url, json=body, timeout=60)
        # 403 = konto usługi bez dostępu w Search Console albo brak zakresu webmasters.readonly w ADC.
        response.raise_for_status()
        page = response.json().get("rows", [])
        rows.extend(page)
        if len(page) < page_size:
            return rows
        start_row += page_size


def to_rows(report: list[dict], dimensions: list[str], site: str, loaded_at: datetime) -> list[dict]:
    """Krok 2: `keys` (wartości wymiarów w kolejności z zapytania) -> kolumny.

    clicks i impressions przychodzą jako liczby zmiennoprzecinkowe (1.0) — to liczniki, więc int.
    """
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
    # Usługa domenowa: sc-domain:example.com; usługa z prefiksem URL: https://example.com/
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
