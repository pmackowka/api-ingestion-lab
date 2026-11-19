# api-ingestion-lab

Pobieranie danych z API w Pythonie i ładowanie ich do BigQuery — projekt do nauki inżynierii danych. Każde źródło to osobny pipeline we własnym folderze. Kierunek: ruch i wyszukiwanie (GA4, Search Console) → lead w CRM → faktura w ERP → przychód w PLN, z kontekstem dnia (kurs NBP, pogoda).

## Połączenia

Każdy folder ma własny README z konfiguracją krok po kroku.

| Etap | System i folder | Dane i dostęp | Czego uczy&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; |
|:-:|---|---|---|
| 1<br>*działa* | [API NBP](https://api.nbp.pl/) — kursy walut, tabela A<br>[`nbp/`](nbp/README.md) | prawdziwe<br>(API otwarte) | • GET i JSON<br>• limit 93 dni → dzielenie zakresu na okna<br>• idempotentny zapis do BigQuery |
| 2<br>*działa* | [Open-Meteo](https://open-meteo.com/en/docs/historical-weather-api) — pogoda historyczna (archiwum)<br>[`weather/`](weather/README.md) | prawdziwe<br>(API otwarte, użytek niekomercyjny) | • GET bez klucza, wiele lokalizacji w jednym zapytaniu<br>• strefa czasowa i granice doby (`timezone`)<br>• dane korygowane wstecz: reanaliza ERA5 z opóźnieniem 5 dni → lookback<br>• limit 10 000 wywołań dziennie |
| 3<br>*działa* | [GA4 Data API](https://developers.google.com/analytics/devguides/reporting/data/v1) — ruch na pmdata.pl<br>[`ga4/`](ga4/README.md) | prawdziwe<br>(własna usługa GA4) | • konto usługi / ADC z dostępem do usługi GA4<br>• paginacja `limit`/`offset` (maks. 250 000 wierszy na zapytanie)<br>• limity tokenów (`returnPropertyQuota`)<br>• dane dopisywane wstecz → lookback |
| 4<br>*działa* | [Search Console API](https://developers.google.com/webmaster-tools/v1/searchanalytics/query) — wyniki wyszukiwania pmdata.pl<br>[`search_console/`](search_console/README.md) | prawdziwe<br>(własna usługa) | • paginacja `rowLimit`/`startRow` (maks. 25 000 wierszy)<br>• `dataState`: dane wstępne vs ostateczne<br>• opóźnienie danych o kilka dni |
| 5<br>*działa* | [HubSpot CRM API](https://developers.hubspot.com/docs/api-reference/latest/crm/objects/contacts/guide) — kontakty (leady) i deale<br>[`hubspot/`](hubspot/README.md) | syntetyczne<br>(darmowe konto testowe) | • token statyczny aplikacji z projektu HubSpot CLI<br>• generator: kliknięcia w kontakt z GA4 → leady → deale, `batch/upsert` po e-mailu i własnej unikalnej właściwości, stały seed<br>• powiązania deal → kontakt<br>• paginacja kursorem (`after`)<br>• pełna migawka zamiast przyrostu: rekordy zmienialne, sandbox bez `MERGE`<br>• limit zapytań → 429 i ponowienia |
| 6<br>*działa* | [Odoo](https://www.odoo.com/documentation/19.0/developer/reference/external_api.html) (ERP, Community) — faktury i płatności<br>[`odoo/`](odoo/README.md) | syntetyczne<br>(open source lokalnie) | • Docker: Odoo 20 + PostgreSQL w osobnym projekcie compose<br>• JSON-2 API z kluczem API (XML-RPC wycofane)<br>• generator: faktura do każdego wygranego deala (`deal_key` w `ref`) i płatność po 3–45 dniach<br>• pełna migawka: status płatności zmienia się po wystawieniu |
| 7<br>*planowany* | Model w dbt na BigQuery<br>`model/` | z etapów 1–6 | • warstwy staging → intermediate → marty<br>• lead-to-cash na agregatach `data × źródło`: sesje → kliknięcia w kontakt → leady → deale → faktury<br>• waluta (kurs NBP), pogoda jako wymiar dnia, strefa czasowa, testy dbt |

**Dane i dostęp:**

- *prawdziwe (API otwarte)* — produkcyjne dane bez klucza; Open-Meteo za darmo tylko do użytku niekomercyjnego.
- *prawdziwe (własna usługa)* — ruch z pmdata.pl; strona nie jest sklepem, więc „konwersją” jest kontakt.
- *syntetyczne (darmowe konto testowe)* — prawdziwe API HubSpot na [koncie testowym dewelopera](https://developers.hubspot.com/docs/getting-started/account-types); dane wgrywa nasz skrypt.
- *syntetyczne (open source lokalnie)* — Odoo z fakturami wystawianymi przez nasz skrypt; SAP i polskie ERP nie mają darmowego środowiska z API, a Odoo daje te same typy danych i PostgreSQL do ćwiczenia CDC.

## Klucze łączące źródła

GA4 Data API zwraca agregaty, nie użytkowników, a pmdata.pl nie ma formularza — tylko kliknięcia w e-mail, telefon i LinkedIn. Syntetyczne leady dostają źródło według proporcji źródeł z GA4 w kliknięciach w kontakt, a ich liczba to kliknięcia × założony współczynnik. Dlatego CRM i ERP łączą się kluczami rekordów, a GA4 z resztą — tylko wspólnymi wymiarami `data × źródło`.

```
 POZIOM REKORDU (klucz 1:1 / 1:N, łączy konkretne wiersze)
 ─────────────────────────────────────────────────────────
 raw_hubspot.contacts        raw_hubspot.deals          raw_odoo.invoices          raw_odoo.payments
 ┌──────────────────┐        ┌──────────────────┐       ┌──────────────────┐       ┌──────────────────┐
 │ contact_id   PK  │◄──1:N──│ contact_id   FK  │       │ invoice_id   PK  │◄─1:N──│ invoice_id   FK  │
 │ email            │        │ deal_id      PK  │       │ deal_key (ref)   │       │ payment_id   PK  │
 │ lead_source ─────┼──┐     │ deal_key     UQ  │◄─1:1──│ partner_id       │       │ payment_date     │
 │ lead_date   ─────┼──┤     │ dealstage,amount │       │ invoice_date     │       │ amount           │
 └──────────────────┘  │     │ closedate        │       │ amount_total     │       └──────────────────┘
                       │     └──────────────────┘       │ currency         │
                       │                                └──────────────────┘
 POZIOM AGREGATU (wspólne wymiary: data × źródło, bez użytkowników)
 ──────────────────────│──────────────────────────────────────────────────
                       ▼
               ┌───────────────┐   lead_source = session_source || ' / ' || session_medium
               │   dim_source  │◄──────────────── raw_ga4.traffic_daily, raw_ga4.contact_events_daily
               └───────────────┘                  (report_date, session_source, session_medium)
               ┌───────────────┐   lead_date, invoice_date, payment_date, closedate
               │   dim_date    │◄──────────────── raw_ga4.*.report_date
               └───────┬───────┘                  raw_search_console.*.report_date
                       ├──────── raw_weather.daily_weather.weather_date
                       └──────── raw_nbp.exchange_rates_a.effective_date
```

- Klucze rekordów: `contact_id`, `deal_key` (unikalna właściwość w HubSpot, w Odoo pole `ref` faktury) i `invoice_id`.
- Źródło faktury wynika z łańcucha faktura → deal → kontakt; ruch dochodzi dopiero do sumy `data leada × źródło`, nie do pojedynczej faktury.
- Search Console nie ma wymiaru źródła — w całości to `google / organic`.
- Pogoda i NBP łączą się tylko datą; NBP nie publikuje kursów w weekendy i święta, a tabela A nie zawiera PLN.
- `invoices.partner_id` to klient w Odoo bez e-maila — z kontaktem łączy go `deal_key`, nie partner.

## Jak dane trafiają do BigQuery

Pobranie i spłaszczenie są w `<system>/ingest.py`, zapis (staging + podmiana zakresu) we wspólnej funkcji `replace_date_range` w [`common/bigquery.py`](common/bigquery.py), interfejs CLI w [`common/cli.py`](common/cli.py).

Przykład jednego uruchomienia krok po kroku (NBP): [`nbp/README.md`](nbp/README.md#jedno-uruchomienie-krok-po-kroku).

### Strategie ładowania

Strategia mówi, co zrobić z wierszami już obecnymi w tabeli. Musi być **idempotentna**: ponowne uruchomienie dla tego samego zakresu daje ten sam stan, bez duplikatów. Kolumna „Sandbox” — sprawdzone na żywo, listopad 2026.

| Strategia | Mechanizm w BigQuery | Idempotentna | Koszt uruchomienia | Sandbox | Kiedy |
|---|---|---|---|---|---|
| Pełne przeładowanie | load całej historii, `WRITE_TRUNCATE` | tak | całe źródło | działa | małe tabele, słowniki, źródło usuwa rekordy |
| Append | load, `WRITE_APPEND` | **nie** | nowe dane | działa | niezmienne zdarzenia + deduplikacja niżej (`QUALIFY ROW_NUMBER()` w dbt) |
| Przepisanie z podmianą zakresu (**ten pipeline**) | `SELECT` spoza zakresu `UNION ALL` staging, `WRITE_TRUNCATE_DATA` | tak | cała tabela | działa | małe tabele bez dostępu do DML |
| Nadpisanie partycji | job do `tabela$YYYYMMDD`, `WRITE_TRUNCATE`; dbt: `insert_overwrite` | tak | nadpisane partycje | działa, z pułapką (niżej) | dane dzienne poprawiane wstecz |
| `MERGE` | staging + `MERGE` po kluczu; dbt: `merge` + `unique_key` | tak | skan celu albo partycji | **nie** (403) | rekordy z kluczem zmieniane w dowolnym miejscu historii: CRM, CDC |
| `DELETE` + `INSERT` w transakcji | `BEGIN TRANSACTION … COMMIT TRANSACTION` | tak | zakres + zapis | **nie** (DML) | podmiana zakresu niezgodnego z partycjami |

#### Przepisanie z podmianą zakresu — na czym polega i dlaczego tutaj

Każde uruchomienie buduje tabelę z wierszy **spoza** `[start, end]` i świeżych wierszy z API **za** ten zakres, w jednym query jobie. Gwarancje: idempotencja (stare wiersze z zakresu odfiltrowane), atomowość (błąd zostawia poprzednią wersję), usunięcia ze źródła znikają też z tabeli. To ta sama idea co dbt `insert_overwrite`, tylko na całej tabeli zamiast partycji.

Dlaczego tutaj:
1. Sandbox odrzuca DML (`MERGE`, `DELETE`, `INSERT`) błędem 403; query job z tabelą docelową to nie DML.
2. Partycje odpadają: w sandboxie partycja wygasa 60 dni po **swojej dacie**, więc historia znika od razu po zapisie.
3. Pełne przeładowanie pobierałoby z API całą historię przy każdym uruchomieniu; przepisanie pobiera tylko zakres.
4. Skala na to pozwala: największa tabela (NBP) ma ok. 8 tys. wierszy rocznie, uruchomienie trwa ok. 7 s.

Ograniczenia: koszt rośnie z całą tabelą, nie z zakresem, a dwa równoległe uruchomienia nadpisałyby się nawzajem. Z billingiem: partycje miesięczne + `MERGE` albo nadpisanie partycji.

## Automatyzacja: gdzie uruchamiać ingest

Wdrożony jest wiersz 1: [`.github/workflows/pipeline.yml`](.github/workflows/pipeline.yml), konfiguracja w [docs/konfiguracja.md](docs/konfiguracja.md#github-actions); pozostałe są do porównania.

| # | Rozwiązanie | Koszt | Uwierzytelnianie do BigQuery | Kiedy wybrać / ograniczenia |
|:-:|---|---|---|---|
| 1 | **GitHub Actions** (cron) | 0 zł: publiczne repo za darmo, prywatne w limicie GitHub Free | token OIDC → WIF → krótkotrwały token konta usługi, zero kluczy | małe joby, zespół na GitHubie. Cron bywa opóźniony; w publicznym repo wyłącza się po 60 dniach bez aktywności |
| 2 | **Cloud Run job + Cloud Scheduler** | billing; 180 000 vCPU-s miesięcznie i 3 harmonogramy gratis | konto usługi przypięte do joba | standard GCP dla joba wsadowego; brak zależności między jobami |
| 3 | **AWS: ECS Fargate + EventBridge Scheduler** | konto AWS, płacisz za czas zadania | rola IAM → WIF z dostawcą AWS | organizacja na AWS; Lambda tylko do 15 min |
| 4 | **Azure: Container Apps job** | subskrypcja Azure, płacisz za czas | managed identity → WIF z Entra ID | organizacja na Azure; wbudowane ponowienia |
| 5 | **Databricks: Lakeflow Jobs** | workspace Databricks | WIF (dostawca AWS albo Entra ID) | lakehouse na Databricks — tam hurtownią zwykle jest sam Databricks |
| 6 | **Airflow: Cloud Composer** | billing, środowisko płatne także bez uruchomień | konto usługi środowiska | wiele zależnych kroków, backfill zakresu dat, stan całego potoku. Dla kilku skryptów przerost |
