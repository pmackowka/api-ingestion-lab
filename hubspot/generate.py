"""Generator syntetycznych leadów i deali: kliknięcia w kontakt z GA4 (BigQuery) -> kontakty i deale w HubSpot."""

import argparse
import random
from datetime import date, timedelta

from google.cloud import bigquery

from common import cli
from common.bigquery import LOCATION
from hubspot.api import API, API_VERSION, CONTACT_PROPERTIES, DEAL_PROPERTIES, make_session

SEED = 20261118
LEAD_RATE = 0.5
DEAL_RATE = 0.4
WIN_RATE = 0.35
SALES_CYCLE_DAYS = (7, 45)
AMOUNT_RANGE = (20, 300)
OPEN_STAGES = ["appointmentscheduled", "qualifiedtobuy", "presentationscheduled", "decisionmakerboughtin", "contractsent"]
BATCH_SIZE = 100
TEST_SOURCES = ("tagassistant.google.com",)

FIRST_NAMES = ["Anna", "Piotr", "Katarzyna", "Tomasz", "Magdalena", "Michał", "Agnieszka", "Paweł", "Joanna", "Marcin"]
LAST_NAMES = ["Nowak", "Kowalczyk", "Wiśniewska", "Wójcik", "Kamińska", "Lewandowski", "Zielińska", "Szymański"]


def fetch_contact_clicks(client: bigquery.Client, project: str, dataset: str, start: date, end: date) -> list[dict]:
    """Kliknięcia w kontakt z tabeli GA4, zagregowane do dzień x źródło x medium x zdarzenie."""
    sql = f"""
        SELECT report_date, session_source, session_medium, event_name, SUM(event_count) AS clicks
        FROM `{project}.{dataset}.contact_events_daily`
        WHERE report_date BETWEEN @start AND @end
        GROUP BY 1, 2, 3, 4
        ORDER BY 1, 2, 3, 4
    """
    config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("start", "DATE", start),
            bigquery.ScalarQueryParameter("end", "DATE", end),
        ]
    )
    return [dict(row) for row in client.query(sql, job_config=config).result()]


def build_leads(clicks: list[dict], seed: int = SEED, rate: float = LEAD_RATE) -> list[dict]:
    """Kliknięcia -> leady (właściwości kontaktu HubSpot)."""
    leads, rng, current_day, n = [], None, None, 0
    for row in clicks:
        day = row["report_date"]
        if day != current_day:
            rng, current_day, n = random.Random(f"{seed}:{day.isoformat()}"), day, 0
        for _ in range(row["clicks"]):
            if rng.random() >= rate:
                continue
            n += 1
            leads.append(
                {
                    "email": f"lead-{day:%Y%m%d}-{n:03d}@example.com",
                    "firstname": rng.choice(FIRST_NAMES),
                    "lastname": rng.choice(LAST_NAMES),
                    "lead_source": f"{row['session_source']} / {row['session_medium']}",
                    "lead_event": row["event_name"],
                    "lead_date": day.isoformat(),
                }
            )
    return leads


def build_deals(leads: list[dict], today: date, seed: int = SEED) -> list[dict]:
    """Leady -> deale: {"email": kontakt do powiązania, "properties": właściwości deala}; leady testowe bez deali."""
    deals = []
    for lead in leads:
        if lead["lead_source"].startswith(TEST_SOURCES):
            continue
        rng = random.Random(f"{seed}:deal:{lead['email']}")
        has_deal = rng.random() < DEAL_RATE
        cycle_days = rng.randint(*SALES_CYCLE_DAYS)
        won = rng.random() < WIN_RATE
        open_stage = rng.choice(OPEN_STAGES)
        amount = rng.randint(*AMOUNT_RANGE) * 100
        if not has_deal:
            continue
        close_date = date.fromisoformat(lead["lead_date"]) + timedelta(days=cycle_days)
        if close_date > today:
            stage = open_stage
        else:
            stage = "closedwon" if won else "closedlost"
        key = lead["email"].removesuffix("@example.com").replace("lead-", "deal-", 1)
        deals.append(
            {
                "email": lead["email"],
                "properties": {
                    "deal_key": key,
                    "dealname": f"{lead['firstname']} {lead['lastname']} ({key})",
                    "pipeline": "default",
                    "dealstage": stage,
                    "amount": str(amount),
                    "closedate": close_date.isoformat(),
                },
            }
        )
    return deals


def ensure_properties(session, object_type: str, properties: list[dict], group: str) -> None:
    """Tworzy własne właściwości obiektu; 409 = już istnieją (kolejne uruchomienie), to nie błąd."""
    for prop in properties:
        response = session.post(
            f"{API}/crm/properties/{API_VERSION}/{object_type}", json={**prop, "groupName": group}, timeout=30
        )
        if response.status_code != 409:
            response.raise_for_status()


def upsert(session, object_type: str, records: list[dict], id_property: str, batch_size: int = BATCH_SIZE) -> dict:
    """Zapis paczkami po 100 przez batch/upsert; zwraca {wartość klucza: ID rekordu w HubSpot}."""
    url = f"{API}/crm/objects/{API_VERSION}/{object_type}/batch/upsert"
    ids = {}
    for i in range(0, len(records), batch_size):
        batch = records[i : i + batch_size]
        inputs = [{"id": r[id_property], "idProperty": id_property, "properties": r} for r in batch]
        response = session.post(url, json={"inputs": inputs}, timeout=60)
        response.raise_for_status()
        for result in response.json().get("results", []):
            ids[result["properties"][id_property]] = result["id"]
    return ids


def associate_deals(session, pairs: list[tuple[str, str]], batch_size: int = BATCH_SIZE) -> None:
    """Powiązania deal -> kontakt (domyślny typ, bez etykiety), paczkami."""
    url = f"{API}/crm/associations/{API_VERSION}/deal/contact/batch/associate/default"
    for i in range(0, len(pairs), batch_size):
        inputs = [{"from": {"id": deal_id}, "to": {"id": contact_id}} for deal_id, contact_id in pairs[i : i + batch_size]]
        response = session.post(url, json={"inputs": inputs}, timeout=60)
        response.raise_for_status()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Wspólny interfejs CLI; --dataset wskazuje tu źródło (dataset GA4), nie cel."""
    return cli.parse(cli.make_parser("GA4 (BigQuery) -> syntetyczne leady i deale w HubSpot", default_dataset="raw_ga4"), argv)


def main() -> None:
    args = parse_args()
    start = args.start - timedelta(days=SALES_CYCLE_DAYS[1])
    client = bigquery.Client(project=args.project, location=LOCATION)
    leads = build_leads(fetch_contact_clicks(client, args.project, args.dataset, start, args.end))
    deals = build_deals(leads, today=args.end)

    session = make_session()
    ensure_properties(session, "contacts", CONTACT_PROPERTIES, group="contactinformation")
    ensure_properties(session, "deals", DEAL_PROPERTIES, group="dealinformation")
    contact_ids = upsert(session, "contacts", leads, id_property="email")
    deal_ids = upsert(session, "deals", [d["properties"] for d in deals], id_property="deal_key")
    associate_deals(session, [(deal_ids[d["properties"]["deal_key"]], contact_ids[d["email"]]) for d in deals])
    print(f"HubSpot: {len(leads)} leadów, {len(deals)} deali (upsert), {start}..{args.end}")


if __name__ == "__main__":
    main()
