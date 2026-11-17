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

Skrypt pobiera z API tylko `[--start, --end]`. Przy codziennym harmonogramie użyj `--lookback-days 7` zamiast `--start` — tydzień zapasu nic nie kosztuje, a łata dni, w które job nie ruszył (awaria, wyłączony komputer, długi weekend), bez ręcznego backfillu.

## Konfiguracja krok po kroku

1. Wykonaj „Wspólne środowisko” z [głównego README](../README.md).
2. Utwórz projekt GCP (billing niepotrzebny) i sprawdź BigQuery API: `gcloud services list --enabled --project=<projekt-gcp> | grep bigquery`. Brak → `gcloud services enable bigquery.googleapis.com --project=<projekt-gcp>`.
3. Uruchom backfill: `uv run python nbp/ingest.py --project <projekt-gcp> --start 2025-01-01`. Przy harmonogramie zamiast `--start` podaj `--lookback-days 7`. Domyślnie `--end` = dziś, `--dataset` = `raw_nbp`; dataset i tabele powstają same.
4. Sprawdź duplikaty — obie liczby muszą być równe:
   ```
   bq query --use_legacy_sql=false 'SELECT COUNT(*), COUNT(DISTINCT FORMAT("%t|%s", effective_date, currency_code)) FROM raw_nbp.exchange_rates_a'
   ```
5. Testy: `uv run pytest nbp`.

## Pułapki

- **Quota project ADC wskazuje usunięty projekt** → `400 ... Project 'projects/<stary-projekt>' not found or deleted` mimo poprawnego `--project`. Fix: `gcloud auth application-default set-quota-project <projekt-gcp>`.
- **Sandbox:** tabela wygasa 60 dni po utworzeniu — wtedy załaduj pełny zakres od nowa. Partycja wygasa 60 dni po **swojej dacie**, więc historia w tabeli partycjonowanej po dacie znika od razu po zapisie.
- **Godzina uruchomienia:** NBP publikuje tabelę A w dni robocze między 11:45 a 12:15 czasu polskiego ([terminy](https://nbp.pl/statystyka-i-sprawozdawczosc/kursy/informacja-o-terminach-publikacji-kursow-walut/)). Uruchomienie wcześniej nie złapie kursu z bieżącego dnia — lookback dociągnie go następnego dnia.
- **`BGN` od 2026:** brak kursu lewa — etap 7 musi to obsłużyć.
