import io
import urllib.error
from datetime import date, datetime, timezone

import pytest

from weather import ingest
from weather.ingest import LOCATIONS, parse_args, to_rows

LOADED_AT = datetime(2026, 11, 18, 12, 0, tzinfo=timezone.utc)


def _location(lat: float, temps: list) -> dict:
    """Jedna lokalizacja w kształcie odpowiedzi Open-Meteo (blok daily = równoległe listy)."""
    n = len(temps)
    return {
        "latitude": lat,
        "longitude": 21.0,
        "elevation": 100.0,
        "timezone": "Europe/Warsaw",
        "daily": {
            "time": ["2026-11-16", "2026-11-17"][:n],
            "temperature_2m_mean": temps,
            "precipitation_sum": [0.0] * n,
            "weather_code": [3] * n,
        },
    }


def test_to_rows_one_row_per_location_and_day_in_request_order():
    response = [_location(50.0 + i, [4.8, None]) for i in range(len(LOCATIONS))]

    rows = to_rows(response, LOADED_AT)

    # 5 lokalizacji x 2 dni; null z API zostaje None (kolumna NULLABLE)
    assert len(rows) == len(LOCATIONS) * 2
    assert rows[0]["location_id"] == "warszawa" and rows[0]["weather_date"] == "2026-11-16"
    assert rows[1]["temperature_2m_mean"] is None
    assert rows[-1]["location_id"] == list(LOCATIONS)[-1]


def test_to_rows_rejects_wrong_number_of_locations():
    with pytest.raises(ValueError):
        to_rows([_location(52.0, [1.0])], LOADED_AT)


def test_retries_transient_error_then_succeeds(monkeypatch):
    calls = []

    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return b'{"ok": true}'

    def fake_urlopen(url, timeout):
        calls.append(url)
        if len(calls) == 1:
            raise TimeoutError("handshake timed out")
        return _Response()

    monkeypatch.setattr(ingest.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(ingest.time, "sleep", lambda _: None)

    assert ingest._get_with_retries("https://x") == {"ok": True}
    assert len(calls) == 2


def test_does_not_retry_client_error(monkeypatch):
    calls = []

    def fake_urlopen(url, timeout):
        calls.append(url)
        raise urllib.error.HTTPError(url, 400, "Bad Request", {}, io.BytesIO(b'{"reason": "zla data"}'))

    monkeypatch.setattr(ingest.urllib.request, "urlopen", fake_urlopen)

    with pytest.raises(RuntimeError, match="zla data"):
        ingest._get_with_retries("https://x")
    assert len(calls) == 1


def test_parse_args_matches_nbp_interface():
    args = parse_args(["--project", "p", "--end", "2026-11-18", "--lookback-days", "7"])
    assert (args.start, args.dataset) == (date(2026, 11, 11), "raw_weather")
