"""Kursy średnie NBP (tabela A) -> BigQuery.

Uruchomienie:
    uv run python nbp/ingest.py --project <projekt-gcp> --start 2026-01-01 --end 2026-03-31   # backfill
    uv run python nbp/ingest.py --project <projekt-gcp> --lookback-days 7                    # harmonogram
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
# Podkreślnik na początku: tabela techniczna, nie do czytania przez analityków.
STAGING_TABLE = "_staging_exchange_rates_a"

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
    uruchomieniem. Ten sam wzorzec (pętla po kawałkach zakresu) wraca przy paginacji w etapie 2.
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


def load_to_bigquery(rows: list[dict], project: str, dataset: str, start: date, end: date) -> None:
    """Krok 4: zapisuje wiersze tak, żeby zakres [start, end] w tabeli docelowej został podmieniony w całości.

    Idempotencja: dwa uruchomienia dla tego samego zakresu dają ten sam stan tabeli, bez duplikatów.
    """
    client = bigquery.Client(project=project)

    # exists_ok=True: pierwsze uruchomienie tworzy dataset i tabelę, kolejne niczego nie zmieniają.
    client.create_dataset(f"{project}.{dataset}", exists_ok=True)
    target = f"{project}.{dataset}.{TARGET_TABLE}"
    staging = f"{project}.{dataset}.{STAGING_TABLE}"
    client.create_table(bigquery.Table(target, schema=SCHEMA), exists_ok=True)

    # Krok 4a: load do staging.
    # Po co staging: dane z API najpierw lądują w BigQuery "obok", a dopiero potem jednym
    # atomowym zapytaniem trafiają do tabeli docelowej. Gdy load padnie (np. NULL w kolumnie
    # REQUIRED), tabela docelowa zostaje nietknięta.
    # WRITE_TRUNCATE: staging zawiera zawsze tylko dane bieżącego uruchomienia.
    load_config = bigquery.LoadJobConfig(
        schema=SCHEMA,
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
    )
    client.load_table_from_json(rows, staging, job_config=load_config).result()

    # Krok 4b: przepisanie tabeli docelowej jednym query jobem.
    # Porównanie z innymi strategiami (MERGE, append, partycje): nbp/README.md, "Strategie ładowania".
    # Wynik = stare wiersze SPOZA zakresu + wszystkie wiersze ze staging. Wiersze z zakresu
    # [start, end] są więc wymieniane w całości — także te, których NBP już nie zwraca.
    #
    # Dlaczego nie MERGE: projekt jest w sandboxie BigQuery, a sandbox odrzuca DML
    # (MERGE/INSERT/UPDATE/DELETE) błędem 403. Query job z tabelą docelową to nie DML, więc działa.
    #
    # Dlaczego to bezpieczne: zapytanie czyta tabelę docelową i ją nadpisuje, ale BigQuery
    # zapisuje wynik dopiero po zakończeniu zapytania, a cały job jest atomowy —
    # albo podmieni tabelę, albo zostawi ją bez zmian.
    #
    # WRITE_TRUNCATE_DATA zamiast WRITE_TRUNCATE: oba nadpisują dane, ale WRITE_TRUNCATE
    # bierze schemat z wyniku zapytania (kolumny stają się NULLABLE), a WRITE_TRUNCATE_DATA
    # zostawia schemat tabeli — REQUIRED zostaje.
    #
    # @start/@end jako parametry zapytania, nie f-string: BigQuery sam pilnuje typu DATE
    # i nie ma ryzyka wstrzyknięcia SQL.
    rewrite_sql = f"""
        SELECT * FROM `{target}`
        WHERE effective_date NOT BETWEEN @start AND @end
        UNION ALL
        SELECT * FROM `{staging}`
    """
    query_config = bigquery.QueryJobConfig(
        destination=target,
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE_DATA,
        query_parameters=[
            bigquery.ScalarQueryParameter("start", "DATE", start),
            bigquery.ScalarQueryParameter("end", "DATE", end),
        ],
    )
    client.query(rewrite_sql, job_config=query_config).result()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Czyta argumenty; początek zakresu podajesz datą (--start) albo liczbą dni wstecz (--lookback-days).

    Po co --lookback-days: harmonogram (cron, Cloud Run job) ma stałe argumenty, więc nie wpisze
    "dziś minus 7 dni" jako daty. Liczba dni jest stała, a data startu liczy się przy każdym uruchomieniu.
    """
    parser = argparse.ArgumentParser(description="Kursy NBP (tabela A) -> BigQuery")
    parser.add_argument("--project", required=True, help="ID projektu GCP")
    parser.add_argument("--dataset", default="raw_nbp")
    # type=date.fromisoformat: zła data (np. 2026-13-01) kończy się błędem argparse, zanim ruszy API.
    parser.add_argument("--end", type=date.fromisoformat, default=date.today())
    # Dokładnie jedno z dwóch: ręczny backfill od daty albo automatyczny lookback.
    start_group = parser.add_mutually_exclusive_group(required=True)
    start_group.add_argument("--start", type=date.fromisoformat)
    start_group.add_argument("--lookback-days", type=int, help="start = end minus tyle dni")
    args = parser.parse_args(argv)
    if args.lookback_days is not None:
        if args.lookback_days < 0:
            parser.error("--lookback-days nie może być ujemne")
        args.start = args.end - timedelta(days=args.lookback_days)
    return args


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

    # Krok 4: zapis do BigQuery z podmianą zakresu [start, end].
    load_to_bigquery(rows, args.project, args.dataset, args.start, args.end)
    print(f"Załadowano {len(rows)} wierszy do {args.project}.{args.dataset}.{TARGET_TABLE}")


if __name__ == "__main__":
    main()
