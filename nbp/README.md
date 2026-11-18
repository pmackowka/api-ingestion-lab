# NBP — kursy średnie walut (tabela A) → BigQuery

Pobiera kursy średnie NBP z publicznego API i zapisuje je w BigQuery. Kursy przydadzą się w etapie 7 do przeliczania przychodów z EUR i USD na PLN.

## Przykładowe uruchomienia

Każde uruchomienie podmienia w tabeli tylko zakres `[--start, --end]`; domyślnie `--end` = dziś. Skrypt nie sprawdza, do jakiego dnia tabela ma już dane — po przerwie podaj `--start`.

```bash
# Backfill: cała historia od 2025 roku — pierwsze uruchomienie albo po wygaśnięciu tabeli w sandboxie.
uv run python -m nbp.ingest --project api-ingestion-lab-bq --start 2025-01-01

# Codzienny przyrost: podmienia ostatnie 8 dni kalendarzowych (dziś i 7 wstecz), łata dzień czy dwa przestoju.
uv run python -m nbp.ingest --project api-ingestion-lab-bq --lookback-days 7

# Nadrabianie po dłuższej przerwie: wszystko od dnia po ostatnim załadowanym, bez luki.
uv run python -m nbp.ingest --project api-ingestion-lab-bq --start 2026-11-17

# Ponowne załadowanie jednego okresu (tu I kwartał), np. po błędzie w danych; reszta tabeli bez zmian.
uv run python -m nbp.ingest --project api-ingestion-lab-bq --start 2026-01-01 --end 2026-03-31

# Osobny dataset do eksperymentów, bez ruszania raw_nbp.
uv run python -m nbp.ingest --project api-ingestion-lab-bq --dataset raw_nbp_test --start 2026-11-01
```

## Konfiguracja

Najpierw „Wspólne środowisko” z [głównego README](../README.md#wspólne-środowisko). NBP nie wymaga klucza ani dodatkowego API, więc zostaje tylko pierwsze uruchomienie i kontrola:

```bash
PROJECT=api-ingestion-lab-bq   # Twój projekt GCP

# 1. Backfill: dataset raw_nbp i tabele powstają same przy pierwszym uruchomieniu.
uv run python -m nbp.ingest --project $PROJECT --start 2025-01-01

# 2. Kontrola duplikatów: obie liczby muszą być równe (klucz: dzień + waluta).
bq query --use_legacy_sql=false "SELECT COUNT(*), COUNT(DISTINCT FORMAT('%t|%s', effective_date, currency_code)) FROM \`$PROJECT.raw_nbp.exchange_rates_a\`"

# 3. Testy jednostkowe (bez sieci i bez GCP).
uv run pytest nbp
```

## Źródło

- Endpoint: `GET https://api.nbp.pl/api/exchangerates/tables/A/{startDate}/{endDate}/`, nagłówek `Accept: application/json`. Dokumentacja: https://api.nbp.pl/
- Bez klucza i bez logowania.
- Jedna odpowiedź to lista tabel. Jedna tabela odpowiada jednemu dniowi notowań i zawiera kurs `mid` każdej waluty.

Zachowanie API sprawdzone na żywo (listopad 2026):

| Zapytanie | Odpowiedź |
|---|---|
| `end - start` ≤ 93 dni | 200 |
| `end - start` = 94 dni lub więcej | `400 BadRequest - Przekroczony limit 93 dni` |
| zakres bez notowań (weekend, święto) | `404 NotFound - Brak danych` |

Od 2026-01-02 tabela A ma 32 waluty zamiast 33. Ostatni kurs `BGN` (lew bułgarski) pochodzi z 2025-12-31.

## Jak działa jedno uruchomienie

Przepływ (pobranie → staging → podmiana zakresu) jest wspólny dla wszystkich źródeł — diagram na przykładzie NBP i porównanie strategii ładowania są w [głównym README](../README.md#jak-dane-trafiają-do-bigquery). Specyficzne dla NBP:

1. `split_windows` — dzieli zakres na okna po 93 dni, bo API odrzuca dłuższe (400).
2. `fetch_window` — jeden GET na okno; 404 = brak notowań (weekend, święto) → pusta lista, nie błąd.
3. `to_rows` — tabela dnia z N walutami → N wierszy; kurs jako `Decimal` → tekst → kolumna `NUMERIC`, bez przejścia przez float.

## Tabela docelowa

`<projekt>.raw_nbp.exchange_rates_a`, klucz: `(effective_date, currency_code)`.

| Kolumna | Typ | Tryb | Znaczenie |
|---|---|---|---|
| `effective_date` | DATE | REQUIRED | dzień notowania |
| `table_no` | STRING | REQUIRED | numer tabeli NBP, np. `001/A/NBP/2026` |
| `currency_code` | STRING | REQUIRED | kod ISO 4217, np. `EUR` |
| `currency_name` | STRING | NULLABLE | nazwa waluty po polsku |
| `mid` | NUMERIC | REQUIRED | kurs średni w PLN za 1 jednostkę waluty |
| `loaded_at` | TIMESTAMP | REQUIRED | czas uruchomienia, które zapisało wiersz (UTC) |

Tabela nie jest partycjonowana — powód w [głównym README](../README.md#przepisanie-z-podmianą-zakresu--na-czym-polega-i-dlaczego-tutaj).
