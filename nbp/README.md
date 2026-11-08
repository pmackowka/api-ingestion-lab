# NBP — kursy średnie walut (tabela A) → BigQuery

Pobiera kursy średnie NBP z publicznego API i zapisuje je w BigQuery. Kursy przydadzą się w etapie 6 do przeliczania przychodów z EUR i USD na PLN.

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

## Jak to działa

Cały kod jest w `ingest.py`. Komentarze w kodzie tłumaczą każdą decyzję.

1. `split_windows` dzieli zakres dat na okna po 93 dni kalendarzowe. To 1 dzień zapasu względem limitu API.
2. `fetch_window` pobiera jedno okno. Odpowiedź 404 zamienia na pustą listę, bo to brak notowań, a nie błąd. Kursy parsuje przez `Decimal`, nie `float`, żeby nie tracić precyzji.
3. `to_rows` spłaszcza odpowiedź: tabela z N walutami daje N wierszy.
4. `load_to_bigquery` zapisuje dane w dwóch krokach:
   - load job wgrywa wszystkie wiersze do `_staging_exchange_rates_a` i za każdym razem nadpisuje tę tabelę (`WRITE_TRUNCATE`). Schemat z `REQUIRED` odrzuca wiersz z brakującą wartością.
   - query job przepisuje tabelę `exchange_rates_a`: zostawia wiersze spoza zakresu `[start, end]`, dokleja świeże wiersze ze staging i nadpisuje tabelę (`WRITE_TRUNCATE`).

Dzięki temu zakres dat jest zawsze zastępowany w całości. Ponowne uruchomienie dla tego samego zakresu niczego nie dubluje — to jest idempotencja.

Dlaczego nie `MERGE`: sandbox BigQuery (projekt bez billingu) nie obsługuje poleceń DML ([dokumentacja](https://docs.cloud.google.com/bigquery/docs/sandbox)). Query job z tabelą docelową to nie DML, więc działa. Jego koszt: każde uruchomienie przepisuje całą tabelę. Przy kilku MB to bez znaczenia. Przy dużej tabeli wróciłbym do `MERGE` albo nadpisywania pojedynczych partycji.

## Tabela docelowa

`<projekt>.raw_nbp.exchange_rates_a`, klucz: `(effective_date, currency_code)`.

| Kolumna | Typ | Znaczenie |
|---|---|---|
| `effective_date` | DATE | dzień notowania |
| `table_no` | STRING | numer tabeli NBP, np. `001/A/NBP/2026` |
| `currency_code` | STRING | kod ISO 4217, np. `EUR` |
| `currency_name` | STRING | nazwa waluty po polsku |
| `mid` | NUMERIC | kurs średni w PLN za 1 jednostkę waluty |
| `loaded_at` | TIMESTAMP | czas uruchomienia, które zapisało wiersz (UTC) |

Wszystkie kolumny są `NULLABLE`. Query job z `WRITE_TRUNCATE` nadpisuje schemat tabeli razem z danymi, więc `REQUIRED` znika. Kompletność danych pilnuje wcześniej load do staging.

## Konfiguracja krok po kroku

1. Wykonaj kroki z sekcji „Wspólne środowisko” w [głównym README](../README.md).
2. Utwórz projekt GCP, np. w Console → „Nowy projekt”. Billing nie jest potrzebny.
3. Sprawdź, czy BigQuery API jest włączone: `gcloud services list --enabled --project=<projekt-gcp> | grep bigquery`. Jeśli nie, włącz je: `gcloud services enable bigquery.googleapis.com --project=<projekt-gcp>`.
4. Uruchom pobieranie:
   ```
   uv run python nbp/ingest.py --project <projekt-gcp> --start 2025-01-01
   ```
   `--end` domyślnie przyjmuje dzisiejszą datę, `--dataset` domyślnie `raw_nbp`. Skrypt sam tworzy dataset i tabele, jeśli ich nie ma.
5. Sprawdź duplikaty. Obie liczby muszą być równe:
   ```
   bq query --use_legacy_sql=false 'SELECT COUNT(*), COUNT(DISTINCT FORMAT("%t|%s", effective_date, currency_code)) FROM raw_nbp.exchange_rates_a'
   ```
6. Uruchom testy: `uv run pytest nbp`.

## Pułapki

- **Projekt rozliczeniowy ADC wskazuje usunięty projekt** → błąd `400 ... Project 'projects/<stary-projekt>' not found or deleted`, nawet jeśli `--project` jest poprawny. Napraw komendą `gcloud auth application-default set-quota-project <projekt-gcp>`.
- **Sandbox:** tabele wygasają po 60 dniach od utworzenia. Po wygaśnięciu uruchom skrypt ponownie z pełnym zakresem dat.
- **`BGN` od 2026 roku:** przeliczenie po kursie z tego samego dnia nie znajdzie kursu lewa. Etap 6 musi to obsłużyć.
