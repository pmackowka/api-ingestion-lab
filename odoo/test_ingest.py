from datetime import date, datetime, timezone
from decimal import Decimal

from odoo.generate import build_invoice, payment_date
from odoo.ingest import fetch_records, payments_to_rows, to_rows

LOADED_AT = datetime(2026, 11, 19, 12, 0, tzinfo=timezone.utc)


class _FakeOdoo:
    """Atrapa klienta: search_read stronami po limit/offset, zapamiętuje offsety."""

    def __init__(self, records):
        self.records, self.offsets = records, []

    def call(self, model, method, **params):
        self.offsets.append(params["offset"])
        return self.records[params["offset"] : params["offset"] + params["limit"]]


def _invoice(**overrides) -> dict:
    base = {
        "id": 7, "name": "FV/2026/00001", "ref": "deal-20260603-001", "partner_id": [12, "Anna Nowak"],
        "invoice_date": "2026-06-10", "invoice_date_due": "2026-06-24", "currency_id": [17, "PLN"],
        "amount_untaxed": 10000.0, "amount_tax": 2300.0, "amount_total": 12300.0, "state": "posted",
        "payment_state": "not_paid", "create_date": "2026-11-19 13:40:00", "write_date": "2026-11-19 13:40:01",
    }
    return {**base, **overrides}


def test_build_invoice_uses_deal_key_date_and_net_amount():
    deal = {"deal_key": "deal-20260603-001", "amount": Decimal("10000"), "close_date": date(2026, 6, 10)}

    vals = build_invoice(deal, partner_id=12, tax_id=8)

    assert (vals["ref"], vals["invoice_date"], vals["partner_id"]) == ("deal-20260603-001", "2026-06-10", 12)
    [[command, _, line]] = vals["invoice_line_ids"]
    assert command == 0 and line["price_unit"] == 10000.0 and line["tax_ids"] == [[6, 0, [8]]]


def test_fetch_records_stops_on_short_page():
    odoo = _FakeOdoo([_invoice(id=i) for i in range(5)])

    assert len(fetch_records(odoo, "account.move", [], ["name"], page_size=2)) == 5
    assert odoo.offsets == [0, 2, 4]


def test_to_rows_maps_many2one_false_and_draft_number():
    draft = _invoice(name="/", ref=False, partner_id=False, invoice_date=False)

    posted, row = to_rows([_invoice(), draft], LOADED_AT)

    assert (posted["partner_id"], posted["partner_name"], posted["currency"]) == ("12", "Anna Nowak", "PLN")
    assert posted["amount_tax"] == "2300.0"
    assert row["invoice_number"] is None and row["deal_key"] is None and row["partner_id"] is None
    assert row["invoice_date"] is None


def test_payment_date_is_stable_and_waits_for_today():
    keys = [f"deal-20260101-{n:03d}" for n in range(1, 101)]
    issued = date(2026, 1, 1)

    late = {k: payment_date(k, issued, today=date(2026, 12, 31)) for k in keys}
    early = {k: payment_date(k, issued, today=date(2026, 1, 2)) for k in keys}

    paid = {k: d for k, d in late.items() if d}
    # Część faktur nigdy nie zapłacona, część zapłacona w oknie 3–45 dni; przed zapłatą — None.
    assert 0 < len(paid) < len(keys)
    assert all(date(2026, 1, 4) <= d <= date(2026, 2, 15) for d in paid.values())
    assert all(d is None for d in early.values())
    assert payment_date(keys[0], issued, today=date(2026, 12, 31)) == late[keys[0]]


def test_payments_to_rows_maps_reconciled_invoice():
    base = {"id": 5, "name": "PBNK1/2026/00005", "date": "2026-10-15", "amount": 9840.0, "currency_id": [17, "PLN"],
            "state": "reconciled", "create_date": "2026-11-19 13:50:00", "write_date": "2026-11-19 13:50:00"}

    paid, unlinked = payments_to_rows([{**base, "reconciled_invoice_ids": [9, 6]}, {**base, "reconciled_invoice_ids": []}], LOADED_AT)

    assert (paid["invoice_id"], paid["amount"], paid["payment_date"]) == ("6", "9840.0", "2026-10-15")
    assert unlinked["invoice_id"] is None
