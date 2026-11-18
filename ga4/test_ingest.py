from datetime import datetime, timezone

from ga4.ingest import fetch_report, parse_args, to_rows

LOADED_AT = datetime(2026, 11, 18, 12, 0, tzinfo=timezone.utc)


def _row(day: str, source: str, sessions: str) -> dict:
    """Wiersz w kształcie odpowiedzi runReport."""
    return {
        "dimensionValues": [{"value": day}, {"value": source}, {"value": "organic"}],
        "metricValues": [{"value": sessions}],
    }


class _FakeSession:
    """Atrapa sesji HTTP: oddaje raport z 5 wierszy stronami po `limit`, jak prawdziwe API."""

    def __init__(self, all_rows):
        self.all_rows, self.offsets = all_rows, []

    def post(self, url, json, timeout):
        self.offsets.append(json["offset"])
        page = self.all_rows[json["offset"] : json["offset"] + json["limit"]]
        body = {"rowCount": len(self.all_rows)}
        if page:
            body["rows"] = page
        return _Response(body)


class _Response:
    def __init__(self, body):
        self.body = body

    def raise_for_status(self):
        pass

    def json(self):
        return self.body


def test_fetch_report_pages_by_offset_until_row_count():
    rows = [_row("20261101", f"s{i}", "1") for i in range(5)]
    session = _FakeSession(rows)

    result = fetch_report(session, "123", {}, page_size=2)

    # 5 wierszy po 2 na stronę -> offsety 0, 2, 4
    assert result == rows
    assert session.offsets == [0, 2, 4]


def test_fetch_report_empty_report_returns_no_rows():
    assert fetch_report(_FakeSession([]), "123", {}) == []


def test_to_rows_converts_date_and_metrics():
    rows = to_rows([_row("20261101", "google", "11")], ["report_date", "session_source", "session_medium", "sessions"], "123", LOADED_AT)

    assert rows[0]["report_date"] == "2026-11-01"
    assert rows[0]["sessions"] == 11
    assert rows[0]["property_id"] == "123"


def test_parse_args_requires_property_on_top_of_common_interface():
    args = parse_args(["--project", "p", "--property", "123", "--lookback-days", "7"])
    assert (args.property, args.dataset) == ("123", "raw_ga4")
