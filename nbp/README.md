# NBP — kursy średnie walut (tabela A) → BigQuery

Kursy średnie NBP do przeliczania przychodów z EUR i USD na PLN w etapie 7.

Diagram sekwencji UML jednego uruchomienia: [`uml-diagram.md`](uml-diagram.md).

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

## Jedno uruchomienie krok po kroku

`--lookback-days 7` uruchomione 17.11.2026; tabela ma dane od 02.01.2025 do 14.11.2026, a NBP poprawiło kurs z 12.11.

```
 PYTHON (Twój Mac / runner)              BIGQUERY (serwery Google)
 ──────────────────────────              ─────────────────────────────────────────

 1. parse_args + split_windows:
    start = 17.11 − 7 = 10.11
    end   = 17.11  (8 dni, jedno okno)

 2. fetch_window (API NBP)
    → dni z notowaniami 10–17.11
      (12.11 już w nowej wersji)

 3. to_rows: spłaszczenie
    → 5 dni × 32 waluty = 160 wierszy
      (11.11 święto, 15–16.11 weekend)

 4a. load_table_from_json ─────────────▶ _staging_exchange_rates_a
     (WRITE_TRUNCATE)                    ┌───────────────────────┐
                                         │ 10.11 … 17.11  (nowe) │  poprzednia zawartość
                                         └───────────────────────┘  stagingu wyrzucona

 4b. client.query(rewrite_sql) ────────▶ wykonanie SQL:

                exchange_rates_a (przed)              _staging
                ┌──────────────────────┐              ┌───────────────┐
                │ 02.01.2025 … 09.11   │──┐           │ 10.11 … 17.11 │
                │ 10.11 … 14.11 (stare)│✗ │           └───────┬───────┘
                └──────────────────────┘  │ WHERE NOT BETWEEN │
                                          ▼                   ▼
                                ┌──────────────────────────────────┐
                                │ UNION ALL = sklejenie pod sobą   │
                                │ 02.01.2025 … 09.11  (z tabeli)   │
                                │ 10.11 … 17.11       (ze stagingu)│
                                └────────────────┬─────────────────┘
                                                 │ WRITE_TRUNCATE_DATA
                                                 ▼
                                exchange_rates_a (po) — zapisana od nowa w całości:
                                historia skopiowana bez zmian, 10–17.11 wymienione
```

Treść zmienia się tylko w zakresie `[start, end]`, ale BigQuery zapisuje całą tabelę od nowa; historia pochodzi ze starej wersji tabeli, nie z API. Bez `NOT BETWEEN` dni 10–14.11 byłyby dwa razy. Zapis jest wspólny dla wszystkich źródeł: [`common/bigquery.py`](../common/bigquery.py).

## Tabela docelowa

`raw_nbp.exchange_rates_a`, klucz `(effective_date, currency_code)`: `effective_date` DATE, `table_no` STRING (np. `001/A/NBP/2026`), `currency_code` STRING (ISO 4217), `currency_name` STRING NULLABLE, `mid` NUMERIC (PLN za 1 jednostkę), `loaded_at` TIMESTAMP. Zapis i brak partycji: [główne README](../README.md#przepisanie-z-podmianą-zakresu--na-czym-polega-i-dlaczego-tutaj).
