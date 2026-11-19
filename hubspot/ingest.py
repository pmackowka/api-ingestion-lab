"""Kontakty i deale z HubSpot CRM API -> BigQuery (pełna migawka obu tabel).

Uruchomienie (token z .env):
    uv run --env-file .env python -m hubspot.ingest --project <projekt-gcp> --lookback-days 7

Strategia inna niż w pozostałych źródłach: pełne przeładowanie zamiast podmiany zakresu dat.
Kontakt i deal w CRM to rekordy zmienialne — dziś wygrany deal z 2025 roku nie ma jednej „swojej” daty,
po której dałoby się podmienić zakres. Właściwy mechanizm to upsert po kluczu (MERGE), ale sandbox
BigQuery nie ma DML. Przy setkach rekordów pełna migawka jest tania i łapie też usunięcia.
"""

import argparse
from datetime import datetime, timezone

from google.cloud import bigquery

from common import cli
from common.bigquery import replace_table
from hubspot.api import API, API_VERSION, make_session

# Maksimum API dla listy obiektów; kolejne strony przez kursor `after`.
PAGE_SIZE = 100
# Właściwości do pobrania — bez listy API oddaje tylko kilka domyślnych.
CONTACT_PROPERTIES = ["email", "firstname", "lastname", "lead_source", "lead_event", "lead_date"]
DEAL_PROPERTIES = ["deal_key", "dealname", "pipeline", "dealstage", "amount", "closedate"]

CONTACTS_SCHEMA = [
    bigquery.SchemaField("contact_id", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("email", "STRING", mode="NULLABLE"),
    bigquery.SchemaField("firstname", "STRING", mode="NULLABLE"),
    bigquery.SchemaField("lastname", "STRING", mode="NULLABLE"),
    # NULLABLE: kontakt dodany ręcznie w HubSpocie nie ma właściwości z generatora.
    bigquery.SchemaField("lead_source", "STRING", mode="NULLABLE"),
    bigquery.SchemaField("lead_event", "STRING", mode="NULLABLE"),
    bigquery.SchemaField("lead_date", "DATE", mode="NULLABLE"),
    bigquery.SchemaField("created_at", "TIMESTAMP", mode="REQUIRED"),
    bigquery.SchemaField("updated_at", "TIMESTAMP", mode="REQUIRED"),
    bigquery.SchemaField("loaded_at", "TIMESTAMP", mode="REQUIRED"),
]

DEALS_SCHEMA = [
    bigquery.SchemaField("deal_id", "STRING", mode="REQUIRED"),
    # NULLABLE: deal założony ręcznie w HubSpocie nie ma klucza generatora.
    bigquery.SchemaField("deal_key", "STRING", mode="NULLABLE"),
    bigquery.SchemaField("dealname", "STRING", mode="NULLABLE"),
    bigquery.SchemaField("pipeline", "STRING", mode="NULLABLE"),
    bigquery.SchemaField("dealstage", "STRING", mode="NULLABLE"),
    # NUMERIC, nie FLOAT64: kwota to wartość dziesiętna (konwencja repo).
    bigquery.SchemaField("amount", "NUMERIC", mode="NULLABLE"),
    bigquery.SchemaField("closedate", "TIMESTAMP", mode="NULLABLE"),
    # Pierwszy powiązany kontakt — klucz złączenia z contacts (a przez lead_source z GA4).
    bigquery.SchemaField("contact_id", "STRING", mode="NULLABLE"),
    bigquery.SchemaField("created_at", "TIMESTAMP", mode="REQUIRED"),
    bigquery.SchemaField("updated_at", "TIMESTAMP", mode="REQUIRED"),
    bigquery.SchemaField("loaded_at", "TIMESTAMP", mode="REQUIRED"),
]


def fetch_objects(session, object_type: str, properties: list[str], associations: str | None = None,
                  page_size: int = PAGE_SIZE) -> list[dict]:
    """Krok 1: wszystkie rekordy obiektu, strona po stronie (paginacja kursorem).

    Trzeci wzorzec paginacji w repo: GA4 podaje rowCount, Search Console — krótszą stronę,
    a HubSpot — kursor `paging.next.after`. Brak `paging` = ostatnia strona.
    Kursor zamiast offsetu: nowy rekord dodany w trakcie pobierania nie przesuwa stron.
    `associations` (np. "contacts"): ID powiązanych rekordów w tej samej odpowiedzi, bez osobnych zapytań.
    """
    url = f"{API}/crm/objects/{API_VERSION}/{object_type}"
    params = {"limit": page_size, "properties": ",".join(properties)}
    if associations:
        params["associations"] = associations
    records = []
    while True:
        response = session.get(url, params=params, timeout=60)
        response.raise_for_status()
        payload = response.json()
        records.extend(payload.get("results", []))
        after = payload.get("paging", {}).get("next", {}).get("after")
        if not after:
            return records
        params["after"] = after


def _base_row(record: dict, id_column: str, properties: list[str], loaded_at: datetime) -> dict:
    """Wspólne pola wiersza. Właściwości przychodzą jako tekst; pusta = None (NULL w BigQuery)."""
    props = record.get("properties", {})
    return {
        id_column: record["id"],
        **{name: props.get(name) or None for name in properties},
        "created_at": record["createdAt"],
        "updated_at": record["updatedAt"],
        "loaded_at": loaded_at.isoformat(),
    }


def to_rows(contacts: list[dict], loaded_at: datetime) -> list[dict]:
    """Krok 2: kontakt z API -> wiersz tabeli contacts."""
    return [_base_row(c, "contact_id", CONTACT_PROPERTIES, loaded_at) for c in contacts]


def deals_to_rows(deals: list[dict], loaded_at: datetime) -> list[dict]:
    """Krok 2: deal z API -> wiersz tabeli deals, z ID pierwszego powiązanego kontaktu.

    Deal może mieć kilka kontaktów; generator tworzy dokładnie jeden. Przy wielu bierzemy najmniejsze ID
    (deterministycznie) — model w dbt z wieloma kontaktami na deal potrzebowałby osobnej tabeli powiązań.
    """
    rows = []
    for deal in deals:
        row = _base_row(deal, "deal_id", DEAL_PROPERTIES, loaded_at)
        contacts = deal.get("associations", {}).get("contacts", {}).get("results", [])
        row["contact_id"] = min((c["id"] for c in contacts), key=int, default=None)
        rows.append(row)
    return rows


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Wspólny interfejs CLI, żeby HubSpot działał w tej samej macierzy co inne źródła.

    --start/--lookback-days są przyjmowane, ale nie zawężają pobrania: migawka zawsze obejmuje wszystkie rekordy.
    """
    return cli.parse(cli.make_parser("HubSpot CRM API -> BigQuery", default_dataset="raw_hubspot"), argv)


def main() -> None:
    args = parse_args()
    session = make_session()
    loaded_at = datetime.now(timezone.utc)

    contacts = to_rows(fetch_objects(session, "contacts", CONTACT_PROPERTIES), loaded_at)
    deals = deals_to_rows(fetch_objects(session, "deals", DEAL_PROPERTIES, associations="contacts"), loaded_at)

    replace_table(contacts, project=args.project, dataset=args.dataset, table="contacts", schema=CONTACTS_SCHEMA)
    replace_table(deals, project=args.project, dataset=args.dataset, table="deals", schema=DEALS_SCHEMA)
    print(f"contacts: {len(contacts)}, deals: {len(deals)} (pełna migawka)")


if __name__ == "__main__":
    main()
