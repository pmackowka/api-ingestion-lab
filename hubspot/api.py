"""Wspólna sesja HTTP dla HubSpot CRM API — używają jej generator (zapis) i ingest (odczyt)."""

import os

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

API = "https://api.hubapi.com"
API_VERSION = "2026-09"

CONTACT_PROPERTIES = [
    {"name": "lead_source", "label": "Lead source (GA4 source / medium)", "type": "string", "fieldType": "text"},
    {"name": "lead_event", "label": "Lead event (GA4 contact click)", "type": "string", "fieldType": "text"},
    {"name": "lead_date", "label": "Lead date (GA4 day)", "type": "date", "fieldType": "date"},
]

DEAL_PROPERTIES = [
    {"name": "deal_key", "label": "Deal key (generator)", "type": "string", "fieldType": "text", "hasUniqueValue": True},
]


def make_session() -> requests.Session:
    """Sesja z tokenem aplikacji i ponowieniami 429/5xx."""
    token = os.environ.get("HUBSPOT_ACCESS_TOKEN")
    if not token:
        raise SystemExit("Brak HUBSPOT_ACCESS_TOKEN — uruchom przez: uv run --env-file .env python -m hubspot.<moduł>")
    session = requests.Session()
    session.headers["Authorization"] = f"Bearer {token}"
    retry = Retry(
        total=4,
        backoff_factor=2,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "POST"],
    )
    session.mount("https://", HTTPAdapter(max_retries=retry))
    return session
