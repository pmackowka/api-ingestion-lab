"""Wspólna sesja HTTP dla HubSpot CRM API — używają jej generator (zapis) i ingest (odczyt).

Osobny moduł, bo oba skrypty potrzebują tego samego: tokenu z .env, adresu API i ponowień przy 429.
"""

import os

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

API = "https://api.hubapi.com"
# Wersja API w ścieżce (np. /crm/objects/2026-09/contacts). HubSpot wersjonuje API datą;
# ta sama wersja co platformVersion aplikacji w hubspot/app/hsproject.json.
API_VERSION = "2026-09"

# Właściwości kontaktu dodawane przez generator. Wbudowane źródło HubSpota (hs_analytics_source)
# jest tylko do odczytu — liczy je skrypt śledzący HubSpota na stronie, którego pmdata.pl nie ma.
CUSTOM_PROPERTIES = [
    {"name": "lead_source", "label": "Lead source (GA4 source / medium)", "type": "string", "fieldType": "text"},
    {"name": "lead_event", "label": "Lead event (GA4 contact click)", "type": "string", "fieldType": "text"},
    # type=date: wartość "YYYY-MM-DD", bez godziny — lead przypisany do doby GA4 (Europe/Warsaw).
    {"name": "lead_date", "label": "Lead date (GA4 day)", "type": "date", "fieldType": "date"},
]


def make_session() -> requests.Session:
    """Sesja z tokenem aplikacji i ponowieniami 429/5xx.

    Token czytamy ze zmiennej środowiskowej, nie z pliku w kodzie: lokalnie podaje go
    `uv run --env-file .env`, w GitHub Actions — sekret repo. Kod ten sam, zmienia się źródło.
    """
    token = os.environ.get("HUBSPOT_ACCESS_TOKEN")
    if not token:
        raise SystemExit("Brak HUBSPOT_ACCESS_TOKEN — uruchom przez: uv run --env-file .env python -m hubspot.<moduł>")
    session = requests.Session()
    session.headers["Authorization"] = f"Bearer {token}"
    # 429 = limit zapytań (darmowy plan: 100 na 10 s na aplikację; search: 5 na s). urllib3 czeka tyle,
    # ile każe nagłówek Retry-After, a gdy go nie ma — wykładniczo (2 s, 4 s, 8 s).
    # POST też ponawiamy: batch/upsert jest idempotentny (klucz = e-mail), a search tylko czyta.
    retry = Retry(
        total=4,
        backoff_factor=2,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "POST"],
    )
    session.mount("https://", HTTPAdapter(max_retries=retry))
    return session
