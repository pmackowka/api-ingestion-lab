"""Generator faktur: wygrane deale z HubSpota (BigQuery) -> zaksięgowane faktury sprzedaży w Odoo."""

import argparse
import random
from datetime import date, timedelta
from decimal import Decimal

from google.cloud import bigquery

from common import cli
from common.bigquery import LOCATION
from odoo.api import make_client

SERVICE_TAX_NAME = "23% S"
SEED = 20261119
PAY_RATE = 0.8
DAYS_TO_PAY = (3, 45)
EUR_RATE = 0.3


def fetch_won_deals(client: bigquery.Client, project: str, dataset: str, start: date, end: date) -> list[dict]:
    """Wygrane deale z kontaktem, zamknięte w [start, end], od najstarszego; eur_mid = kurs NBP z ostatniego dnia przed zamknięciem."""
    sql = f"""
        SELECT d.deal_key, d.amount, DATE(d.closedate) AS close_date, c.email, c.firstname, c.lastname,
            ARRAY_AGG(r.mid IGNORE NULLS ORDER BY r.effective_date DESC LIMIT 1)[SAFE_OFFSET(0)] AS eur_mid
        FROM `{project}.{dataset}.deals` AS d
        JOIN `{project}.{dataset}.contacts` AS c USING (contact_id)
        LEFT JOIN `{project}.raw_nbp.exchange_rates_a` AS r
            ON r.currency_code = 'EUR' AND r.effective_date < DATE(d.closedate)
        WHERE d.dealstage = 'closedwon' AND d.deal_key IS NOT NULL
          AND DATE(d.closedate) BETWEEN @start AND @end
        GROUP BY d.deal_key, d.amount, close_date, c.email, c.firstname, c.lastname
        ORDER BY close_date, d.deal_key
    """
    config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("start", "DATE", start),
            bigquery.ScalarQueryParameter("end", "DATE", end),
        ]
    )
    return [dict(row) for row in client.query(sql, job_config=config).result()]


def invoice_currency(deal: dict, seed: int = SEED) -> str:
    """EUR dla części deali (stały seed), o ile znany jest kurs NBP; reszta PLN."""
    is_eur = random.Random(f"{seed}:currency:{deal['deal_key']}").random() < EUR_RATE
    return "EUR" if is_eur and deal.get("eur_mid") else "PLN"


def build_invoice(deal: dict, partner_id: int, tax_id: int, eur_id: int | None = None) -> dict:
    """Deal -> wartości faktury Odoo (account.move); w EUR kwota deala w PLN przeliczona kursem NBP."""
    vals = {
        "move_type": "out_invoice",
        "partner_id": partner_id,
        "invoice_date": deal["close_date"].isoformat(),
        "ref": deal["deal_key"],
    }
    price = Decimal(deal["amount"])
    if invoice_currency(deal) == "EUR":
        vals["currency_id"] = eur_id
        price = (price / Decimal(deal["eur_mid"])).quantize(Decimal("0.01"))
    vals["invoice_line_ids"] = [
        [0, 0, {
            "name": f"Usługi analityczne ({deal['deal_key']})",
            "quantity": 1,
            "price_unit": float(price),
            "tax_ids": [[6, 0, [tax_id]]],
        }]
    ]
    return vals


def payment_date(deal_key: str, invoice_date: date, today: date, seed: int = SEED) -> date | None:
    """Data zapłaty faktury albo None (jeszcze nie zapłacona / nigdy)."""
    rng = random.Random(f"{seed}:pay:{deal_key}")
    pays = rng.random() < PAY_RATE
    paid_on = invoice_date + timedelta(days=rng.randint(*DAYS_TO_PAY))
    return paid_on if pays and paid_on <= today else None


def register_payments(odoo, today: date) -> int:
    """Płatności do niezapłaconych faktur, których data zapłaty już minęła."""
    unpaid = odoo.call(
        "account.move", "search_read",
        domain=[["move_type", "=", "out_invoice"], ["state", "=", "posted"], ["payment_state", "=", "not_paid"]],
        fields=["ref", "invoice_date"], order="invoice_date, id",
    )
    count = 0
    for inv in unpaid:
        paid_on = inv["ref"] and payment_date(inv["ref"], date.fromisoformat(inv["invoice_date"]), today)
        if not paid_on:
            continue
        context = {"active_model": "account.move", "active_ids": [inv["id"]]}
        [wizard] = odoo.call("account.payment.register", "create", vals_list=[{"payment_date": paid_on.isoformat()}], context=context)
        odoo.call("account.payment.register", "action_create_payments", ids=[wizard], context=context)
        count += 1
    return count


def ensure_partners(odoo, deals: list[dict]) -> dict[str, int]:
    """Klienci po e-mailu: istniejący z Odoo, brakujący tworzeni jedną paczką."""
    emails = sorted({d["email"] for d in deals})
    found = odoo.call("res.partner", "search_read", domain=[["email", "in", emails]], fields=["email"])
    ids = {p["email"]: p["id"] for p in found}
    missing = [d for d in {d["email"]: d for d in deals}.values() if d["email"] not in ids]
    if missing:
        vals = [{"name": f"{d['firstname']} {d['lastname']}", "email": d["email"]} for d in missing]
        created = odoo.call("res.partner", "create", vals_list=vals)
        ids.update(zip([d["email"] for d in missing], created))
    return ids


def ensure_eur(odoo) -> int:
    """Włącza walutę EUR (w nowej bazie Odoo nieaktywna) i zwraca jej ID."""
    [eur] = odoo.call("res.currency", "search_read", domain=[["name", "=", "EUR"]], fields=["active"], context={"active_test": False})
    if not eur["active"]:
        odoo.call("res.currency", "write", ids=[eur["id"]], vals={"active": True})
    return eur["id"]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Wspólny interfejs CLI; --dataset wskazuje tu źródło (dataset HubSpota), nie cel."""
    return cli.parse(cli.make_parser("HubSpot (BigQuery) -> faktury w Odoo", default_dataset="raw_hubspot"), argv)


def main() -> None:
    args = parse_args()
    client = bigquery.Client(project=args.project, location=LOCATION)
    deals = fetch_won_deals(client, args.project, args.dataset, args.start, args.end)

    odoo = make_client()
    existing = odoo.call(
        "account.move", "search_read",
        domain=[["move_type", "=", "out_invoice"], ["ref", "in", [d["deal_key"] for d in deals]]], fields=["ref"],
    )
    done = {m["ref"] for m in existing}
    new = [d for d in deals if d["deal_key"] not in done]
    if new:
        create_invoices(odoo, new)
    payments = register_payments(odoo, today=args.end)
    print(f"Odoo: {len(new)} nowych faktur, {len(done)} już było ({args.start}..{args.end}); {payments} nowych płatności")


def create_invoices(odoo, new: list[dict]) -> None:
    """Klienci + faktury + księgowanie, dla deali bez faktury."""
    [tax] = odoo.call("account.tax", "search_read", domain=[["type_tax_use", "=", "sale"], ["name", "=", SERVICE_TAX_NAME]], fields=["id"])
    partners = ensure_partners(odoo, new)
    eur_id = ensure_eur(odoo)
    move_ids = odoo.call("account.move", "create", vals_list=[build_invoice(d, partners[d["email"]], tax["id"], eur_id) for d in new])
    odoo.call("account.move", "action_post", ids=move_ids)


if __name__ == "__main__":
    main()
