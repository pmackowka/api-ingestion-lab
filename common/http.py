"""Wspólna sesja HTTP dla API Google (GA4, Search Console): token z ADC + ponowienia.

Wydzielona przy drugim użyciu, bo obie kopie byłyby identyczne co do znaku — różnią się tylko zakresem.
"""

import google.auth
from google.auth.transport.requests import AuthorizedSession
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


def authorized_session(scopes: list[str]) -> AuthorizedSession:
    """Sesja HTTP, która sama dokleja token OAuth i ponawia błędy przejściowe.

    Poświadczenia z ADC — lokalnie podszywanie się pod konto usługi, w harmonogramie WIF.
    Kod się nie zmienia, zmienia się tylko środowisko. Zakres musi być też w ADC
    (gcloud auth application-default login --scopes=...), inaczej API odpowie 403.

    Ponowienia z urllib3.Retry zamiast własnej pętli jak w pogodzie: requests ma to wbudowane.
    429 = przekroczony limit zapytań, 5xx = awaria po stronie Google. POST trzeba dopisać jawnie,
    bo domyślnie Retry nie ponawia metod, które mogą zmieniać stan — raporty tylko czytają, więc wolno.
    """
    credentials, _ = google.auth.default(scopes=scopes)
    session = AuthorizedSession(credentials)
    retry = Retry(
        total=3,
        backoff_factor=2,  # przerwy ok. 2 s, 4 s, 8 s
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["POST"],
    )
    session.mount("https://", HTTPAdapter(max_retries=retry))
    return session
