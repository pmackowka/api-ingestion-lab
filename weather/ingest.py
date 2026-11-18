"""Pogoda dzienna z Open-Meteo (archiwum) -> BigQuery.

Uruchomienie:
    uv run python weather/ingest.py --project <projekt-gcp> --start 2025-01-01      # backfill
    uv run python weather/ingest.py --project <projekt-gcp> --lookback-days 7       # harmonogram
"""

import argparse
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone

from google.cloud import bigquery

API_URL = "https://archive-api.open-meteo.com/v1/archive"

# Strefa czasowa wyznacza granice doby: suma opadów "za 12.11" w Europe/Warsaw i w GMT to różne liczby
# (sprawdzone na żywo). Bierzemy polską dobę, bo z nią złączymy dane GA4 pmdata.pl w etapie 7.
TIMEZONE = "Europe/Warsaw"

# Zmienne dzienne: na wymiar "jaka była pogoda tego dnia" wystarczą trzy.
# weather_code to kod WMO (0 = bezchmurnie, 61 = deszcz, 75 = śnieg itd.).
DAILY_VARIABLES = ["temperature_2m_mean", "precipitation_sum", "weather_code"]

# Własny, stały identyfikator lokalizacji -> współrzędne, o które pytamy.
# Kluczem tabeli jest location_id, nie współrzędne: API zwraca środek komórki siatki modelu
# (np. 52.267, 20.961 zamiast 52.23, 21.01), a liczby zmiennoprzecinkowe to kiepski klucz złączenia.
# Słownik zachowuje kolejność, a API zwraca lokalizacje w kolejności z zapytania — na tym opiera się to_rows.
LOCATIONS = {
    "warszawa": (52.23, 21.01),
    "krakow": (50.06, 19.94),
    "wroclaw": (51.11, 17.03),
    "poznan": (52.41, 16.93),
    "gdansk": (54.35, 18.65),
}

TARGET_TABLE = "daily_weather"
STAGING_TABLE = "_staging_daily_weather"

# Klucz naturalny: (weather_date, location_id).
# FLOAT64, nie NUMERIC jak kursy w NBP: temperatura i opad to pomiary z modelu, nie kwoty —
# błąd zaokrąglenia floata (1e-15) jest pomijalny wobec niepewności samego pomiaru.
SCHEMA = [
    bigquery.SchemaField("weather_date", "DATE", mode="REQUIRED"),
    bigquery.SchemaField("location_id", "STRING", mode="REQUIRED"),
    # Współrzędne komórki siatki, którą API faktycznie zwróciło — do kontroli, nie do złączeń.
    bigquery.SchemaField("grid_latitude", "FLOAT64", mode="REQUIRED"),
    bigquery.SchemaField("grid_longitude", "FLOAT64", mode="REQUIRED"),
    bigquery.SchemaField("elevation", "FLOAT64"),
    # Metryki NULLABLE: API zwraca null dla dni, których model jeszcze nie policzył.
    bigquery.SchemaField("temperature_2m_mean", "FLOAT64"),
    bigquery.SchemaField("precipitation_sum", "FLOAT64"),
    bigquery.SchemaField("weather_code", "INT64"),
    # Strefa zapisana w wierszu: bez niej nie wiadomo, jaką dobę opisuje weather_date.
    bigquery.SchemaField("timezone", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("loaded_at", "TIMESTAMP", mode="REQUIRED"),
]


def _get_with_retries(url: str, attempts: int = 3, base_delay: float = 2.0) -> dict | list:
    """GET z ponowieniami błędów przejściowych.

    Po co: pierwszy backfill padł na timeoucie TLS handshake, choć minutę wcześniej to samo API
    odpowiedziało w 1,3 s. Taki błąd mija sam, więc ponawiamy z rosnącą przerwą (2 s, 4 s).
    Ponawiamy tylko to, co może się udać za chwilę: sieć, timeout, 5xx. Kod 400 (zła data) przerywa
    od razu — ponowienie dałoby ten sam błąd, a harmonogram czekałby na próżno.
    """
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(url, timeout=30) as response:
                return json.loads(response.read())
        except urllib.error.HTTPError as error:
            # HTTPError dziedziczy po URLError, więc musi być obsłużony pierwszy.
            if error.code < 500 or attempt == attempts:
                # Open-Meteo opisuje błąd w treści: {"error": true, "reason": "..."}.
                # Pokazujemy reason, bo sam kod 400 nic nie mówi.
                reason = json.loads(error.read() or b"{}").get("reason", "brak opisu")
                raise RuntimeError(f"Open-Meteo {error.code}: {reason}") from error
        except (urllib.error.URLError, TimeoutError):
            if attempt == attempts:
                raise
        delay = base_delay * 2 ** (attempt - 1)
        print(f"Próba {attempt}/{attempts} nieudana, ponawiam za {delay:.0f} s")
        time.sleep(delay)
    raise AssertionError("nieosiągalne")  # pętla zawsze kończy się return albo raise


def fetch(start: date, end: date) -> list[dict]:
    """Krok 1: pobiera pogodę dla wszystkich lokalizacji jednym GET-em.

    Bez dzielenia na okna jak w NBP: Open-Meteo nie ma limitu długości zakresu
    (687 dni x 5 miast przychodzi w jednym zapytaniu, ok. 90 KB, ok. 1,3 s — zmierzone).
    """
    latitudes = ",".join(str(lat) for lat, _ in LOCATIONS.values())
    longitudes = ",".join(str(lon) for _, lon in LOCATIONS.values())
    # urlencode koduje znaki specjalne (np. "/" w Europe/Warsaw -> %2F), zamiast sklejać URL ręcznie.
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

    # Jedna lokalizacja -> API zwraca obiekt, kilka -> listę obiektów. Sprowadzamy do listy,
    # żeby reszta kodu nie musiała rozróżniać tych przypadków.
    return payload if isinstance(payload, list) else [payload]


def to_rows(locations: list[dict], loaded_at: datetime) -> list[dict]:
    """Krok 2: zamienia odpowiedź kolumnową na wiersze: lokalizacja x dzień.

    Po co: blok `daily` to równoległe listy (time[i], temperature_2m_mean[i], ... opisują ten sam dzień),
    a BigQuery ładuje wiersze. NBP zwracał już obiekty dzień -> waluty; tu wiersz trzeba złożyć z i-tych
    elementów każdej listy — robi to zip().
    """
    # Lokalizacji nie ma w odpowiedzi (są tylko współrzędne siatki), więc dopasowujemy po kolejności.
    # Inna liczba elementów = dopasowanie po kolejności byłoby błędne -> przerywamy, zamiast zgadywać.
    if len(locations) != len(LOCATIONS):
        raise ValueError(f"API zwróciło {len(locations)} lokalizacji, oczekiwano {len(LOCATIONS)}")

    rows = []
    for location_id, location in zip(LOCATIONS, locations):
        daily = location["daily"]
        # strict=True: listy różnej długości to błąd formatu, nie powód do cichego ucięcia danych.
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


def load_to_bigquery(rows: list[dict], project: str, dataset: str, start: date, end: date) -> None:
    """Krok 3: podmienia zakres [start, end] w tabeli docelowej — ten sam wzorzec co nbp/ingest.py.

    Kopia, nie import z nbp: foldery są niezależne i każdy da się przeczytać w całości bez skakania
    po repo. Wspólny moduł wydzielimy przy trzecim źródle, gdy będzie wiadomo, co naprawdę się powtarza.
    Szczegółowe wyjaśnienie mechanizmu (staging, UNION ALL, WRITE_TRUNCATE_DATA): nbp/README.md.
    """
    client = bigquery.Client(project=project)
    client.create_dataset(f"{project}.{dataset}", exists_ok=True)
    target = f"{project}.{dataset}.{TARGET_TABLE}"
    staging = f"{project}.{dataset}.{STAGING_TABLE}"
    client.create_table(bigquery.Table(target, schema=SCHEMA), exists_ok=True)

    # Krok 3a: staging zawiera zawsze tylko dane bieżącego uruchomienia.
    load_config = bigquery.LoadJobConfig(schema=SCHEMA, write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE)
    client.load_table_from_json(rows, staging, job_config=load_config).result()

    # Krok 3b: stare wiersze spoza zakresu + świeży zakres ze stagingu -> tabela docelowa, atomowo.
    # Zakres dotyczy wszystkich lokalizacji naraz, bo każde uruchomienie pobiera wszystkie.
    rewrite_sql = f"""
        SELECT * FROM `{target}`
        WHERE weather_date NOT BETWEEN @start AND @end
        UNION ALL
        SELECT * FROM `{staging}`
    """
    query_config = bigquery.QueryJobConfig(
        destination=target,
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE_DATA,
        query_parameters=[
            bigquery.ScalarQueryParameter("start", "DATE", start),
            bigquery.ScalarQueryParameter("end", "DATE", end),
        ],
    )
    client.query(rewrite_sql, job_config=query_config).result()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Ten sam interfejs CLI co nbp/ingest.py — warunek, żeby harmonogram odpalał wszystkie źródła
    jedną komendą (matrix w GitHub Actions, patrz CLAUDE.md)."""
    parser = argparse.ArgumentParser(description="Pogoda dzienna Open-Meteo -> BigQuery")
    parser.add_argument("--project", required=True, help="ID projektu GCP")
    parser.add_argument("--dataset", default="raw_weather")
    # Domyślnie dziś: API przyjmuje end_date najwyżej równe dzisiejszej dacie (jutro -> 400).
    # Dzisiejsza wartość jest niepełna (doba trwa) — poprawi ją lookback przy następnym uruchomieniu.
    parser.add_argument("--end", type=date.fromisoformat, default=date.today())
    start_group = parser.add_mutually_exclusive_group(required=True)
    start_group.add_argument("--start", type=date.fromisoformat)
    start_group.add_argument("--lookback-days", type=int, help="start = end minus tyle dni")
    args = parser.parse_args(argv)
    if args.lookback_days is not None:
        if args.lookback_days < 0:
            parser.error("--lookback-days nie może być ujemne")
        args.start = args.end - timedelta(days=args.lookback_days)
    return args


def main() -> None:
    args = parse_args()
    loaded_at = datetime.now(timezone.utc)
    rows = to_rows(fetch(args.start, args.end), loaded_at)
    print(f"{args.start}..{args.end}: {len(rows)} wierszy ({len(LOCATIONS)} lokalizacji)")
    load_to_bigquery(rows, args.project, args.dataset, args.start, args.end)
    print(f"Załadowano do {args.project}.{args.dataset}.{TARGET_TABLE}")


if __name__ == "__main__":
    main()
