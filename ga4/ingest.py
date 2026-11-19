"""Ruch i kliknięcia w kontakt z GA4 (Data API) -> BigQuery."""

import argparse
from datetime import date, datetime, timezone

from google.cloud import bigquery

from common import cli
from common.bigquery import replace_date_range
from common.http import authorized_session

API_URL = "https://analyticsdata.googleapis.com/v1beta/properties/{property}:runReport"
SCOPES = ["https://www.googleapis.com/auth/analytics.readonly"]

PAGE_SIZE = 100_000

CONTACT_EVENTS = ["phone_reveal", "linkedin_click", "email_click", "email_reveal"]

TRAFFIC_TABLE = "traffic_daily"
CONTACTS_TABLE = "contact_events_daily"

_KEY = [
    bigquery.SchemaField("report_date", "DATE", mode="REQUIRED"),
    bigquery.SchemaField("session_source", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("session_medium", "STRING", mode="REQUIRED"),
]
_META = [
    bigquery.SchemaField("property_id", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("loaded_at", "TIMESTAMP", mode="REQUIRED"),
]
TRAFFIC_SCHEMA = [
    *_KEY,
    bigquery.SchemaField("sessions", "INT64", mode="REQUIRED"),
    bigquery.SchemaField("total_users", "INT64", mode="REQUIRED"),
    bigquery.SchemaField("engaged_sessions", "INT64", mode="REQUIRED"),
    *_META,
]
CONTACTS_SCHEMA = [
    *_KEY,
    bigquery.SchemaField("event_name", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("event_count", "INT64", mode="REQUIRED"),
    *_META,
]


def make_session():
    """Sesja z tokenem z ADC i ponowieniami 429/5xx — wspólna z Search Console (common/http.py)."""
    return authorized_session(SCOPES)


def fetch_report(session, property_id: str, body: dict, page_size: int = PAGE_SIZE) -> list[dict]:
    """Pobiera cały raport, strona po stronie (paginacja offsetem)."""
    url = API_URL.format(property=property_id)
    rows, offset = [], 0
    while True:
        response = session.post(url, json={**body, "limit": page_size, "offset": offset}, timeout=60)
        response.raise_for_status()
        payload = response.json()
        page = payload.get("rows", [])
        rows.extend(page)
        offset += len(page)
        if not page or offset >= payload.get("rowCount", 0):
            return rows


def report_body(start: date, end: date, dimensions: list[str], metrics: list[str], event_filter: list[str] | None = None) -> dict:
    """Treść zapytania runReport."""
    body = {
        "dateRanges": [{"startDate": start.isoformat(), "endDate": end.isoformat()}],
        "dimensions": [{"name": d} for d in dimensions],
        "metrics": [{"name": m} for m in metrics],
    }
    if event_filter:
        body["dimensionFilter"] = {"filter": {"fieldName": "eventName", "inListFilter": {"values": event_filter}}}
    return body


def to_rows(report: list[dict], columns: list[str], property_id: str, loaded_at: datetime) -> list[dict]:
    """Wiersz API (listy dimensionValues i metricValues) -> słownik z nazwami kolumn."""
    rows = []
    for item in report:
        values = [v["value"] for v in item["dimensionValues"]] + [v["value"] for v in item["metricValues"]]
        row = dict(zip(columns, values, strict=True))
        raw = row["report_date"]
        row["report_date"] = f"{raw[:4]}-{raw[4:6]}-{raw[6:]}"
        for column in columns[len(item["dimensionValues"]):]:
            row[column] = int(row[column])
        row["property_id"] = property_id
        row["loaded_at"] = loaded_at.isoformat()
        rows.append(row)
    return rows


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Wspólny interfejs CLI (common/cli.py) + --property, którego inne źródła nie mają."""
    parser = cli.make_parser("GA4 Data API -> BigQuery", default_dataset="raw_ga4")
    parser.add_argument("--property", required=True, help="identyfikator usługi GA4, np. 123456789")
    return cli.parse(parser, argv)


def main() -> None:
    args = parse_args()
    session = make_session()
    loaded_at = datetime.now(timezone.utc)
    dims = ["date", "sessionSource", "sessionMedium"]

    reports = [
        (
            TRAFFIC_TABLE,
            TRAFFIC_SCHEMA,
            report_body(args.start, args.end, dims, ["sessions", "totalUsers", "engagedSessions"]),
            ["report_date", "session_source", "session_medium", "sessions", "total_users", "engaged_sessions"],
        ),
        (
            CONTACTS_TABLE,
            CONTACTS_SCHEMA,
            report_body(args.start, args.end, [*dims, "eventName"], ["eventCount"], event_filter=CONTACT_EVENTS),
            ["report_date", "session_source", "session_medium", "event_name", "event_count"],
        ),
    ]
    for table, schema, body, columns in reports:
        rows = to_rows(fetch_report(session, args.property, body), columns, args.property, loaded_at)
        if not rows:
            print(f"{table}: brak wierszy w {args.start}..{args.end} — pomijam")
            continue
        replace_date_range(
            rows,
            project=args.project,
            dataset=args.dataset,
            table=table,
            schema=schema,
            date_column="report_date",
            start=args.start,
            end=args.end,
        )
        print(f"{table}: {len(rows)} wierszy, {args.start}..{args.end}")


if __name__ == "__main__":
    main()
