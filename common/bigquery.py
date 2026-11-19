"""Wspólny zapis do BigQuery: podmiana zakresu dat w tabeli docelowej."""

from datetime import date

from google.cloud import bigquery

LOCATION = "EU"


def _client_with_dataset(project: str, dataset: str) -> bigquery.Client:
    """Klient BigQuery + dataset w EU (tworzony przy pierwszym uruchomieniu)."""
    client = bigquery.Client(project=project, location=LOCATION)

    dataset_ref = bigquery.Dataset(f"{project}.{dataset}")
    dataset_ref.location = LOCATION
    existing = client.create_dataset(dataset_ref, exists_ok=True)
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
    """Pełne przeładowanie: tabela po zapisie zawiera dokładnie `rows` — migawkę źródła z tej chwili."""
    client = _client_with_dataset(project, dataset)
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
    """Zapisuje wiersze tak, żeby zakres [start, end] w tabeli docelowej został podmieniony w całości."""
    client = _client_with_dataset(project, dataset)
    target = f"{project}.{dataset}.{table}"
    staging = f"{project}.{dataset}._staging_{table}"
    client.create_table(bigquery.Table(target, schema=schema), exists_ok=True)

    load_config = bigquery.LoadJobConfig(
        schema=schema,
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
    )
    client.load_table_from_json(rows, staging, job_config=load_config).result()

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
