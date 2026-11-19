"""Pogoda dzienna z Open-Meteo (archiwum) -> BigQuery."""

import argparse
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone

from google.cloud import bigquery

from common import cli
from common.bigquery import replace_date_range

API_URL = "https://archive-api.open-meteo.com/v1/archive"

TIMEZONE = "Europe/Warsaw"

DAILY_VARIABLES = ["temperature_2m_mean", "precipitation_sum", "weather_code"]

LOCATIONS = {
    "warszawa": (52.23, 21.01),
    "krakow": (50.06, 19.94),
    "wroclaw": (51.11, 17.03),
    "poznan": (52.41, 16.93),
    "gdansk": (54.35, 18.65),
}

TARGET_TABLE = "daily_weather"

SCHEMA = [
    bigquery.SchemaField("weather_date", "DATE", mode="REQUIRED"),
    bigquery.SchemaField("location_id", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("grid_latitude", "FLOAT64", mode="REQUIRED"),
    bigquery.SchemaField("grid_longitude", "FLOAT64", mode="REQUIRED"),
    bigquery.SchemaField("elevation", "FLOAT64"),
    bigquery.SchemaField("temperature_2m_mean", "FLOAT64"),
    bigquery.SchemaField("precipitation_sum", "FLOAT64"),
    bigquery.SchemaField("weather_code", "INT64"),
    bigquery.SchemaField("timezone", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("loaded_at", "TIMESTAMP", mode="REQUIRED"),
]


def _get_with_retries(url: str, attempts: int = 3, base_delay: float = 2.0) -> dict | list:
    """GET z ponowieniami błędów przejściowych."""
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(url, timeout=30) as response:
                return json.loads(response.read())
        except urllib.error.HTTPError as error:
            if error.code < 500 or attempt == attempts:
                reason = json.loads(error.read() or b"{}").get("reason", "brak opisu")
                raise RuntimeError(f"Open-Meteo {error.code}: {reason}") from error
        except (urllib.error.URLError, TimeoutError):
            if attempt == attempts:
                raise
        delay = base_delay * 2 ** (attempt - 1)
        print(f"Próba {attempt}/{attempts} nieudana, ponawiam za {delay:.0f} s")
        time.sleep(delay)
    raise AssertionError("nieosiągalne")


def fetch(start: date, end: date) -> list[dict]:
    """Pobiera pogodę dla wszystkich lokalizacji jednym GET-em."""
    latitudes = ",".join(str(lat) for lat, _ in LOCATIONS.values())
    longitudes = ",".join(str(lon) for _, lon in LOCATIONS.values())
    query = urllib.parse.urlencode(
        {
            "latitude": latitudes,
            "longitude": longitudes,
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "daily": ",".join(DAILY_VARIABLES),
            "timezone": TIMEZONE,
        }
    )
    payload = _get_with_retries(f"{API_URL}?{query}")

    return payload if isinstance(payload, list) else [payload]


def to_rows(locations: list[dict], loaded_at: datetime) -> list[dict]:
    """Zamienia odpowiedź kolumnową na wiersze: lokalizacja x dzień."""
    if len(locations) != len(LOCATIONS):
        raise ValueError(f"API zwróciło {len(locations)} lokalizacji, oczekiwano {len(LOCATIONS)}")

    rows = []
    for location_id, location in zip(LOCATIONS, locations):
        daily = location["daily"]
        for day, temperature, precipitation, code in zip(
            daily["time"],
            daily["temperature_2m_mean"],
            daily["precipitation_sum"],
            daily["weather_code"],
            strict=True,
        ):
            rows.append(
                {
                    "weather_date": day,
                    "location_id": location_id,
                    "grid_latitude": location["latitude"],
                    "grid_longitude": location["longitude"],
                    "elevation": location.get("elevation"),
                    "temperature_2m_mean": temperature,
                    "precipitation_sum": precipitation,
                    "weather_code": code,
                    "timezone": location["timezone"],
                    "loaded_at": loaded_at.isoformat(),
                }
            )
    return rows


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Wspólny interfejs CLI (common/cli.py); --end domyślnie dziś."""
    return cli.parse(cli.make_parser("Pogoda dzienna Open-Meteo -> BigQuery", default_dataset="raw_weather"), argv)


def main() -> None:
    args = parse_args()
    loaded_at = datetime.now(timezone.utc)
    rows = to_rows(fetch(args.start, args.end), loaded_at)
    print(f"{args.start}..{args.end}: {len(rows)} wierszy ({len(LOCATIONS)} lokalizacji)")
    replace_date_range(
        rows,
        project=args.project,
        dataset=args.dataset,
        table=TARGET_TABLE,
        schema=SCHEMA,
        date_column="weather_date",
        start=args.start,
        end=args.end,
    )
    print(f"Załadowano do {args.project}.{args.dataset}.{TARGET_TABLE}")


if __name__ == "__main__":
    main()
