"""Wspólna sesja HTTP dla Odoo JSON-2 API — używają jej generator faktur (zapis) i ingest (odczyt)."""

import os

import requests

ODOO_URL = os.environ.get("ODOO_URL", "http://127.0.0.1:8069")
ODOO_DB = os.environ.get("ODOO_DB", "lab")


class OdooClient:
    """Wywołanie metody modelu: client.call("res.partner", "search_read", domain=[...], fields=[...])."""

    def __init__(self, session: requests.Session, url: str = ODOO_URL):
        self.session, self.url = session, url

    def call(self, model: str, method: str, **params):
        response = self.session.post(f"{self.url}/json/2/{model}/{method}", json=params, timeout=60)
        if response.status_code >= 400:
            body = response.json() if response.headers.get("Content-Type", "").startswith("application/json") else {}
            raise RuntimeError(f"Odoo {model}.{method} {response.status_code}: {body.get('message', response.text[:300])}")
        return response.json()


def make_client() -> OdooClient:
    """Klient z kluczem API z .env (ODOO_API_KEY); baza w nagłówku, bo serwer może mieć kilka baz."""
    key = os.environ.get("ODOO_API_KEY")
    if not key:
        raise SystemExit("Brak ODOO_API_KEY — uruchom przez: uv run --env-file .env python -m odoo.<moduł>")
    session = requests.Session()
    session.headers.update({"Authorization": f"bearer {key}", "X-Odoo-Database": ODOO_DB})
    return OdooClient(session)
