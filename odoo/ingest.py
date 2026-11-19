"""Faktury sprzedaży i płatności z Odoo JSON-2 API -> BigQuery (pełna migawka obu tabel).

Uruchomienie (klucz z .env, Odoo z odoo/docker-compose.yml):
    uv run --env-file .env python -m odoo.ingest --project <projekt-gcp> --lookback-days 7

Strategia jak w HubSpocie: pełne przeładowanie. Faktura jest rekordem zmienialnym — status płatności
(`payment_state`) zmienia się tygodnie po wystawieniu, więc data wystawienia nie wyznacza zakresu do podmiany.
Odoo działa lokalnie, więc ingest nie wchodzi do pipeline.yml — runner GitHuba go nie widzi.
"""

import argparse
from datetime import datetime, timezone
from decimal import Decimal

from google.cloud import bigquery

from common import cli
from common.bigquery import replace_table
from odoo.api import make_client

PAGE_SIZE = 100
INVOICE_FIELDS = [
    "name", "ref", "partner_id", "invoice_date", "invoice_date_due", "currency_id",
    "amount_untaxed", "amount_tax", "amount_total", "state", "payment_state", "create_date", "write_date",
]

PAYMENT_FIELDS = ["name", "date", "amount", "currency_id", "state", "payment_type", "reconciled_invoice_ids",
                  "create_date", "write_date"]

INVOICES_SCHEMA = [
    bigquery.SchemaField("invoice_id", "STRING", mode="REQUIRED"),
    # Numer nadawany przy księgowaniu (FV/2026/00001); szkic go nie ma.
    bigquery.SchemaField("invoice_number", "STRING", mode="NULLABLE"),
    # Pole `ref` faktury = deal_key z HubSpota — klucz złączenia HubSpot ↔ Odoo.
    bigquery.SchemaField("deal_key", "STRING", mode="NULLABLE"),
    bigquery.SchemaField("partner_id", "STRING", mode="NULLABLE"),
    bigquery.SchemaField("partner_name", "STRING", mode="NULLABLE"),
    bigquery.SchemaField("invoice_date", "DATE", mode="NULLABLE"),
    bigquery.SchemaField("due_date", "DATE", mode="NULLABLE"),
    bigquery.SchemaField("currency", "STRING", mode="NULLABLE"),
    bigquery.SchemaField("amount_untaxed", "NUMERIC", mode="REQUIRED"),
    bigquery.SchemaField("amount_tax", "NUMERIC", mode="REQUIRED"),
    bigquery.SchemaField("amount_total", "NUMERIC", mode="REQUIRED"),
    bigquery.SchemaField("state", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("payment_state", "STRING", mode="NULLABLE"),
    bigquery.SchemaField("created_at", "TIMESTAMP", mode="REQUIRED"),
    bigquery.SchemaField("updated_at", "TIMESTAMP", mode="REQUIRED"),
    bigquery.SchemaField("loaded_at", "TIMESTAMP", mode="REQUIRED"),
]

PAYMENTS_SCHEMA = [
    bigquery.SchemaField("payment_id", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("payment_number", "STRING", mode="NULLABLE"),
    # Faktura, którą płatność rozliczyła (najmniejsze ID, gdy kilka) — złączenie z invoices.
    bigquery.SchemaField("invoice_id", "STRING", mode="NULLABLE"),
    bigquery.SchemaField("payment_date", "DATE", mode="REQUIRED"),
    bigquery.SchemaField("amount", "NUMERIC", mode="REQUIRED"),
    bigquery.SchemaField("currency", "STRING", mode="NULLABLE"),
    bigquery.SchemaField("state", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("created_at", "TIMESTAMP", mode="REQUIRED"),
    bigquery.SchemaField("updated_at", "TIMESTAMP", mode="REQUIRED"),
    bigquery.SchemaField("loaded_at", "TIMESTAMP", mode="REQUIRED"),
]


def fetch_records(odoo, model: str, domain: list, fields: list[str], page_size: int = PAGE_SIZE) -> list[dict]:
    """Krok 1: wszystkie rekordy modelu, strona po stronie (search_read z limit/offset).

    Czwarty wzorzec końca paginacji w repo: Odoo nie podaje liczby rekordów ani kursora,
    więc koniec poznajemy po stronie krótszej niż limit (jak Search Console).
    order="id": stała kolejność, inaczej strony mogłyby się nakładać.
    """
    records, offset = [], 0
    while True:
        page = odoo.call(model, "search_read", domain=domain, fields=fields, limit=page_size, offset=offset, order="id")
        records.extend(page)
        if len(page) < page_size:
            return records
        offset += page_size


def _many2one(value) -> tuple[str | None, str | None]:
    """Relacja z Odoo to [id, nazwa], a pusta to False -> (id, nazwa) albo (None, None)."""
    return (str(value[0]), value[1]) if value else (None, None)


def _amount(value: float) -> str:
    """Kwota z JSON (float) -> tekst do NUMERIC; str(float) daje najkrótszy zapis, bez artefaktów binarnych."""
    return str(Decimal(str(value)))


def to_rows(invoices: list[dict], loaded_at: datetime) -> list[dict]:
    """Krok 2: faktura Odoo -> wiersz. False (pusta wartość w Odoo) -> None (NULL w BigQuery)."""
    rows = []
    for inv in invoices:
        partner_id, partner_name = _many2one(inv["partner_id"])
        rows.append(
            {
                "invoice_id": str(inv["id"]),
                "invoice_number": inv["name"] if inv["name"] and inv["name"] != "/" else None,
                "deal_key": inv["ref"] or None,
                "partner_id": partner_id,
                "partner_name": partner_name,
                "invoice_date": inv["invoice_date"] or None,
                "due_date": inv["invoice_date_due"] or None,
                "currency": _many2one(inv["currency_id"])[1],
                "amount_untaxed": _amount(inv["amount_untaxed"]),
                "amount_tax": _amount(inv["amount_tax"]),
                "amount_total": _amount(inv["amount_total"]),
                "state": inv["state"],
                "payment_state": inv["payment_state"] or None,
                # Odoo zwraca czas UTC bez strefy ("2026-11-19 13:40:00") — BigQuery czyta go jako UTC.
                "created_at": inv["create_date"],
                "updated_at": inv["write_date"],
                "loaded_at": loaded_at.isoformat(),
            }
        )
    return rows


def payments_to_rows(payments: list[dict], loaded_at: datetime) -> list[dict]:
    """Krok 2: płatność Odoo -> wiersz. reconciled_invoice_ids to lista ID (many2many), może być pusta."""
    return [
        {
            "payment_id": str(p["id"]),
            "payment_number": p["name"] or None,
            "invoice_id": str(min(p["reconciled_invoice_ids"])) if p["reconciled_invoice_ids"] else None,
            "payment_date": p["date"],
            "amount": _amount(p["amount"]),
            "currency": _many2one(p["currency_id"])[1],
            "state": p["state"],
            "created_at": p["create_date"],
            "updated_at": p["write_date"],
            "loaded_at": loaded_at.isoformat(),
        }
        for p in payments
    ]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Wspólny interfejs CLI; --start/--lookback-days przyjmowane, ale migawka obejmuje wszystkie rekordy."""
    return cli.parse(cli.make_parser("Odoo JSON-2 API -> BigQuery", default_dataset="raw_odoo"), argv)


def main() -> None:
    args = parse_args()
    odoo = make_client()
    loaded_at = datetime.now(timezone.utc)
    invoices = to_rows(fetch_records(odoo, "account.move", [["move_type", "=", "out_invoice"]], INVOICE_FIELDS), loaded_at)
    # Tylko wpłaty od klientów; zwroty i płatności dostawcom to payment_type outbound.
    payments = payments_to_rows(
        fetch_records(odoo, "account.payment", [["payment_type", "=", "inbound"]], PAYMENT_FIELDS), loaded_at
    )
    replace_table(invoices, project=args.project, dataset=args.dataset, table="invoices", schema=INVOICES_SCHEMA)
    replace_table(payments, project=args.project, dataset=args.dataset, table="payments", schema=PAYMENTS_SCHEMA)
    print(f"invoices: {len(invoices)}, payments: {len(payments)} (pełna migawka)")


if __name__ == "__main__":
    main()
