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

Strategia ładowania odpowiada na pytanie: co zrobić z danymi, które już są w tabeli, gdy przychodzą nowe? Dobra strategia jest **idempotentna**: ponowne uruchomienie dla tego samego zakresu daje ten sam stan tabeli. Bez tego każdy restart po awarii, backfill albo podwójne uruchomienie z harmonogramu tworzy duplikaty.

Porównanie zakłada projekt z billingiem, czyli dostępne są wszystkie opcje. Kolumna „Sandbox” mówi, co działa w tym projekcie (sprawdzone na żywo, listopad 2026).

| Strategia | Jak w BigQuery | Idempotentna | Koszt jednego uruchomienia | Sandbox | Kiedy |
|---|---|---|---|---|---|
| Pełne przeładowanie (full refresh) | pobierz całą historię z API, load z `WRITE_TRUNCATE` | tak | całe źródło: transfer z API + zapis całej tabeli | działa | małe tabele, słowniki, API bez filtra dat, źródło, które usuwa rekordy |
| Dopisywanie (append) | load z `WRITE_APPEND` | **nie** — ponowne uruchomienie dubluje wiersze | tylko nowe dane | działa | niezmienne zdarzenia (logi, kliknięcia) + deduplikacja niżej, np. `QUALIFY ROW_NUMBER()` w modelu dbt |
| Przepisanie tabeli z podmianą zakresu (**ten pipeline**) | query job: `SELECT` spoza zakresu `UNION ALL` staging, `WRITE_TRUNCATE_DATA` | tak | odczyt i zapis **całej** tabeli — rośnie z jej rozmiarem | działa | małe tabele w sandboxie, gdzie DML jest zablokowany |
| Nadpisanie partycji (partition overwrite) | tabela partycjonowana po dacie; load albo query job do `tabela$YYYYMMDD` z `WRITE_TRUNCATE`; w dbt: `insert_overwrite` | tak | tylko nadpisane partycje | działa, ale partycje starsze niż 60 dni wygasają od razu | dane dzienne z późnymi poprawkami: przeładuj ostatnie N dni (lookback) |
| `MERGE` (upsert) | staging + `MERGE` po kluczu: `UPDATE` istniejących, `INSERT` nowych; w dbt: `merge` z `unique_key` (domyślna strategia) | tak | skan tabeli docelowej — mały, jeśli filtr w `ON`/`WHEN` przycina partycje; pełny, jeśli nie | **nie** — 403 | rekordy z kluczem, które mogą zmienić się w dowolnym miejscu historii: zamówienia ze statusem, CRM, CDC |
| `DELETE` + `INSERT` w transakcji | `BEGIN TRANSACTION; DELETE ... ; INSERT ... ; COMMIT TRANSACTION;` | tak | skan zakresu do usunięcia + zapis nowych | **nie** — to DML | podmiana zakresu, który nie pokrywa się z partycjami, np. w tabeli niepartycjonowanej |

### Jak wybrać

1. **Czy całość jest mała i tania do pobrania?** Wybierz pełne przeładowanie — zero logiki stanu, zero ryzyka rozjazdu. Nie ma progu w GB. Granica przychodzi wtedy, gdy pobranie albo przepisanie całości nie mieści się w oknie uruchomienia, w limitach API albo w budżecie na skanowane bajty.
2. **Czy zmiany dotyczą tylko ostatnich dni?** Wybierz nadpisanie partycji z lookbackiem. Przykład: GA4 [aktualizuje dzienne tabele eksportu](https://support.google.com/analytics/answer/9358801) przez 2 dni kalendarzowe plus dzień bieżący, więc codzienny job przeładowuje 3 ostatnie partycje. Platformy reklamowe działają podobnie: konwersje dopisują się wstecz przez okno atrybucji.
3. **Czy dowolny rekord z historii może się zmienić i ma unikalny klucz?** Wybierz `MERGE`. Jeśli zmiany mieszczą się w znanym oknie dat, dodaj filtr partycji w warunku `ON` albo `WHEN` — wtedy BigQuery [przycina partycje](https://docs.cloud.google.com/bigquery/docs/using-dml-with-partitioned-tables) zamiast skanować całą tabelę.
4. **Czy dane tylko przyrastają i nigdy się nie zmieniają?** Dopisywanie wystarczy, ale z deduplikacją niżej. Często bezpieczniej i tak nadpisywać partycję dnia — restart joba nie zrobi wtedy duplikatów.

Limity, o które pytają na rozmowach, bo wychodzą dopiero przy skali ([quotas](https://docs.cloud.google.com/bigquery/quotas)):

- `MERGE`, `UPDATE` i `DELETE` na tej samej tabeli: maks. 2 naraz, 20 w kolejce. Równoległe joby piszące do jednej tabeli przez DML czekają na siebie.
- Load joby: 1500 na tabelę dziennie, wliczając nieudane.
- Modyfikacje partycji: 30 000 na tabelę partycjonowaną po kolumnie dziennie.

### Dlaczego tu przepisanie tabeli

- Tabela jest mała: ok. 8 tys. wierszy rocznie. Całe uruchomienie z przepisaniem tabeli trwa ok. 7 s (zmierzone) i mieści się w darmowym limicie.
- Sandbox blokuje DML, więc `MERGE` i transakcja odpadają.
- Nadpisywanie partycji działa w sandboxie, ale sandbox ustawia partycjom wygasanie po 60 dniach od daty partycji. Tabela kursów partycjonowana po `effective_date` traciłaby od razu całą historię starszą niż 60 dni — test potwierdził, że takie partycje znikają natychmiast po zapisie.
- Z billingiem: tabela partycjonowana po `effective_date` (miesięcznie, bo dzienna partycja z 32 wierszami to przerost) + `MERGE` albo nadpisanie partycji. Przy tej skali oba warianty są równie dobre.

**Ile pobierać przy codziennym uruchomieniu.** Skrypt pobiera z API tylko zakres `[--start, --end]`, nie całą historię. W BigQuery przepisuje całą tabelę, ale podmienia tylko ten zakres. Przy codziennym harmonogramie wystarczy `--start` = dziś minus 7 dni. Tydzień zapasu nic nie kosztuje, a łata dni, w które job nie ruszył (awaria, wyłączony komputer, długi weekend), bez ręcznego backfillu.

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
- **Sandbox i partycje:** partycja wygasa 60 dni po swojej dacie, nie po dacie zapisu. Historyczne dane w tabeli partycjonowanej po dacie znikają od razu.
- **`BGN` od 2026 roku:** przeliczenie po kursie z tego samego dnia nie znajdzie kursu lewa. Etap 6 musi to obsłużyć.
