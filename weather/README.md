# Pogoda — Open-Meteo (archiwum) → BigQuery

Dzienna pogoda dla 5 największych miast Polski — w etapie 7 wymiar dnia obok ruchu z GA4.

Diagram sekwencji UML jednego uruchomienia: [`uml-diagram.md`](uml-diagram.md).

## Przykładowe uruchomienia

```bash
# Backfill od 2025 roku — wszystkie miasta w jednym zapytaniu.
uv run python -m weather.ingest --project api-ingestion-lab-bq --start 2025-01-01

# Codzienny przyrost: podmienia ostatnie 8 dni, łapie korekty modelu.
uv run python -m weather.ingest --project api-ingestion-lab-bq --lookback-days 7
```

## Konfiguracja

Najpierw [„Wspólne środowisko”](../docs/konfiguracja.md#wspólne-środowisko). Open-Meteo nie wymaga klucza:

```bash
PROJECT=api-ingestion-lab-bq

# 1. Backfill: dataset raw_weather i tabela powstają same.
uv run python -m weather.ingest --project $PROJECT --start 2025-01-01

# 2. Kontrola duplikatów: obie liczby równe (klucz: dzień + miasto).
bq query --use_legacy_sql=false "SELECT COUNT(*), COUNT(DISTINCT FORMAT('%t|%s', weather_date, location_id)) FROM \`$PROJECT.raw_weather.daily_weather\`"

# 3. Testy (bez sieci i bez GCP).
uv run pytest weather
```

## Źródło

`GET https://archive-api.open-meteo.com/v1/archive` ([dokumentacja](https://open-meteo.com/en/docs/historical-weather-api)), bez klucza, za darmo do użytku niekomercyjnego (10 000 wywołań dziennie). Sprawdzone na żywo (2026-11-18):

| Zachowanie | Co robi kod |
|---|---|
| jedna lokalizacja → obiekt, kilka → lista w kolejności z zapytania | `fetch` zawsze zwraca listę; `to_rows` sprawdza liczbę miast |
| `daily` to równoległe listy (`time[i]`, `temperature_2m_mean[i]`…) | wiersz składa `zip(strict=True)` |
| współrzędne w odpowiedzi to środek komórki siatki | kluczem jest własny `location_id` |
| `timezone` zmienia sumy dobowe | `Europe/Warsaw`, zapisana w wierszu |
| cała historia w jednym zapytaniu (ok. 1 s) | bez dzielenia na okna |
| `end_date` w przyszłości → 400 | `--end` domyślnie dziś |
| ostatnie dni korygowane (ERA5 z 5-dniowym opóźnieniem) | lookback 7 dni |
| sporadyczny timeout TLS | 3 próby, przerwa 2 s i 4 s; 400 przerywa od razu |

## Tabela docelowa

`raw_weather.daily_weather`, klucz `(weather_date, location_id)`.

| Kolumna | Typ | Znaczenie |
|---|---|---|
| `weather_date` | DATE | doba w strefie z `timezone` |
| `location_id` | STRING | `warszawa`, `krakow`, `wroclaw`, `poznan`, `gdansk` |
| `grid_latitude`, `grid_longitude`, `elevation` | FLOAT64 | komórka siatki — do kontroli, nie do złączeń |
| `temperature_2m_mean`, `precipitation_sum` | FLOAT64 NULLABLE | °C, mm; `null` dla dni jeszcze niepoliczonych |
| `weather_code` | INT64 NULLABLE | kod WMO: 0 bezchmurnie, 3 pochmurno, 6x deszcz, 7x śnieg |
| `timezone`, `loaded_at` | STRING, TIMESTAMP | strefa doby, czas zapisu (UTC) |

FLOAT64, nie NUMERIC jak w NBP: to pomiary z modelu, nie kwoty. Zapis: [podmiana zakresu](../README.md#strategie-ładowania).
