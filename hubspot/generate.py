"""Generator syntetycznych leadów: kliknięcia w kontakt z GA4 (BigQuery) -> kontakty w HubSpot.

Uruchomienie (token z .env):
    uv run --env-file .env python -m hubspot.generate --project <projekt-gcp> --start 2025-01-01   # cała historia
    uv run --env-file .env python -m hubspot.generate --project <projekt-gcp> --lookback-days 7    # przyrost

Zasada: każde kliknięcie w kontakt (phone_reveal, email_click…) zamienia się w lead z prawdopodobieństwem
LEAD_RATE, a lead dziedziczy źródło i medium sesji tego kliknięcia. Dzięki temu proporcje źródeł leadów
odpowiadają proporcjom źródeł kliknięć w GA4, a wolumen — liczbie kliknięć. Dane trafiają do prawdziwego
HubSpota (konto testowe), a ingest pobiera je z powrotem przez API — jak z każdego CRM.
"""

import argparse
import random
from datetime import date

from google.cloud import bigquery

from common import cli
from common.bigquery import LOCATION
from hubspot.api import API, API_VERSION, CUSTOM_PROPERTIES, make_session

# Stały seed: ten sam dzień GA4 zawsze daje te same leady (imiona, decyzje lead/nie-lead).
SEED = 20261118
# Założony odsetek kliknięć w kontakt, które kończą się leadem w CRM (np. telefon odebrany, mail z zapytaniem).
LEAD_RATE = 0.5
# Limit API: batch endpointy przyjmują maks. 100 rekordów na zapytanie.
BATCH_SIZE = 100

FIRST_NAMES = ["Anna", "Piotr", "Katarzyna", "Tomasz", "Magdalena", "Michał", "Agnieszka", "Paweł", "Joanna", "Marcin"]
LAST_NAMES = ["Nowak", "Kowalczyk", "Wiśniewska", "Wójcik", "Kamińska", "Lewandowski", "Zielińska", "Szymański"]


def fetch_contact_clicks(client: bigquery.Client, project: str, dataset: str, start: date, end: date) -> list[dict]:
    """Kliknięcia w kontakt z tabeli GA4, zagregowane do dzień x źródło x medium x zdarzenie.

    ORDER BY jest częścią kontraktu: build_leads przechodzi wiersze po kolei z jednym generatorem
    losowym na dzień, więc inna kolejność dałaby inne leady przy tym samym seedzie.
    """
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
    """Kliknięcia -> leady (właściwości kontaktu HubSpot). Czysta funkcja: bez sieci, łatwa do testu.

    Generator losowy osobno dla każdego dnia (seed + data): przeliczenie jednego tygodnia daje te same
    leady co pełny backfill, bo wynik dnia nie zależy od tego, od którego dnia ruszył skrypt.
    E-mail = klucz upsertu w HubSpot, więc musi być deterministyczny: lead-YYYYMMDD-NNN@example.com
    (domena example.com jest zarezerwowana do przykładów — żaden mail nie trafi do prawdziwej osoby).
    """
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


def ensure_properties(session) -> None:
    """Tworzy własne właściwości kontaktu; 409 = już istnieją (kolejne uruchomienie), to nie błąd."""
    for prop in CUSTOM_PROPERTIES:
        response = session.post(
            f"{API}/crm/properties/{API_VERSION}/contacts", json={**prop, "groupName": "contactinformation"}, timeout=30
        )
        if response.status_code != 409:
            response.raise_for_status()


def upsert_contacts(session, leads: list[dict], batch_size: int = BATCH_SIZE) -> None:
    """Zapis paczkami po 100 przez batch/upsert z kluczem `email`.

    Upsert zamiast create: drugie uruchomienie dla tych samych dni aktualizuje istniejące kontakty
    zamiast tworzyć duplikaty — ta sama idempotencja, której pilnujemy po stronie BigQuery.
    """
    url = f"{API}/crm/objects/{API_VERSION}/contacts/batch/upsert"
    for i in range(0, len(leads), batch_size):
        batch = leads[i : i + batch_size]
        inputs = [{"id": lead["email"], "idProperty": "email", "properties": lead} for lead in batch]
        response = session.post(url, json={"inputs": inputs}, timeout=60)
        response.raise_for_status()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Wspólny interfejs CLI; --dataset wskazuje tu źródło (dataset GA4), nie cel."""
    return cli.parse(cli.make_parser("GA4 (BigQuery) -> syntetyczne leady w HubSpot", default_dataset="raw_ga4"), argv)


def main() -> None:
    args = parse_args()
    client = bigquery.Client(project=args.project, location=LOCATION)
    leads = build_leads(fetch_contact_clicks(client, args.project, args.dataset, args.start, args.end))
    session = make_session()
    ensure_properties(session)
    upsert_contacts(session, leads)
    print(f"HubSpot: {len(leads)} leadów (upsert), {args.start}..{args.end}")


if __name__ == "__main__":
    main()
