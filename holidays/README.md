# Święta — święta państwowe w Polsce (Nager.Date) → BigQuery

Dni wolne od pracy w Polsce do `is_holiday` w `dim_date`: wyjaśniają spadki ruchu i braki kursów NBP (NBP nie publikuje kursów w święta).

## Przykładowe uruchomienia

```bash
# Backfill od 2025 roku — pierwsze uruchomienie albo po wygaśnięciu tabeli w sandboxie.
uv run python -m holidays.ingest --project api-ingestion-lab-bq --start 2025-01-01

# Codzienne uruchomienie: zakres rozszerzany do pełnych lat, więc przeładowuje bieżący rok
# (na przełomie roku — oba lata).
uv run python -m holidays.ingest --project api-ingestion-lab-bq --lookback-days 7

# Rok z wyprzedzeniem, np. do planowania.
uv run python -m holidays.ingest --project api-ingestion-lab-bq --start 2027-01-01 --end 2027-12-31
```

## Konfiguracja

Najpierw [„Wspólne środowisko”](../docs/konfiguracja.md#wspólne-środowisko). Nager.Date nie wymaga klucza:

```bash
PROJECT=api-ingestion-lab-bq

# 1. Backfill: dataset raw_holidays i tabela powstają same.
uv run python -m holidays.ingest --project $PROJECT --start 2025-01-01

# 2. Kontrola duplikatów: obie liczby równe (klucz: dzień).
bq query --use_legacy_sql=false "SELECT COUNT(*), COUNT(DISTINCT holiday_date) FROM \`$PROJECT.raw_holidays.public_holidays\`"

# 3. Testy (bez sieci i bez GCP).
uv run pytest holidays
```

## Źródło

`GET https://nagerholidays.com/api/v4/Holidays/PL/{rok}` ([dokumentacja](https://nagerholidays.com/Api)), bez klucza, „No Rate Limits”. [Regulamin](https://nagerholidays.com/legal/termsofservice): projekty prywatne i non-profit za darmo, komercyjne wymagają sponsoringu. Sprawdzone na żywo (2026-11-26):

| Zapytanie | Odpowiedź | Co robi kod |
|---|---|---|
| rok, kraj `PL` | 200, lista świąt roku (2025 i 2026: po 14, w tym ruchome — Wielkanoc, Zielone Świątki, Boże Ciało; Wigilia od 2025) | `to_rows`: święto → wiersz |
| domyślny User-Agent `Python-urllib` | `403 Forbidden` (Cloudflare) | nagłówek `User-Agent: api-ingestion-lab` |
| `subdivisionCodes` | `null` — w Polsce wszystkie święta są ogólnopolskie (`nationalHoliday: true`) | `null` → pusta lista (`REPEATED` w BigQuery nie przyjmuje `NULL`) |

Dwie wersje API: stara v3 (`https://date.nager.at/api/v3/PublicHolidays/{rok}/PL`, pola `localName`, `types`, `global`, `counties`) nadal odpowiada, ale strona `date.nager.at` przekierowuje (301) na `nagerholidays.com`. Kod używa v4 — nie ma w niej polskich nazw (`localName`), tylko angielskie `name`.

## Tabela docelowa

`raw_holidays.public_holidays`, klucz `holiday_date`: `holiday_date` DATE, `country_code` STRING, `name` STRING (nazwa angielska), `is_national` BOOL, `holiday_types` STRING REPEATED (np. `Public`), `subdivision_codes` STRING REPEATED (kody ISO 3166-2 regionów dla świąt regionalnych; w Polsce puste), `loaded_at` TIMESTAMP.

Strategia: podmiana zakresu jak w pozostałych źródłach ([`common/bigquery.py`](../common/bigquery.py)), z zakresem rozszerzonym do pełnych lat (`year_bounds`), bo API zwraca cały rok — podmiana samych 7 dni zostawiłaby resztę roku z poprzedniego ładowania, a święta mogą zmienić się ustawą (Wigilia od 2025). Zapis i brak partycji: [główne README](../README.md#przepisanie-z-podmianą-zakresu--na-czym-polega-i-dlaczego-tutaj).
