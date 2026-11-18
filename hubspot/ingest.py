"""Kontakty z HubSpot CRM API -> BigQuery (pełna migawka).

Uruchomienie (token z .env):
    uv run --env-file .env python -m hubspot.ingest --project <projekt-gcp> --lookback-days 7

Strategia inna niż w pozostałych źródłach: pełne przeładowanie zamiast podmiany zakresu dat.
Kontakt w CRM to rekord zmienialny — dziś poprawiony kontakt z 2025 roku nie ma jednej „swojej” daty,
po której dałoby się podmienić zakres. Właściwy mechanizm to upsert po kluczu (MERGE), ale sandbox
BigQuery nie ma DML. Przy setkach kontaktów pełna migawka jest tania i łapie też usunięcia.
"""

import argparse
from datetime import datetime, timezone

from google.cloud import bigquery

from common import cli
from common.bigquery import replace_table
from hubspot.api import API, API_VERSION, make_session

TARGET_TABLE = "contacts"
# Maksimum API dla listy obiektów; kolejne strony przez kursor `after`.
PAGE_SIZE = 100
# Właściwości do pobrania — bez listy API oddaje tylko kilka domyślnych.
PROPERTIES = ["email", "firstname", "lastname", "lead_source", "lead_event", "lead_date"]

SCHEMA = [
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


def fetch_contacts(session, page_size: int = PAGE_SIZE) -> list[dict]:
    """Krok 1: wszystkie kontakty, strona po stronie (paginacja kursorem).

    Trzeci wzorzec paginacji w repo: GA4 podaje rowCount, Search Console — krótszą stronę,
    a HubSpot — kursor `paging.next.after`. Brak `paging` = ostatnia strona.
    Kursor zamiast offsetu: nowy kontakt dodany w trakcie pobierania nie przesuwa stron.
    """
    url = f"{API}/crm/objects/{API_VERSION}/contacts"
    params = {"limit": page_size, "properties": ",".join(PROPERTIES)}
    contacts = []
    while True:
        response = session.get(url, params=params, timeout=60)
        response.raise_for_status()
        payload = response.json()
        contacts.extend(payload.get("results", []))
        after = payload.get("paging", {}).get("next", {}).get("after")
        if not after:
            return contacts
        params["after"] = after


def to_rows(contacts: list[dict], loaded_at: datetime) -> list[dict]:
    """Krok 2: obiekt API -> wiersz. Właściwości przychodzą jako tekst; pusta = None (NULL w BigQuery)."""
    rows = []
    for contact in contacts:
        props = contact.get("properties", {})
        rows.append(
            {
                "contact_id": contact["id"],
                **{name: props.get(name) or None for name in PROPERTIES},
                "created_at": contact["createdAt"],
                "updated_at": contact["updatedAt"],
                "loaded_at": loaded_at.isoformat(),
            }
        )
    return rows


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Wspólny interfejs CLI, żeby HubSpot działał w tej samej macierzy co inne źródła.

    --start/--lookback-days są przyjmowane, ale nie zawężają pobrania: migawka zawsze obejmuje wszystkie kontakty.
    """
    return cli.parse(cli.make_parser("HubSpot CRM API -> BigQuery", default_dataset="raw_hubspot"), argv)


def main() -> None:
    args = parse_args()
    rows = to_rows(fetch_contacts(make_session()), datetime.now(timezone.utc))
    replace_table(rows, project=args.project, dataset=args.dataset, table=TARGET_TABLE, schema=SCHEMA)
    print(f"{TARGET_TABLE}: {len(rows)} kontaktów (pełna migawka)")


if __name__ == "__main__":
    main()
