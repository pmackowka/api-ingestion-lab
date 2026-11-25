from collections import Counter
from datetime import date, datetime, timezone

from hubspot.generate import build_deals, build_leads, upsert
from hubspot.ingest import deals_to_rows, fetch_objects, to_rows

LOADED_AT = datetime(2026, 11, 18, 12, 0, tzinfo=timezone.utc)


class _Response:
    def __init__(self, body=None):
        self.body = body or {}

    def raise_for_status(self):
        pass

    def json(self):
        return self.body


class _FakeSession:
    """Atrapa API: lista kontaktów stronami z kursorem `after`; zapamiętuje wysłane paczki."""

    def __init__(self, contacts=()):
        self.contacts, self.afters, self.batches = list(contacts), [], []

    def get(self, url, params, timeout):
        start = int(params.get("after", 0))
        self.afters.append(params.get("after"))
        page = self.contacts[start : start + params["limit"]]
        body = {"results": page}
        if start + params["limit"] < len(self.contacts):
            body["paging"] = {"next": {"after": str(start + params["limit"])}}
        return _Response(body)

    def post(self, url, json, timeout):
        self.batches.append(json["inputs"])
        results = [{"id": f"id-{item['id']}", "properties": item["properties"]} for item in json["inputs"]]
        return _Response({"results": results})


def _click(day: str, source: str, clicks: int) -> dict:
    return {"report_date": date.fromisoformat(day), "session_source": source, "session_medium": "organic",
            "event_name": "phone_reveal", "clicks": clicks}


def test_build_leads_is_deterministic_and_per_day():
    clicks = [_click("2026-11-01", "google", 20), _click("2026-11-02", "bing", 20)]

    full = build_leads(clicks)
    only_second_day = build_leads(clicks[1:])

    assert build_leads(clicks) == full
    assert [lead for lead in full if lead["lead_date"] == "2026-11-02"] == only_second_day


def test_build_leads_inherits_source_and_rate_bounds():
    leads = build_leads([_click("2026-11-01", "google", 10)], rate=1.0)

    assert len(leads) == 10
    assert Counter(lead["lead_source"] for lead in leads) == {"google / organic": 10}
    assert leads[0]["email"] == "lead-20261101-001@example.com"
    assert build_leads([_click("2026-11-01", "google", 10)], rate=0.0) == []


def test_upsert_batches_by_limit_and_maps_key_to_id():
    session = _FakeSession()
    leads = build_leads([_click("2026-11-01", "google", 5)], rate=1.0)

    ids = upsert(session, "contacts", leads, id_property="email", batch_size=2)

    assert [len(batch) for batch in session.batches] == [2, 2, 1]
    assert session.batches[0][0]["idProperty"] == "email"
    assert ids["lead-20261101-001@example.com"] == "id-lead-20261101-001@example.com"


def test_build_deals_stage_depends_only_on_date():
    leads = build_leads([_click("2026-01-01", "google", 200)], rate=1.0)

    early = build_deals(leads, today=date(2026, 1, 2))
    late = build_deals(leads, today=date(2026, 12, 31))

    assert [d["properties"]["deal_key"] for d in early] == [d["properties"]["deal_key"] for d in late]
    assert [d["properties"]["amount"] for d in early] == [d["properties"]["amount"] for d in late]
    assert all(d["properties"]["dealstage"] not in ("closedwon", "closedlost") for d in early)
    assert {d["properties"]["dealstage"] for d in late} == {"closedwon", "closedlost"}
    assert len({d["properties"]["deal_key"] for d in late}) == len(late) > 0


def test_build_deals_skips_test_sources():
    real = build_leads([_click("2026-01-01", "google", 200)], rate=1.0)
    test = build_leads([_click("2026-01-02", "tagassistant.google.com", 200)], rate=1.0)

    deals = build_deals(real + test, today=date(2026, 12, 31))

    assert deals == build_deals(real, today=date(2026, 12, 31))
    assert len(deals) > 0


def test_fetch_objects_follows_cursor_until_no_paging():
    contacts = [{"id": str(i), "properties": {}, "createdAt": "x", "updatedAt": "y"} for i in range(5)]
    session = _FakeSession(contacts)

    assert len(fetch_objects(session, "contacts", ["email"], page_size=2)) == 5
    assert session.afters == [None, "2", "4"]


def test_to_rows_maps_empty_properties_to_null():
    contact = {"id": "7", "properties": {"email": "a@example.com", "lead_source": ""},
               "createdAt": "2026-11-01T10:00:00Z", "updatedAt": "2026-11-02T10:00:00Z"}

    row = to_rows([contact], LOADED_AT)[0]

    assert (row["contact_id"], row["email"]) == ("7", "a@example.com")
    assert row["lead_source"] is None and row["lead_date"] is None


def test_deals_to_rows_takes_lowest_contact_id_or_null():
    base = {"properties": {"amount": "1200"}, "createdAt": "2026-11-01T10:00:00Z", "updatedAt": "2026-11-02T10:00:00Z"}
    with_contacts = {**base, "id": "1", "associations": {"contacts": {"results": [{"id": "90"}, {"id": "100"}]}}}
    without = {**base, "id": "2"}

    rows = deals_to_rows([with_contacts, without], LOADED_AT)

    assert rows[0]["contact_id"] == "90" and rows[0]["amount"] == "1200"
    assert rows[1]["contact_id"] is None
