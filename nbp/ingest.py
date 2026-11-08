"""Etap 1: kursy średnie NBP (tabela A) -> BigQuery.

Przepływ:
1. Zakres dat dzielimy na okna, bo API odrzuca zapytanie dłuższe niż 93 dni (HTTP 400).
2. Każde okno pobieramy jednym GET-em. 404 oznacza "brak notowań" (np. weekend), nie błąd.
3. Wszystkie wiersze ładujemy do tabeli staging (WRITE_TRUNCATE), a potem przepisujemy tabelę
   docelową: stare wiersze spoza zakresu [start, end] + świeże wiersze ze staging.
   Zakres jest więc zawsze zastępowany w całości, a ponowne uruchomienie nie tworzy duplikatów (idempotencja).

Dlaczego nie MERGE: sandbox BigQuery (projekt bez billingu) nie obsługuje DML.
Zapytanie SELECT z tabelą docelową i WRITE_TRUNCATE to zwykły query job, nie DML, więc działa.
Koszt obejścia: każde uruchomienie przepisuje całą tabelę — przy kilku MB danych bez znaczenia,
przy dużych tabelach użylibyśmy MERGE albo nadpisywania pojedynczych partycji.

Uruchomienie:
    uv run python nbp/ingest.py --project <projekt-gcp> --start 2026-01-01 --end 2026-03-31
"""

import argparse
import json
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from google.cloud import bigquery

API_URL = "https://api.nbp.pl/api/exchangerates/tables/A/{start}/{end}/"
# API przyjmuje end - start <= 93 dni (sprawdzone empirycznie: 94 dni różnicy -> 400).
# Bierzemy 93 dni kalendarzowe włącznie (różnica 92), żeby mieć zapas na zmianę interpretacji limitu.
WINDOW_DAYS = 93

TARGET_TABLE = "exchange_rates_a"
STAGING_TABLE = "_staging_exchange_rates_a"

SCHEMA = [
    bigquery.SchemaField("effective_date", "DATE", mode="REQUIRED"),
    bigquery.SchemaField("table_no", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("currency_code", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("currency_name", "STRING"),
    # NUMERIC, nie FLOAT64: kurs to wartość dziesiętna, float wprowadza błędy zaokrągleń.
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
        # Następne okno zaczyna się dzień po końcu poprzedniego — bez luk i bez nakładania.
        cursor = window_end + timedelta(days=1)
    return windows


def fetch_window(start: date, end: date) -> list[dict]:
    """Pobiera tabele A z jednego okna. Zwraca listę tabel (jedna tabela = jeden dzień notowań)."""
    url = API_URL.format(start=start.isoformat(), end=end.isoformat())
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            # parse_float=Decimal: kurs trafia do Pythona bez przejścia przez float.
            return json.loads(response.read(), parse_float=Decimal)
    except urllib.error.HTTPError as error:
        # NBP zwraca 404, gdy w oknie nie ma żadnego notowania (weekend, święta).
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
                    # Decimal -> str: JSON load do BigQuery przyjmie tekst do kolumny NUMERIC bez utraty precyzji.
                    "mid": str(rate["mid"]),
                    "loaded_at": loaded_at.isoformat(),
                }
            )
    return rows


def load_to_bigquery(rows: list[dict], project: str, dataset: str, start: date, end: date) -> None:
    client = bigquery.Client(project=project)
    client.create_dataset(f"{project}.{dataset}", exists_ok=True)

    target = f"{project}.{dataset}.{TARGET_TABLE}"
    staging = f"{project}.{dataset}.{STAGING_TABLE}"
    client.create_table(bigquery.Table(target, schema=SCHEMA), exists_ok=True)

    # Krok 1: staging nadpisywany w całości przy każdym uruchomieniu.
    job_config = bigquery.LoadJobConfig(
        schema=SCHEMA,
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
    )
    client.load_table_from_json(rows, staging, job_config=job_config).result()

    # Krok 2: przepisanie tabeli docelowej jednym zapytaniem.
    # Query job z WRITE_TRUNCATE jest atomowy: albo podmieni całą tabelę, albo zostawi ją bez zmian.
    # Zapytanie czyta tabelę docelową i jednocześnie ją nadpisuje — BigQuery na to pozwala,
    # bo wynik zapisuje dopiero po zakończeniu odczytu.
    # Uwaga: WRITE_TRUNCATE z zapytania nadpisuje też schemat, więc w tabeli docelowej kolumny
    # stają się NULLABLE. Pilnowanie REQUIRED zostaje na granicy: load do staging odrzuci wiersz z NULL-em.
    rewrite_sql = f"""
        SELECT * FROM `{target}`
        WHERE effective_date NOT BETWEEN @start AND @end
        UNION ALL
        SELECT * FROM `{staging}`
    """
    query_config = bigquery.QueryJobConfig(
        destination=target,
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
        query_parameters=[
            bigquery.ScalarQueryParameter("start", "DATE", start),
            bigquery.ScalarQueryParameter("end", "DATE", end),
        ],
    )
    client.query(rewrite_sql, job_config=query_config).result()


def main() -> None:
    parser = argparse.ArgumentParser(description="Kursy NBP (tabela A) -> BigQuery")
    parser.add_argument("--project", required=True, help="ID projektu GCP")
    parser.add_argument("--dataset", default="raw_nbp")
    parser.add_argument("--start", required=True, type=date.fromisoformat)
    parser.add_argument("--end", type=date.fromisoformat, default=date.today())
    args = parser.parse_args()

    loaded_at = datetime.now(timezone.utc)
    rows = []
    for window_start, window_end in split_windows(args.start, args.end):
        tables = fetch_window(window_start, window_end)
        print(f"{window_start}..{window_end}: {len(tables)} dni notowań")
        rows.extend(to_rows(tables, loaded_at))

    if not rows:
        print("Brak notowań w zakresie — nic do załadowania.")
        return

    load_to_bigquery(rows, args.project, args.dataset, args.start, args.end)
    print(f"Załadowano {len(rows)} wierszy do {args.project}.{args.dataset}.{TARGET_TABLE}")


if __name__ == "__main__":
    main()
