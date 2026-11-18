# Pogoda — Open-Meteo (archiwum) → BigQuery

Pobiera dzienną pogodę dla 5 największych miast Polski i zapisuje ją w BigQuery. W etapie 7 pogoda będzie wymiarem dnia obok ruchu z GA4.

## Przykładowe uruchomienia

Interfejs taki sam jak w `nbp/` — każde uruchomienie podmienia w tabeli zakres `[--start, --end]`; domyślnie `--end` = dziś.

```bash
# Backfill: cała historia od 2025 roku — 5 miast x 687 dni w jednym zapytaniu (ok. 1–2 s).
uv run python weather/ingest.py --project api-ingestion-lab-bq --start 2025-01-01

# Codzienny przyrost: podmienia ostatnie 8 dni — łapie korekty modelu z ostatnich dni.
uv run python weather/ingest.py --project api-ingestion-lab-bq --lookback-days 7

# Ponowne załadowanie jednego okresu; reszta tabeli bez zmian.
uv run python weather/ingest.py --project api-ingestion-lab-bq --start 2026-01-01 --end 2026-03-31
```

## Konfiguracja

Najpierw „Wspólne środowisko” z [głównego README](../README.md#wspólne-środowisko). Open-Meteo nie wymaga klucza ani dodatkowego API, więc zostaje tylko pierwsze uruchomienie i kontrola:

```bash
PROJECT=api-ingestion-lab-bq   # Twój projekt GCP

# 1. Backfill: dataset raw_weather i tabele powstają same przy pierwszym uruchomieniu.
uv run python weather/ingest.py --project $PROJECT --start 2025-01-01

# 2. Kontrola duplikatów: obie liczby muszą być równe (klucz: dzień + miasto).
bq query --use_legacy_sql=false "SELECT COUNT(*), COUNT(DISTINCT FORMAT('%t|%s', weather_date, location_id)) FROM \`$PROJECT.raw_weather.daily_weather\`"

# 3. Testy jednostkowe (bez sieci i bez GCP).
uv run pytest weather
```

## Źródło

- Endpoint: `GET https://archive-api.open-meteo.com/v1/archive`, bez klucza. [Dokumentacja](https://open-meteo.com/en/docs/historical-weather-api). Za darmo tylko do użytku niekomercyjnego, do 10 000 wywołań dziennie.
- Kilka lokalizacji w jednym zapytaniu: `latitude=52.23,50.06,…&longitude=21.01,19.94,…`.

Zachowanie API sprawdzone na żywo (2026-11-17/18):

| Zapytanie | Odpowiedź | Co z tego wynika dla kodu |
|---|---|---|
| jedna lokalizacja | obiekt `{…}` | `fetch` zawsze zwraca listę — jeden kształt dla reszty kodu |
| kilka lokalizacji | lista obiektów w kolejności z zapytania | `to_rows` dopasowuje miasto po kolejności i sprawdza liczbę |
| blok `daily` | równoległe listy: `time[i]`, `temperature_2m_mean[i]`… | wiersz składa `zip()`, nie pętla po obiektach jak w NBP |
| współrzędne w odpowiedzi | środek komórki siatki (52.267, 20.961 zamiast 52.23, 21.01) | kluczem jest własny `location_id`, nie współrzędne |
| `timezone=GMT` vs `Europe/Warsaw` | inne sumy opadów dla części dni (12.11: 3,0 vs 2,8 mm) | strefa to część definicji danych → `Europe/Warsaw`, zapisana w wierszu |
| 687 dni x 5 miast | 200, ok. 90 KB, ok. 1,3 s | bez dzielenia na okna |
| `end_date` = jutro | `400 … out of allowed range` | `--end` domyślnie dziś |
| `start` po `end` | `400 End-date must be larger…` | błąd z `reason` przerywa skrypt |
| ten sam dzień dzień później | 17.11: 2,4 mm → 1,7 mm | ostatnie dni są korygowane → lookback |
| raz na kilka zapytań | timeout TLS handshake | ponowienia: 3 próby, przerwa 2 s i 4 s |

## Jak działa jedno uruchomienie

Ten sam przepływ co w `nbp/` (diagram i wyjaśnienie: [`nbp/README.md`](../nbp/README.md)), z trzema różnicami:

1. `fetch` — jeden GET dla wszystkich miast, z ponowieniami błędów przejściowych (sieć, timeout, 5xx). Błąd 400 przerywa od razu: zła data nie naprawi się sama.
2. `to_rows` — odpowiedź kolumnowa → wiersze `miasto x dzień` przez `zip(..., strict=True)`; listy różnej długości to błąd, nie powód do cichego ucięcia.
3. `load_to_bigquery` — kopia wzorca z NBP (staging + `UNION ALL` + `WRITE_TRUNCATE_DATA`), nie import: foldery mają być czytelne osobno. Wspólny moduł wydzielimy przy trzecim źródle.

## Tabela docelowa

`<projekt>.raw_weather.daily_weather`, klucz: `(weather_date, location_id)`.

| Kolumna | Typ | Tryb | Znaczenie |
|---|---|---|---|
| `weather_date` | DATE | REQUIRED | doba w strefie z kolumny `timezone` |
| `location_id` | STRING | REQUIRED | `warszawa`, `krakow`, `wroclaw`, `poznan`, `gdansk` |
| `grid_latitude`, `grid_longitude` | FLOAT64 | REQUIRED | środek komórki siatki zwróconej przez API — do kontroli, nie do złączeń |
| `elevation` | FLOAT64 | NULLABLE | wysokość komórki (m) |
| `temperature_2m_mean` | FLOAT64 | NULLABLE | średnia temperatura doby (°C) |
| `precipitation_sum` | FLOAT64 | NULLABLE | suma opadu doby (mm) |
| `weather_code` | INT64 | NULLABLE | kod WMO: 0 bezchmurnie, 3 pochmurno, 5x mżawka, 6x deszcz, 7x śnieg |
| `timezone` | STRING | REQUIRED | `Europe/Warsaw` |
| `loaded_at` | TIMESTAMP | REQUIRED | czas uruchomienia (UTC) |

Dlaczego FLOAT64, a nie NUMERIC jak kursy NBP: to pomiary z modelu, nie kwoty. Błąd zaokrąglenia floata jest pomijalny wobec niepewności pomiaru. Metryki są NULLABLE, bo API zwraca `null` dla dni, których model jeszcze nie policzył.

## Strategia ładowania

Przepisanie z podmianą zakresu — jak w NBP i z tych samych powodów (sandbox bez DML, mała tabela: ok. 1800 wierszy rocznie). Pełne uzasadnienie i porównanie strategii: [`nbp/README.md`](../nbp/README.md#strategie-ładowania).

Lookback ma tu mocniejszy powód niż w NBP: kurs raz opublikowany się nie zmienia, a pogoda z ostatnich dni tak — najnowsze dni pochodzą z modelu prognostycznego i są później zastępowane danymi z reanalizy ERA5, publikowanej z 5-dniowym opóźnieniem ([źródła danych](https://open-meteo.com/en/docs/historical-weather-api)). `--lookback-days 7` obejmuje to okno.
