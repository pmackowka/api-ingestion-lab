"""Wspólna sesja HTTP dla API Google (GA4, Search Console): token z ADC + ponowienia."""

import google.auth
from google.auth.transport.requests import AuthorizedSession
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


def authorized_session(scopes: list[str]) -> AuthorizedSession:
    """Sesja HTTP, która sama dokleja token OAuth i ponawia błędy przejściowe."""
    credentials, _ = google.auth.default(scopes=scopes)
    session = AuthorizedSession(credentials)
    retry = Retry(
        total=3,
        backoff_factor=2,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["POST"],
    )
    session.mount("https://", HTTPAdapter(max_retries=retry))
    return session
