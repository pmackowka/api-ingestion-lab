# NBP — kursy średnie walut (tabela A) → BigQuery

Kursy średnie NBP do przeliczania przychodów z EUR i USD na PLN w etapie 7.

## Przykładowe uruchomienia

```bash
# Backfill od 2025 roku — pierwsze uruchomienie albo po wygaśnięciu tabeli w sandboxie.
uv run python -m nbp.ingest --project api-ingestion-lab-bq --start 2025-01-01

# Codzienny przyrost: podmienia dziś i 7 dni wstecz. Po dłuższej przerwie podaj --start.
uv run python -m nbp.ingest --project api-ingestion-lab-bq --lookback-days 7

# Ponowne załadowanie jednego okresu; reszta tabeli bez zmian.
uv run python -m nbp.ingest --project api-ingestion-lab-bq --start 2026-01-01 --end 2026-03-31
```

## Konfiguracja

Najpierw [„Wspólne środowisko”](../docs/konfiguracja.md#wspólne-środowisko). NBP nie wymaga klucza:

```bash
PROJECT=api-ingestion-lab-bq

# 1. Backfill: dataset raw_nbp i tabela powstają same.
uv run python -m nbp.ingest --project $PROJECT --start 2025-01-01

# 2. Kontrola duplikatów: obie liczby równe (klucz: dzień + waluta).
bq query --use_legacy_sql=false "SELECT COUNT(*), COUNT(DISTINCT FORMAT('%t|%s', effective_date, currency_code)) FROM \`$PROJECT.raw_nbp.exchange_rates_a\`"

# 3. Testy (bez sieci i bez GCP).
uv run pytest nbp
```

## Źródło

`GET https://api.nbp.pl/api/exchangerates/tables/A/{start}/{end}/` ([dokumentacja](https://api.nbp.pl/)), bez klucza. Sprawdzone na żywo (listopad 2026):

| Zapytanie | Odpowiedź | Co robi kod |
|---|---|---|
| zakres ≤ 93 dni | 200, lista tabel (dzień = tabela z kursem `mid` każdej waluty) | `to_rows`: dzień × waluta, kurs jako `Decimal` → `NUMERIC` |
| zakres > 93 dni | `400 Przekroczony limit 93 dni` | `split_windows` dzieli na okna |
| weekend, święto | `404 Brak danych` | pusta lista, nie błąd |

Od 2026-01-02 tabela ma 32 waluty zamiast 33 (ostatni kurs `BGN`: 2025-12-31).

## Tabela docelowa

`raw_nbp.exchange_rates_a`, klucz `(effective_date, currency_code)`: `effective_date` DATE, `table_no` STRING (np. `001/A/NBP/2026`), `currency_code` STRING (ISO 4217), `currency_name` STRING NULLABLE, `mid` NUMERIC (PLN za 1 jednostkę), `loaded_at` TIMESTAMP. Zapis i brak partycji: [główne README](../README.md#przepisanie-z-podmianą-zakresu--na-czym-polega-i-dlaczego-tutaj).
