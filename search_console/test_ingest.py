from datetime import date, datetime, timezone

from search_console.ingest import fetch_report, parse_args, to_rows

LOADED_AT = datetime(2026, 11, 18, 12, 0, tzinfo=timezone.utc)


class _FakeSession:
    """Atrapa API: oddaje wiersze stronami po rowLimit; brak rowCount, jak w prawdziwym API."""

    def __init__(self, all_rows):
        self.all_rows, self.start_rows, self.urls = all_rows, [], []

    def post(self, url, json, timeout):
        self.urls.append(url)
        self.start_rows.append(json["startRow"])
        page = self.all_rows[json["startRow"] : json["startRow"] + json["rowLimit"]]
        return _Response({"rows": page} if page else {})


class _Response:
    def __init__(self, body):
        self.body = body

    def raise_for_status(self):
        pass

    def json(self):
        return self.body


def _row(day: str) -> dict:
    return {"keys": [day, "pol", "MOBILE"], "clicks": 1.0, "impressions": 3.0, "position": 4.5}


def test_fetch_report_pages_until_short_page_and_encodes_site():
    session = _FakeSession([_row("2026-11-01") for _ in range(5)])

    rows = fetch_report(session, "sc-domain:pmdata.pl", date(2026, 11, 1), date(2026, 11, 2), ["date"], page_size=2)

    # 5 wierszy po 2: strony 2, 2, 1 — trzecia krótsza niż limit kończy pętlę
    assert len(rows) == 5
    assert session.start_rows == [0, 2, 4]
    assert "sc-domain%3Apmdata.pl" in session.urls[0]


def test_fetch_report_full_last_page_needs_one_empty_request():
    session = _FakeSession([_row("2026-11-01") for _ in range(4)])

    rows = fetch_report(session, "s", date(2026, 11, 1), date(2026, 11, 2), ["date"], page_size=2)

    # 4 wiersze po 2: ostatnia strona pełna, więc koniec poznajemy dopiero po pustej (startRow 4)
    assert len(rows) == 4
    assert session.start_rows == [0, 2, 4]


def test_to_rows_maps_keys_and_casts_counts():
    rows = to_rows([_row("2026-11-01")], ["date", "country", "device"], "sc-domain:pmdata.pl", LOADED_AT)

    assert rows[0]["report_date"] == "2026-11-01"
    assert (rows[0]["country"], rows[0]["device"]) == ("pol", "MOBILE")
    assert (rows[0]["clicks"], rows[0]["impressions"]) == (1, 3)


def test_parse_args_requires_site():
    args = parse_args(["--project", "p", "--site", "sc-domain:pmdata.pl", "--lookback-days", "7"])
    assert (args.site, args.dataset) == ("sc-domain:pmdata.pl", "raw_search_console")
