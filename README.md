# api-ingestion-lab

Pobieranie danych z API w Pythonie i ładowanie ich do BigQuery — projekt do nauki inżynierii danych. Każde źródło to osobny pipeline we własnym folderze, z komentarzami po polsku tłumaczącymi mechanizm. Kierunek: ruch i wyszukiwanie (GA4, Search Console) → lead w CRM → faktura w ERP → przychód w PLN, z kontekstem dnia (kurs NBP, pogoda).

## Połączenia

Każdy folder ma własny README z konfiguracją krok po kroku.

| Etap | System i folder | Dane i dostęp | Czego uczy&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; |
|:-:|---|---|---|
| 1<br>*działa* | [API NBP](https://api.nbp.pl/) — kursy walut, tabela A<br>[`nbp/`](nbp/README.md) | prawdziwe<br>(API otwarte) | • GET i JSON<br>• limit 93 dni → dzielenie zakresu na okna<br>• idempotentny zapis do BigQuery |
| 2<br>*działa* | [Open-Meteo](https://open-meteo.com/en/docs/historical-weather-api) — pogoda historyczna (archiwum)<br>[`weather/`](weather/README.md) | prawdziwe<br>(API otwarte, użytek niekomercyjny) | • GET bez klucza, wiele lokalizacji w jednym zapytaniu<br>• strefa czasowa i granice doby (`timezone`)<br>• dane korygowane wstecz: reanaliza ERA5 z opóźnieniem 5 dni → lookback<br>• limit 10 000 wywołań dziennie |
| 3<br>*działa* | [GA4 Data API](https://developers.google.com/analytics/devguides/reporting/data/v1) — ruch na pmdata.pl<br>[`ga4/`](ga4/README.md) | prawdziwe<br>(własna usługa GA4) | • konto usługi / ADC z dostępem do usługi GA4<br>• paginacja `limit`/`offset` (maks. 250 000 wierszy na zapytanie)<br>• limity tokenów (`returnPropertyQuota`)<br>• dane dopisywane wstecz → lookback |
| 4<br>*działa* | [Search Console API](https://developers.google.com/webmaster-tools/v1/searchanalytics/query) — wyniki wyszukiwania pmdata.pl<br>[`search_console/`](search_console/README.md) | prawdziwe<br>(własna usługa) | • paginacja `rowLimit`/`startRow` (maks. 25 000 wierszy)<br>• `dataState`: dane wstępne vs ostateczne<br>• opóźnienie danych o kilka dni |
| 5<br>*planowany* | [HubSpot CRM API](https://developers.hubspot.com/docs/api/crm/understanding-the-crm) — kontakty, firmy, deale<br>`hubspot/` | syntetyczne<br>(darmowe konto testowe) | • bearer token aplikacji prywatnej<br>• źródło leada (UTM) losowane według proporcji źródeł z GA4<br>• paginacja kursorem (`after`)<br>• przyrost po `lastmodifieddate` przez search API<br>• limit zapytań → 429 i ponowienia |
| 6<br>*planowany* | [Odoo](https://www.odoo.com/documentation/19.0/developer/reference/external_api.html) (ERP, Community) — zamówienia, faktury<br>`odoo/` | syntetyczne<br>(open source lokalnie) | • Docker: Odoo + PostgreSQL z danymi demo<br>• JSON-2 API z kluczem API<br>• przyrost po `write_date`, rekordy zmieniane i usuwane<br>• baza transakcyjna → CDC z PostgreSQL |
| 7<br>*planowany* | Model w dbt na BigQuery<br>`model/` | z etapów 1–6 | • warstwy staging → intermediate → marty<br>• lead-to-cash na agregatach `data × źródło`: sesje → kliknięcia w kontakt → leady → deale → faktury<br>• waluta (kurs NBP), pogoda jako wymiar dnia, strefa czasowa, testy dbt |

**Dane i dostęp:**

- *prawdziwe (API otwarte)* — produkcyjne dane bez klucza; Open-Meteo za darmo tylko do użytku niekomercyjnego.
- *prawdziwe (własna usługa)* — ruch z pmdata.pl; strona nie jest sklepem, więc „konwersją” jest kontakt.
- *syntetyczne (darmowe konto testowe)* — prawdziwe API HubSpot na [koncie testowym dewelopera](https://developers.hubspot.com/docs/getting-started/account-types); dane wgrywa nasz skrypt.
- *syntetyczne (open source lokalnie)* — Odoo z danymi demo; SAP i polskie ERP nie mają darmowego środowiska z API, a Odoo daje te same typy danych i PostgreSQL do ćwiczenia CDC.

Jak łączą się źródła: GA4 Data API zwraca agregaty, nie użytkowników, a pmdata.pl nie ma formularza — tylko kliknięcia w e-mail, telefon i LinkedIn. Złączenie jest więc po `data × źródło`: syntetyczne leady dostają źródło według proporcji źródeł z GA4 w kliknięciach w kontakt, a ich liczba to kliknięcia × założony współczynnik.

## Jak dane trafiają do BigQuery

Pobranie i spłaszczenie są w `<system>/ingest.py`, zapis (kroki 4a i 4b) we wspólnej funkcji `replace_date_range` w [`common/bigquery.py`](common/bigquery.py), interfejs CLI w [`common/cli.py`](common/cli.py).

### Jedno uruchomienie krok po kroku (przykład: NBP)

`--lookback-days 7` uruchomione 17.11.2026; tabela ma dane od 02.01.2025 do 14.11.2026, a NBP poprawiło kurs z 12.11.

```
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
```

Treść zmienia się tylko w zakresie `[start, end]`, ale BigQuery zapisuje całą tabelę od nowa; historia pochodzi ze starej wersji tabeli, nie z API. Bez `NOT BETWEEN` dni 10–14.11 byłyby dwa razy.

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

Wdrożony jest wiersz 1 ([niżej](#automatyzacja-w-github-actions)); pozostałe są do porównania.

| # | Rozwiązanie | Koszt | Uwierzytelnianie do BigQuery | Kiedy wybrać / ograniczenia |
|:-:|---|---|---|---|
| 1 | **GitHub Actions** (cron) | 0 zł: publiczne repo za darmo, prywatne w limicie GitHub Free | token OIDC → WIF → krótkotrwały token konta usługi, zero kluczy | małe joby, zespół na GitHubie. Cron bywa opóźniony; w publicznym repo wyłącza się po 60 dniach bez aktywności |
| 2 | **Cloud Run job + Cloud Scheduler** | billing; 180 000 vCPU-s miesięcznie i 3 harmonogramy gratis | konto usługi przypięte do joba | standard GCP dla joba wsadowego; brak zależności między jobami |
| 3 | **AWS: ECS Fargate + EventBridge Scheduler** | konto AWS, płacisz za czas zadania | rola IAM → WIF z dostawcą AWS | organizacja na AWS; Lambda tylko do 15 min |
| 4 | **Azure: Container Apps job** | subskrypcja Azure, płacisz za czas | managed identity → WIF z Entra ID | organizacja na Azure; wbudowane ponowienia |
| 5 | **Databricks: Lakeflow Jobs** | workspace Databricks | WIF (dostawca AWS albo Entra ID) | lakehouse na Databricks — tam hurtownią zwykle jest sam Databricks |
| 6 | **Airflow: Cloud Composer** | billing, środowisko płatne także bez uruchomień | konto usługi środowiska | wiele zależnych kroków, backfill zakresu dat, stan całego potoku. Dla kilku skryptów przerost |

### Automatyzacja w GitHub Actions

Workflow [`.github/workflows/pipeline.yml`](.github/workflows/pipeline.yml) codziennie o 3:41 czasu polskiego uruchamia każde źródło z `--lookback-days 7` jako osobny job macierzy — awaria jednego nie zatrzymuje pozostałych. Porównanie wariantów: [docs/orkiestracja.md](docs/orkiestracja.md).

Konfiguracja (raz, po „Wspólnym środowisku”):

```bash
PROJECT=api-ingestion-lab-bq
REPO=<właściciel>/<repo>                 # repo na GitHubie, np. pmackowka/api-ingestion-lab
SA=ingest-runner@$PROJECT.iam.gserviceaccount.com
PROJECT_NUMBER=$(gcloud projects describe $PROJECT --format="value(projectNumber)")   # ścieżki WIF wymagają numeru, nie ID

# 1. API do wymiany tokenów (STS) i wystawiania tokenów konta usługi.
gcloud services enable sts.googleapis.com iamcredentials.googleapis.com --project=$PROJECT

# 2. Pula Workload Identity: miejsce w GCP na tożsamości spoza Google (tu: GitHub).
gcloud iam workload-identity-pools create github --project=$PROJECT --location=global --display-name="GitHub Actions Pool"

# 3. Dostawca OIDC: ufa tokenom GitHuba, mapuje ich pola na atrybuty i wpuszcza tylko jedno repo.
gcloud iam workload-identity-pools providers create-oidc api-ingestion-lab --project=$PROJECT --location=global \
  --workload-identity-pool=github --display-name="GitHub api-ingestion-lab" \
  --issuer-uri="https://token.actions.githubusercontent.com" \
  --attribute-mapping="google.subject=assertion.sub,attribute.actor=assertion.actor,attribute.repository=assertion.repository,attribute.repository_owner=assertion.repository_owner" \
  --attribute-condition="assertion.repository == '$REPO'"

# 4. Repo może działać jako konto usługi — z jego dostępem do BigQuery, GA4 i Search Console.
gcloud iam service-accounts add-iam-policy-binding $SA --project=$PROJECT --role=roles/iam.workloadIdentityUser \
  --member="principalSet://iam.googleapis.com/projects/$PROJECT_NUMBER/locations/global/workloadIdentityPools/github/attribute.repository/$REPO"

# 5. Wartość do pola workload_identity_provider w pipeline.yml.
gcloud iam workload-identity-pools providers describe api-ingestion-lab --project=$PROJECT --location=global --workload-identity-pool=github --format="value(name)"

# 6. Ręczny przebieg testowy i podgląd na żywo.
gh workflow run pipeline.yml && gh run watch
```

Źródło komend: [google-github-actions/auth — WIF przez konto usługi](https://github.com/google-github-actions/auth#indirect-wif) (sprawdzone 2026-11-18). Wariant przez konto usługi, a nie bezpośredni, bo GA4 i Search Console nadają dostęp po adresie e-mail, a ten ma tylko konto usługi.

### Scenariusz dla Airflow (wiersz 6)

Jeden DAG dziennie: równoległe ingesty jako Cloud Run joby (`CloudRunExecuteJobOperator`) z ponowieniami per źródło → `dbt build` dopiero po wszystkich → testy dbt jako bramka → alert przy porażce, a zadania zależne dostają `upstream_failed`. Zależności i ponowienia ma też GitHub Actions (`needs:`, „Re-run failed jobs”); Airflow wygrywa datą logiczną przebiegu, stanem per zadanie i backfillem zakresu dat jednym poleceniem.

Źródła (sprawdzone 2026-11-16): [GitHub Actions – schedule](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows), [GitHub Actions – rozliczenia](https://docs.github.com/en/billing/concepts/product-billing/github-actions), [Cloud Run – ceny](https://cloud.google.com/run/pricing), [Cloud Scheduler – ceny](https://cloud.google.com/scheduler/pricing), [WIF z AWS i Azure](https://docs.cloud.google.com/iam/docs/workload-identity-federation-with-other-clouds), [Lambda – timeout](https://docs.aws.amazon.com/lambda/latest/dg/configuration-timeout.html), [Databricks → BigQuery](https://docs.databricks.com/aws/en/connect/external-systems/bigquery), [Composer – ceny](https://cloud.google.com/composer/pricing), [Airflow – backfill](https://airflow.apache.org/docs/apache-airflow/stable/core-concepts/backfill.html).

## Wspólne środowisko

Foldery są niezależne od siebie, ale dzielą jedno środowisko Pythona (`pyproject.toml`) i jedną tożsamość w GCP: konto usługi `ingest-runner`, pod które podszywasz się lokalnie (impersonation) — bez pliku z kluczem. Wymagane: [uv](https://docs.astral.sh/uv/) i [gcloud CLI](https://cloud.google.com/sdk/docs/install). Konfiguracja jednorazowa, od zera:

```bash
# Zmienne: ID projektu GCP jest globalnie unikalne — wymyśl własne. E-mail = Twoje konto Google.
PROJECT=api-ingestion-lab-bq
ME=twoj-email@gmail.com
SA=ingest-runner@$PROJECT.iam.gserviceaccount.com

# 1. Zależności Pythona do .venv/ (wersje z uv.lock).
uv sync

# 2. Logowanie gcloud (komendy administracyjne niżej) i projekt domyślny.
gcloud auth login
gcloud projects create $PROJECT            # pomiń, jeśli projekt już istnieje; billing niepotrzebny (sandbox BigQuery)
gcloud config set project $PROJECT

# 3. API BigQuery — w nowym projekcie wszystkie API są wyłączone.
gcloud services enable bigquery.googleapis.com --project=$PROJECT

# 4. Konto usługi: osobna tożsamość dla skryptów, ta sama lokalnie i w harmonogramie (GitHub Actions + WIF).
gcloud iam service-accounts create ingest-runner --project=$PROJECT --display-name="Ingest runner (GA4, BigQuery)"

# 5. Najmniejsze potrzebne uprawnienia w BigQuery: tworzenie tabel i zapis (dataEditor), uruchamianie zadań (jobUser).
gcloud projects add-iam-policy-binding $PROJECT --member=serviceAccount:$SA --role=roles/bigquery.dataEditor --condition=None
gcloud projects add-iam-policy-binding $PROJECT --member=serviceAccount:$SA --role=roles/bigquery.jobUser --condition=None

# 6. Twoje konto może generować krótkotrwałe tokeny konta usługi — zamiast pliku z kluczem, który mógłby wyciec.
gcloud iam service-accounts add-iam-policy-binding $SA --project=$PROJECT --member=user:$ME --role=roles/iam.serviceAccountTokenCreator

# 7. ADC = poświadczenia, które biblioteki Google biorą automatycznie. Od teraz każdy skrypt działa jako konto usługi.
#    Zakresy: cloud-platform (BigQuery), analytics.readonly (etap 3, GA4), webmasters.readonly (etap 4, Search Console).
#    Nowy zakres = to samo logowanie jeszcze raz z pełną listą.
gcloud auth application-default login --impersonate-service-account=$SA \
  --scopes="https://www.googleapis.com/auth/cloud-platform,https://www.googleapis.com/auth/analytics.readonly,https://www.googleapis.com/auth/webmasters.readonly"

# 8. Kontrola: zwraca token = ADC działa.
gcloud auth application-default print-access-token > /dev/null && echo "ADC OK"
```

Datasety powstają same przy pierwszym uruchomieniu, w lokalizacji `EU` (`LOCATION` w [`common/bigquery.py`](common/bigquery.py)). Lokalizacji datasetu nie da się zmienić po utworzeniu — jeśli istnieje w innej, skrypt przerwie z błędem.

Dalej: sekcja „Konfiguracja” w README konkretnego folderu (kroki specyficzne dla źródła).
