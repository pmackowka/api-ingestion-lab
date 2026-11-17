# NBP — kursy średnie walut (tabela A) → BigQuery

Pobiera kursy średnie NBP z publicznego API i zapisuje je w BigQuery. Kursy przydadzą się w etapie 7 do przeliczania przychodów z EUR i USD na PLN.

## Przykładowe uruchomienia

Każde uruchomienie podmienia w tabeli tylko zakres `[--start, --end]`; domyślnie `--end` = dziś. Skrypt nie sprawdza, do jakiego dnia tabela ma już dane — po przerwie podaj `--start`.

```bash
# Backfill: cała historia od 2025 roku — pierwsze uruchomienie albo po wygaśnięciu tabeli w sandboxie.
uv run python nbp/ingest.py --project api-ingestion-lab-bq --start 2025-01-01

# Codzienny przyrost: podmienia ostatnie 8 dni kalendarzowych (dziś i 7 wstecz), łata dzień czy dwa przestoju.
uv run python nbp/ingest.py --project api-ingestion-lab-bq --lookback-days 7

# Nadrabianie po dłuższej przerwie: wszystko od dnia po ostatnim załadowanym, bez luki.
uv run python nbp/ingest.py --project api-ingestion-lab-bq --start 2026-11-17

# Ponowne załadowanie jednego okresu (tu I kwartał), np. po błędzie w danych; reszta tabeli bez zmian.
uv run python nbp/ingest.py --project api-ingestion-lab-bq --start 2026-01-01 --end 2026-03-31

# Osobny dataset do eksperymentów, bez ruszania raw_nbp.
uv run python nbp/ingest.py --project api-ingestion-lab-bq --dataset raw_nbp_test --start 2026-11-01
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

Cały pipeline jest w `ingest.py`; każdy blok ma komentarz: co robi, po co i dlaczego tak. SQL z kroku 4b też tam jest — jako tekst, który Python wysyła przez `client.query()`, a wykonuje BigQuery.

Przykład: `--lookback-days 7` uruchomione 17.11.2026, tabela ma dane od 02.01.2025 do 14.11.2026, a NBP poprawiło kurs z 12.11.

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

- Treść zmienia się tylko w zakresie `[start, end]`, ale BigQuery zapisuje całą tabelę od nowa — stąd koszt „cała tabela” w porównaniu strategii niżej. Historia pochodzi ze starej wersji tabeli, nie z API.
- Bez filtra `NOT BETWEEN` dni 10–14.11 byłyby w tabeli dwa razy; bez części `SELECT … FROM exchange_rates_a` zostałby sam staging, czyli 8 dni.

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

### Przepisanie z podmianą zakresu — na czym polega i dlaczego tutaj

**Mechanizm.** Każde uruchomienie buduje tabelę od nowa z dwóch części: wierszy, które już w niej są **poza** zakresem `[start, end]`, i świeżych wierszy z API **za** ten zakres (staging). Wynik zastępuje tabelę w jednym query jobie (diagram w „Jak działa jedno uruchomienie”). Treść zmienia się tylko w zakresie; reszta jest przepisywana bez zmian ze starej wersji tabeli, nie pobierana ponownie z API.

**Gwarancje.**
- Idempotencja: stare wiersze z zakresu są odfiltrowane (`NOT BETWEEN`), więc każda para `(effective_date, currency_code)` z zakresu pochodzi wyłącznie ze stagingu — ponowne uruchomienie nie tworzy duplikatów.
- Atomowość: BigQuery podmienia tabelę dopiero po zakończeniu zapytania. Błąd w połowie zostawia poprzednią wersję w całości.
- Usunięcia ze źródła: wiersz z zakresu, którego API już nie zwraca, znika z tabeli — `MERGE` bez klauzuli `WHEN NOT MATCHED BY SOURCE` by go zostawił.

**Czy to typowe?** Nie jako nazwa — to robocza nazwa tego repo. Jako idea: tak, to podmiana zakresu, ta sama co w nadpisywaniu partycji (dbt `insert_overwrite`), tylko na poziomie całej tabeli zamiast partycji. W produkcji z billingiem standardem są `MERGE` albo nadpisanie partycji; przepisanie całej tabeli spotkasz przy małych tabelach referencyjnych (kursy, słowniki, kalendarze) i tam, gdzie DML jest niedostępny.

**Dlaczego tutaj.**
1. Sandbox odrzuca DML (`MERGE`, `DELETE`, `INSERT`) błędem 403. Query job z tabelą docelową to nie DML, więc działa.
2. Nadpisanie partycji odpada: w sandboxie partycja wygasa 60 dni po **swojej dacie**, więc tabela partycjonowana po `effective_date` traci historię od razu po zapisie (sprawdzone na żywo).
3. Pełne przeładowanie z API też by działało, ale przy każdym uruchomieniu pobierałoby całą historię oknami po 93 dni. Przepisanie pobiera z API tylko zakres — historię bierze z własnej tabeli.
4. Skala to umożliwia: ok. 8 tys. wierszy rocznie, całe uruchomienie trwa ok. 7 s (zmierzone).

**Koszt i ograniczenia.**
- Każde uruchomienie skanuje i zapisuje całą tabelę, także przy `--lookback-days 7` — koszt rośnie z historią, nie z zakresem. Przy milionach wierszy to przestaje mieć sens.
- Dwa równoległe uruchomienia czytają tę samą starą wersję, więc wygrywa to, które skończy później, a zmiany pierwszego przepadają. Przy jednym harmonogramie dziennym nie występuje.
- Z billingiem zmieniłbym na partycje miesięczne po `effective_date` + `MERGE` albo nadpisanie partycji; partycje dzienne z 32 wierszami to przerost.
