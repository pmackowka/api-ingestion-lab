"""Wspólny zapis do BigQuery: podmiana zakresu dat w tabeli docelowej.

Wydzielone przy trzecim źródle (NBP, pogoda, GA4) — wtedy było już widać, że różnią się tylko:
nazwa tabeli, schemat i kolumna z datą. Pełne wyjaśnienie strategii i diagram: README.md (sekcja „Jak dane trafiają do BigQuery”).
"""

from datetime import date

from google.cloud import bigquery

# Lokalizacja wszystkich datasetów. EU, bo polityka prywatności pmdata.pl obiecuje przechowywanie danych w UE.
# Lokalizacji datasetu nie da się zmienić po utworzeniu — bez jawnego location BigQuery tworzy dataset w US.
LOCATION = "EU"


def _client_with_dataset(project: str, dataset: str) -> bigquery.Client:
    """Klient BigQuery + dataset w EU (tworzony przy pierwszym uruchomieniu). Wspólne dla obu strategii zapisu."""
    # location w kliencie: zadania (load, query) wykonują się w tej samej lokalizacji co dane.
    client = bigquery.Client(project=project, location=LOCATION)

    # exists_ok=True: pierwsze uruchomienie tworzy dataset, kolejne niczego nie zmieniają.
    dataset_ref = bigquery.Dataset(f"{project}.{dataset}")
    dataset_ref.location = LOCATION
    existing = client.create_dataset(dataset_ref, exists_ok=True)
    # exists_ok zwraca istniejący dataset bez sprawdzania lokalizacji — dataset sprzed tej zmiany (US)
    # przeszedłby po cichu. Przerywamy, zamiast pisać dane poza UE.
    if existing.location != LOCATION:
        raise RuntimeError(
            f"Dataset {project}.{dataset} jest w {existing.location}, oczekiwano {LOCATION}. "
            "Lokalizacji nie da się zmienić: usuń dataset (bq rm -r -f) i uruchom backfill od nowa."
        )
    return client


def replace_table(
    rows: list[dict],
    *,
    project: str,
    dataset: str,
    table: str,
    schema: list[bigquery.SchemaField],
) -> None:
    """Pełne przeładowanie: tabela po zapisie zawiera dokładnie `rows` — migawkę źródła z tej chwili.

    Dla rekordów zmienialnych (kontakty w CRM): rekord poprawiony albo usunięty w źródle zmienia się
    też w tabeli, bez klucza i bez DML. Podmiana zakresu dat tu nie pasuje — rekord nie ma jednej
    „swojej” daty, a zmieniony wczoraj kontakt z 2025 roku trafiłby do tabeli drugi raz.
    """
    client = _client_with_dataset(project, dataset)
    # Bez stagingu: pojedynczy load job z WRITE_TRUNCATE jest atomowy — błąd (np. NULL w REQUIRED)
    # zostawia poprzednią wersję tabeli. Staging jest potrzebny dopiero, gdy wynik skleja się z tym,
    # co już jest w tabeli (replace_date_range niżej).
    load_config = bigquery.LoadJobConfig(
        schema=schema,
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
    )
    client.load_table_from_json(rows, f"{project}.{dataset}.{table}", job_config=load_config).result()


def replace_date_range(
    rows: list[dict],
    *,
    project: str,
    dataset: str,
    table: str,
    schema: list[bigquery.SchemaField],
    date_column: str,
    start: date,
    end: date,
) -> None:
    """Zapisuje wiersze tak, żeby zakres [start, end] w tabeli docelowej został podmieniony w całości.

    Idempotencja: dwa uruchomienia dla tego samego zakresu dają ten sam stan tabeli, bez duplikatów.
    Argumenty po `*` tylko z nazwą: przy 8 parametrach pomyłka kolejności (np. start z end) byłaby niewidoczna.
    """
    client = _client_with_dataset(project, dataset)
    target = f"{project}.{dataset}.{table}"
    # Podkreślnik na początku: tabela techniczna, nie do czytania przez analityków.
    staging = f"{project}.{dataset}._staging_{table}"
    client.create_table(bigquery.Table(target, schema=schema), exists_ok=True)

    # Krok A: load do staging.
    # Po co staging: dane z API najpierw lądują w BigQuery "obok", a dopiero potem jednym
    # atomowym zapytaniem trafiają do tabeli docelowej. Gdy load padnie (np. NULL w kolumnie
    # REQUIRED), tabela docelowa zostaje nietknięta.
    # WRITE_TRUNCATE: staging zawiera zawsze tylko dane bieżącego uruchomienia.
    load_config = bigquery.LoadJobConfig(
        schema=schema,
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
    )
    client.load_table_from_json(rows, staging, job_config=load_config).result()

    # Krok B: przepisanie tabeli docelowej jednym query jobem.
    # Wynik = stare wiersze SPOZA zakresu + wszystkie wiersze ze staging. Wiersze z zakresu
    # [start, end] są więc wymieniane w całości — także te, których źródło już nie zwraca.
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
    # @start/@end jako parametry zapytania: BigQuery sam pilnuje typu DATE i nie ma ryzyka
    # wstrzyknięcia SQL. Nazwy tabel i date_column w f-stringu, bo parametrem nie da się podać
    # identyfikatora — to stałe z kodu, nie dane od użytkownika.
    rewrite_sql = f"""
        SELECT * FROM `{target}`
        WHERE {date_column} NOT BETWEEN @start AND @end
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
