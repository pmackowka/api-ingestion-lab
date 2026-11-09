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

## Kod

Cały pipeline jest w `ingest.py`. Każda funkcja i każdy blok ma komentarz: co robi, po co i dlaczego tak. Kolejność czytania: `main` → `split_windows` → `fetch_window` → `to_rows` → `load_to_bigquery`.

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

Tabela nie jest partycjonowana — powód w sekcji „Strategie ładowania”.

## Strategie ładowania

Strategia mówi, co zrobić z danymi już obecnymi w tabeli, gdy przychodzą nowe. Musi być **idempotentna**: ponowne uruchomienie dla tego samego zakresu daje ten sam stan tabeli, więc restart, backfill ani podwójne uruchomienie nie tworzą duplikatów. Porównanie zakłada projekt z billingiem; kolumna „Sandbox” pokazuje, co działa tutaj (sprawdzone na żywo, listopad 2026).

| Strategia | Mechanizm w BigQuery | Idempotentna | Koszt uruchomienia | Sandbox | Kiedy |
|---|---|---|---|---|---|
| Pełne przeładowanie | load całej historii, `WRITE_TRUNCATE` | tak | całe źródło | działa | małe tabele, słowniki, źródło usuwa rekordy |
| Append | load, `WRITE_APPEND` | **nie** | nowe dane | działa | niezmienne zdarzenia + deduplikacja niżej (`QUALIFY ROW_NUMBER()` w dbt) |
| Przepisanie z podmianą zakresu (**ten pipeline**) | `SELECT` spoza zakresu `UNION ALL` staging, `WRITE_TRUNCATE_DATA` | tak | cała tabela | działa | małe tabele bez dostępu do DML |
| Nadpisanie partycji | job do `tabela$YYYYMMDD`, `WRITE_TRUNCATE`; dbt: `insert_overwrite` | tak | nadpisane partycje | działa, z pułapką (niżej) | dane dzienne poprawiane wstecz: przeładuj ostatnie N dni |
| `MERGE` | staging + `MERGE` po kluczu; dbt: `merge` + `unique_key` (domyślna) | tak | skan celu; z filtrem partycji tylko jej część | **nie** (403) | rekordy z kluczem zmieniane w dowolnym miejscu historii: zamówienia, CRM, CDC |
| `DELETE` + `INSERT` w transakcji | `BEGIN TRANSACTION … COMMIT TRANSACTION` | tak | zakres + zapis | **nie** (DML) | podmiana zakresu niezgodnego z partycjami |

### Jak wybrać

1. **Całość mała i tania?** Pełne przeładowanie. Progu w GB nie ma — granicą jest okno czasowe joba, limity API albo budżet na skanowane bajty.
2. **Zmiany tylko w ostatnich dniach?** Nadpisanie partycji z lookbackiem. GA4 [poprawia dzienne tabele eksportu](https://support.google.com/analytics/answer/9358801) przez 2 dni plus dzień bieżący, więc job przeładowuje 3 partycje. Platformy reklamowe działają podobnie: konwersje dopisują się wstecz przez okno atrybucji.
3. **Dowolny rekord może się zmienić i ma klucz?** `MERGE`, z filtrem partycji w `ON`/`WHEN`, żeby BigQuery [przycinał skan](https://docs.cloud.google.com/bigquery/docs/using-dml-with-partitioned-tables).
4. **Dane tylko przyrastają?** Append z deduplikacją albo — bezpieczniej przy restartach — nadpisanie partycji dnia.

[Limity](https://docs.cloud.google.com/bigquery/quotas) widoczne dopiero przy skali: DML na jednej tabeli maks. 2 naraz i 20 w kolejce, więc równoległe joby piszące przez `MERGE` czekają na siebie; 1500 load jobów na tabelę dziennie; 30 000 modyfikacji partycji na tabelę dziennie.

### Dlaczego tu przepisanie tabeli

- Ok. 8 tys. wierszy rocznie; całe uruchomienie trwa ok. 7 s (zmierzone).
- Sandbox blokuje DML, a partycjonowanie po dacie kasowałoby historię (pułapka niżej).
- Z billingiem: partycje miesięczne po `effective_date` + `MERGE` albo nadpisanie partycji. Przy tej skali oba warianty są równie dobre; partycje dzienne z 32 wierszami to przerost.

Skrypt pobiera z API tylko `[--start, --end]`. Przy codziennym harmonogramie wystarczy `--start` = dziś minus 7 dni — tydzień zapasu nic nie kosztuje, a łata dni, w które job nie ruszył (awaria, wyłączony komputer, długi weekend), bez ręcznego backfillu.

## Konfiguracja krok po kroku

1. Wykonaj „Wspólne środowisko” z [głównego README](../README.md).
2. Utwórz projekt GCP (billing niepotrzebny) i sprawdź BigQuery API: `gcloud services list --enabled --project=<projekt-gcp> | grep bigquery`. Brak → `gcloud services enable bigquery.googleapis.com --project=<projekt-gcp>`.
3. Uruchom: `uv run python nbp/ingest.py --project <projekt-gcp> --start 2025-01-01`. Domyślnie `--end` = dziś, `--dataset` = `raw_nbp`; dataset i tabele powstają same.
4. Sprawdź duplikaty — obie liczby muszą być równe:
   ```
   bq query --use_legacy_sql=false 'SELECT COUNT(*), COUNT(DISTINCT FORMAT("%t|%s", effective_date, currency_code)) FROM raw_nbp.exchange_rates_a'
   ```
5. Testy: `uv run pytest nbp`.

## Pułapki

- **Quota project ADC wskazuje usunięty projekt** → `400 ... Project 'projects/<stary-projekt>' not found or deleted` mimo poprawnego `--project`. Fix: `gcloud auth application-default set-quota-project <projekt-gcp>`.
- **Sandbox:** tabela wygasa 60 dni po utworzeniu — wtedy załaduj pełny zakres od nowa. Partycja wygasa 60 dni po **swojej dacie**, więc historia w tabeli partycjonowanej po dacie znika od razu po zapisie.
- **`BGN` od 2026:** brak kursu lewa — etap 6 musi to obsłużyć.
