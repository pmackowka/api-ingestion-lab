"""Kursy średnie NBP (tabela A) -> BigQuery.

Uruchomienie:
    uv run python -m nbp.ingest --project <projekt-gcp> --start 2026-01-01 --end 2026-03-31   # backfill
    uv run python -m nbp.ingest --project <projekt-gcp> --lookback-days 7                    # harmonogram
"""

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
# API przyjmuje end - start <= 93 dni (sprawdzone empirycznie: 94 dni różnicy -> 400).
# Bierzemy 93 dni kalendarzowe włącznie (różnica 92), żeby mieć zapas na zmianę interpretacji limitu.
WINDOW_DAYS = 93

TARGET_TABLE = "exchange_rates_a"  # staging: _staging_exchange_rates_a (tworzy common/bigquery.py)

# Jeden schemat dla staging i tabeli docelowej. Klucz naturalny: (effective_date, currency_code).
SCHEMA = [
    bigquery.SchemaField("effective_date", "DATE", mode="REQUIRED"),
    bigquery.SchemaField("table_no", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("currency_code", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("currency_name", "STRING"),
    # NUMERIC, nie FLOAT64: kurs to wartość dziesiętna, float wprowadza błędy zaokrągleń.
    bigquery.SchemaField("mid", "NUMERIC", mode="REQUIRED"),
    # Kiedy wiersz trafił do BigQuery — pozwala odróżnić dane z różnych uruchomień przy debugowaniu.
    bigquery.SchemaField("loaded_at", "TIMESTAMP", mode="REQUIRED"),
]


def split_windows(start: date, end: date, window_days: int = WINDOW_DAYS) -> list[tuple[date, date]]:
    """Krok 1: dzieli [start, end] (obie granice włącznie) na sąsiadujące okna po maks. window_days dni.

    Po co: API odrzuca zakres dłuższy niż 93 dni, a chcemy móc załadować np. kilka lat jednym
    uruchomieniem. Ten sam wzorzec (pętla po kawałkach zakresu) wraca przy paginacji w etapie 3 (GA4).
    """
    if start > end:
        raise ValueError(f"start {start} jest po end {end}")
    windows = []
    cursor = start
    while cursor <= end:
        # min(...) przycina ostatnie okno do `end`, żeby nie pytać o daty spoza zakresu.
        window_end = min(cursor + timedelta(days=window_days - 1), end)
        windows.append((cursor, window_end))
        # Następne okno zaczyna się dzień po końcu poprzedniego — bez luk i bez nakładania.
        cursor = window_end + timedelta(days=1)
    return windows


def fetch_window(start: date, end: date) -> list[dict]:
    """Krok 2: pobiera tabele A z jednego okna jednym GET-em.

    Zwraca listę tabel: jedna tabela = jeden dzień notowań z kursami wszystkich walut.
    """
    url = API_URL.format(start=start.isoformat(), end=end.isoformat())
    # NBP zwraca JSON albo XML zależnie od nagłówka Accept. Prosimy jawnie o JSON,
    # zamiast polegać na formacie domyślnym.
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        # timeout: bez niego zawieszone połączenie blokuje skrypt w nieskończoność.
        with urllib.request.urlopen(request, timeout=30) as response:
            # parse_float=Decimal: kurs trafia do Pythona bez przejścia przez float.
            return json.loads(response.read(), parse_float=Decimal)
    except urllib.error.HTTPError as error:
        # NBP zwraca 404, gdy w oknie nie ma żadnego notowania (weekend, święta).
        # To poprawny stan danych, nie awaria — zwracamy pustą listę.
        if error.code == 404:
            return []
        # Każdy inny kod (400 = zły zakres, 5xx = awaria NBP) przerywa skrypt.
        # Lepiej nie załadować nic niż załadować dziurawy zakres i podmienić nim dobre dane.
        raise


def to_rows(tables: list[dict], loaded_at: datetime) -> list[dict]:
    """Krok 3: spłaszcza odpowiedź API: jedna tabela z N walutami -> N wierszy.

    Po co: BigQuery ładuje płaskie wiersze, a API zwraca zagnieżdżoną strukturę dzień -> waluty.

    Klucze słownika czytamy przez [...], nie .get(): jeśli NBP zmieni format odpowiedzi,
    skrypt padnie z KeyError zamiast po cichu wpisać NULL-e.
    """
    rows = []
    for table in tables:
        for rate in table["rates"]:
            rows.append(
                {
                    "effective_date": table["effectiveDate"],
                    "table_no": table["no"],
                    "currency_code": rate["code"],
                    "currency_name": rate["currency"],
                    # Decimal -> str: JSON load do BigQuery przyjmie tekst do kolumny NUMERIC bez utraty precyzji.
                    "mid": str(rate["mid"]),
                    # Jedna wartość na całe uruchomienie, nie czas pojedynczego wiersza.
                    "loaded_at": loaded_at.isoformat(),
                }
            )
    return rows


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Wspólny interfejs CLI (common/cli.py): --project, --dataset, --start albo --lookback-days, --end."""
    return cli.parse(cli.make_parser("Kursy NBP (tabela A) -> BigQuery", default_dataset="raw_nbp"), argv)


def main() -> None:
    args = parse_args()

    # Kroki 1-3: pobranie i spłaszczenie wszystkich okien, zanim cokolwiek trafi do BigQuery.
    # Błąd API w dowolnym oknie przerywa skrypt, zanim cokolwiek zmieni się w tabeli.
    # loaded_at liczymy raz: wszystkie wiersze z jednego uruchomienia mają ten sam znacznik.
    loaded_at = datetime.now(timezone.utc)
    rows = []
    for window_start, window_end in split_windows(args.start, args.end):
        tables = fetch_window(window_start, window_end)
        print(f"{window_start}..{window_end}: {len(tables)} dni notowań")
        rows.extend(to_rows(tables, loaded_at))

    # Pusty zakres (np. sam weekend): nic nie zapisujemy — load pustej listy nie ma sensu.
    if not rows:
        print("Brak notowań w zakresie — nic do załadowania.")
        return

    # Krok 4: zapis do BigQuery z podmianą zakresu [start, end] — wspólny dla wszystkich źródeł,
    # opis mechanizmu w common/bigquery.py i README.md („Jak dane trafiają do BigQuery”).
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
