# api-ingestion-lab

Pobieranie danych z API (głównie REST) w Pythonie i ładowanie ich do BigQuery. Projekt do nauki inżynierii danych: każde połączenie to osobny, niezależny pipeline w swoim folderze, z komentarzami po polsku, które tłumaczą mechanizm.

Kierunek: dane, z którymi pracuje analityk internetowy, połączone z danymi biznesowymi: ruch i wyszukiwanie (GA4, Search Console) → lead w CRM → zamówienie i faktura w ERP → przychód w PLN, z kontekstem dnia (kurs NBP, pogoda).

## Połączenia

Każdy folder ma własny README z konfiguracją krok po kroku. Ta tabela to indeks.

| Etap | System i folder | Dane i dostęp | Czego uczy&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; |
|:-:|---|---|---|
| 1<br>*działa* | [API NBP](https://api.nbp.pl/) — kursy walut, tabela A<br>[`nbp/`](nbp/README.md) | prawdziwe<br>(API otwarte) | • GET i JSON<br>• limit 93 dni → dzielenie zakresu na okna<br>• idempotentny zapis do BigQuery |
| 2<br>*działa* | [Open-Meteo](https://open-meteo.com/en/docs/historical-weather-api) — pogoda historyczna (archiwum)<br>[`weather/`](weather/README.md) | prawdziwe<br>(API otwarte, użytek niekomercyjny) | • GET bez klucza, wiele lokalizacji w jednym zapytaniu<br>• strefa czasowa i granice doby (`timezone`)<br>• dane korygowane wstecz: reanaliza ERA5 z opóźnieniem 5 dni → lookback<br>• limit 10 000 wywołań dziennie |
| 3<br>*planowany* | [GA4 Data API](https://developers.google.com/analytics/devguides/reporting/data/v1) — ruch na pmdata.pl<br>`ga4/` | prawdziwe<br>(własna usługa GA4) | • konto usługi / ADC z dostępem do usługi GA4<br>• paginacja `limit`/`offset` (maks. 250 000 wierszy na zapytanie)<br>• limity tokenów (`returnPropertyQuota`)<br>• dane dopisywane wstecz → lookback |
| 4<br>*planowany* | [Search Console API](https://developers.google.com/webmaster-tools/v1/searchanalytics/query) — wyniki wyszukiwania pmdata.pl<br>`search_console/` | prawdziwe<br>(własna usługa) | • paginacja `rowLimit`/`startRow` (maks. 25 000 wierszy)<br>• `dataState`: dane wstępne vs ostateczne<br>• opóźnienie danych o kilka dni |
| 5<br>*planowany* | [HubSpot CRM API](https://developers.hubspot.com/docs/api/crm/understanding-the-crm) — kontakty, firmy, deale<br>`hubspot/` | syntetyczne<br>(darmowe konto testowe) | • bearer token aplikacji prywatnej<br>• źródło leada (UTM) losowane według proporcji źródeł z GA4<br>• paginacja kursorem (`after`)<br>• przyrost po `lastmodifieddate` przez search API<br>• limit zapytań → 429 i ponowienia |
| 6<br>*planowany* | [Odoo](https://www.odoo.com/documentation/19.0/developer/reference/external_api.html) (ERP, Community) — zamówienia, faktury<br>`odoo/` | syntetyczne<br>(open source lokalnie) | • Docker: Odoo + PostgreSQL z danymi demo<br>• JSON-2 API z kluczem API<br>• przyrost po `write_date`, rekordy zmieniane i usuwane<br>• baza transakcyjna → CDC z PostgreSQL |
| 7<br>*planowany* | Model w dbt na BigQuery<br>`model/` | z etapów 1–6 | • warstwy staging → intermediate → marty<br>• lead-to-cash na agregatach `data × źródło`: sesje → kliknięcia w kontakt → leady → deale → faktury<br>• waluta (kurs NBP), pogoda jako wymiar dnia, strefa czasowa, testy dbt |

**Dane i dostęp** — co faktycznie trafi do BigQuery i skąd:

- *prawdziwe (API otwarte)* — produkcyjne dane źródła, dostępne dla każdego bez klucza. NBP to produkcyjne API, nie sandbox. Open-Meteo za darmo tylko do użytku niekomercyjnego. Alternatywa IMGW (`danepubliczne.imgw.pl/api/data/synop`) zwraca tylko ostatni pomiar, bez historii — nie nadaje się do backfillu.
- *prawdziwe (własna usługa)* — realny ruch z pmdata.pl. Strona to nie sklep, więc „konwersją” jest kontakt, nie zakup.
- *syntetyczne (darmowe konto testowe)* — prawdziwe API HubSpot na [koncie testowym dewelopera](https://developers.hubspot.com/docs/getting-started/account-types) (darmowe, wygasa po 90 dniach bez wywołań API). Dane wgrywa nasz skrypt.
- *syntetyczne (open source lokalnie)* — prawdziwe oprogramowanie uruchomione u siebie; dane demo Odoo plus dogenerowane rekordy. ERP to Odoo, bo SAP i popularne polskie systemy ERP nie mają darmowego środowiska z API; Odoo daje ten sam typ danych (zamówienia, faktury, rekordy zmieniane i usuwane) i bazę PostgreSQL do ćwiczenia CDC.

Jak łączą się źródła: GA4 Data API zwraca agregaty (dzień × źródło ruchu), nie pojedynczych użytkowników, a pmdata.pl nie ma formularza — są tylko kliknięcia w e-mail, telefon i LinkedIn. Dlatego złączenie jest na agregatach, po `data × źródło`: syntetyczne leady w HubSpot dostają źródło losowane według proporcji źródeł z GA4 (udział każdego źródła w kliknięciach w kontakt danego dnia), a ich dzienna liczba wynika z prawdziwych kliknięć w kontakt × założony współczynnik. Złączenie po identyfikatorze leada (backend generuje `lead_id`, wysyła go do CRM i do GA4) wymagałoby eksportu GA4 do BigQuery i jest poza zakresem.

## Automatyzacja: gdzie uruchamiać ingest

Skrypty z tego repo uruchamia się ręcznie. W pracy ten sam kod musi ruszać sam, według harmonogramu, z uprawnieniami do hurtowni i bez kluczy w repo. Tabela zestawia, gdzie go uruchomić, od wariantu darmowego po pełną orkiestrację. Konfiguracji tu nie wdrażamy.

| # | Rozwiązanie | Koszt | Konfiguracja w skrócie&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; | Uwierzytelnianie do hurtowni | Kiedy wybrać / ograniczenia |
|:-:|---|---|---|---|---|
| 1 | **GitHub Actions** (cron) → BigQuery | 0 zł: publiczne repo za darmo, prywatne w ramach limitu GitHub Free ($12 miesięcznie) | 1. Pula Workload Identity Federation (WIF) + dostawca OIDC GitHuba<br>2. Konto usługi z rolami BigQuery Data Editor i Job User<br>3. Workflow z `on: schedule`, krok `google-github-actions/auth@v3`, potem `uv run python nbp/ingest.py --project <projekt-gcp> --lookback-days 7`<br>4. Cron po publikacji NBP (11:45–12:15 czasu PL), np. `0 12 * * 1-5` w UTC | token OIDC GitHuba → WIF → krótkotrwały token Google; workflow potrzebuje `id-token: write`. Zero kluczy w sekretach | nauka, małe joby, zespół już na GitHubie. Cron co najmniej co 5 min, bywa opóźniony przy obciążeniu; w publicznym repo GitHub wyłącza go po 60 dniach bez aktywności. Działa w sandboxie BigQuery, ale tam tabela wygasa po 60 dniach, a cron z lookbackiem odbuduje tylko ostatni tydzień — pełną historię trzeba wtedy doładować ręcznie (`--start`) |
| 2 | **Cloud Run job + Cloud Scheduler** (GCP) | wymaga billingu. Job: płacisz za czas życia instancji (min. 1 min), 180 000 vCPU-s miesięcznie gratis; Scheduler: 3 joby gratis na konto rozliczeniowe | 1. `Dockerfile` → obraz w Artifact Registry<br>2. `gcloud run jobs deploy` z dedykowanym kontem usługi<br>3. Wyzwalacz Cloud Scheduler (cron) wołający endpoint `:run` | konto usługi przypięte do joba; biblioteka Google bierze poświadczenia z ADC w kontenerze, bez kluczy | standard GCP dla pojedynczego joba wsadowego. Timeout zadania do 168 h. Brak zależności między jobami — każdy harmonogram osobno |
| 3 | **AWS: ECS Fargate + EventBridge Scheduler** | wymaga konta AWS; płacisz za czas zadania | 1. Obraz w ECR<br>2. Task definition z rolą IAM<br>3. Harmonogram w EventBridge Scheduler (cel: `ECS RunTask`), ponowienia i kolejka DLQ | rola IAM zadania. Do BigQuery: WIF z dostawcą AWS (bez kluczy). Hurtownia po stronie AWS: Redshift | organizacja na AWS. Krótkie joby można odpalać jako Lambda, ale jej limit to 15 min |
| 4 | **Azure: Container Apps job** (typ `Schedule`) | wymaga subskrypcji Azure; płacisz za czas wykonania | 1. Obraz w Azure Container Registry<br>2. `az containerapp job create --trigger-type Schedule --cron-expression "..."` (cron w UTC)<br>3. Managed identity przypisana do joba | managed identity → token Microsoft Entra ID. Do BigQuery: WIF z dostawcą OIDC Entra ID | organizacja na Azure. Wbudowane ponowienia (`replica-retry-limit`) i timeout repliki |
| 5 | **Databricks: Lakeflow Jobs** | wymaga workspace'u Databricks | 1. Plik `.py` w repo albo workspace<br>2. Job z zadaniem typu Python script<br>3. Wyzwalacz czasowy (cron) albo zdarzeniowy (nowe pliki w storage) | `ingest.py` jako Python script task pisze do BigQuery biblioteką `google-cloud-bigquery`, z poświadczeniami Google przez WIF (dostawca AWS albo Entra ID). Eksperymentalny konektor Spark z kluczem JSON jest potrzebny tylko do zapisu DataFrame'ów Spark | organizacja z lakehouse'em na Databricks; tam hurtownią zwykle jest sam Databricks (tabele Delta w Unity Catalog), a BigQuery to wyjątek |
| 6 | **Airflow: Cloud Composer** (Managed Service for Apache Airflow, GCP) | wymaga billingu; płacisz za zasoby środowiska w trybie ciągłym, także bez uruchomień | 1. Środowisko Composer (Airflow 2 albo 3)<br>2. Plik DAG-a w buckecie środowiska<br>3. Zadania: `CloudRunExecuteJobOperator` odpala ingest z wiersza 2, potem dbt | konto usługi środowiska; ingest działa na koncie usługi Cloud Run joba | wiele zależnych kroków, ponowienia per zadanie, backfill zakresu dat, jeden widok stanu całego potoku. Dla jednego skryptu to przerost. Odpowiednik na AWS: Amazon MWAA |

### Scenariusz dla Airflow (wiersz 6)

Dzienny potok etapu 6: przychód w PLN przypisany do źródła ruchu. Jeden DAG, harmonogram codziennie rano:

1. **Równolegle ingesty** jako Cloud Run joby (`CloudRunExecuteJobOperator`): NBP, pogoda, GA4, Search Console, HubSpot i Odoo. Każdy z lookbackiem kilku dni (dla NBP: `--lookback-days 7`) i idempotentnym zapisem, więc ponowienie zadania jest bezpieczne.
2. **Ponowienia per źródło.** HubSpot przy przekroczeniu limitu zwraca 429 — ingest czeka i ponawia, a Airflow pilnuje timeoutu i liczby prób, nie blokując pozostałych źródeł.
3. **`dbt build`** dopiero gdy wszystkie ingesty się powiodą: modele łączą po `data × źródło` sesje i kliknięcia w kontakt z leadami, dealami i fakturami, przeliczają EUR na PLN kursem NBP dołączają pogodę jako wymiar dnia i wyrównują strefy czasowe.
4. **Testy dbt** jako bramka: np. faktura bez dealu albo deal bez kontaktu powyżej progu zatrzymuje potok przed publikacją.
5. **Alert przy porażce** dowolnego zadania. Zadania zależne dostają stan `upstream_failed` i nie ruszają, więc nic nie liczy się na niepełnych danych. Po naprawie czyścisz nieudane zadanie razem z zadaniami zależnymi (Clear → Downstream) i Airflow uruchamia je ponownie — samo się to nie wznowi.

Zależności i ponowienie nieudanego kroku da się zrobić też w GitHub Actions (`needs:`, „Re-run failed jobs”). Airflow wygrywa gdzie indziej: każdy przebieg ma swoją datę logiczną i stan per zadanie, a backfill zakresu dat to jedno polecenie (`airflow backfill create --dag-id ... --from-date ... --to-date ...` w Airflow 3, `airflow dags backfill` w Airflow 2).

Źródła (sprawdzone 2026-11-16): [NBP – terminy publikacji kursów](https://nbp.pl/statystyka-i-sprawozdawczosc/kursy/informacja-o-terminach-publikacji-kursow-walut/), [Airflow – backfill](https://airflow.apache.org/docs/apache-airflow/stable/core-concepts/backfill.html), [GitHub Actions – schedule](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows), [GitHub Actions – rozliczenia](https://docs.github.com/en/billing/concepts/product-billing/github-actions), [Cloud Run jobs](https://docs.cloud.google.com/run/docs/create-jobs), [Cloud Run – ceny](https://cloud.google.com/run/pricing), [Cloud Scheduler – ceny](https://cloud.google.com/scheduler/pricing), [WIF z AWS i Azure](https://docs.cloud.google.com/iam/docs/workload-identity-federation-with-other-clouds), [EventBridge Scheduler + ECS](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/tasks-scheduled-eventbridge-scheduler.html), [Lambda – timeout](https://docs.aws.amazon.com/lambda/latest/dg/configuration-timeout.html), [Container Apps jobs](https://learn.microsoft.com/en-us/azure/container-apps/jobs), [Lakeflow Jobs](https://docs.databricks.com/aws/en/jobs/), [Databricks → BigQuery](https://docs.databricks.com/aws/en/connect/external-systems/bigquery), [Composer – ceny](https://cloud.google.com/composer/pricing), [CloudRunExecuteJobOperator](https://airflow.apache.org/docs/apache-airflow-providers-google/stable/operators/cloud/cloud_run.html), [Amazon MWAA](https://docs.aws.amazon.com/mwaa/latest/userguide/what-is-mwaa.html).

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
#    Zakres analytics.readonly potrzebny od etapu 3 (GA4); cloud-platform obejmuje BigQuery.
gcloud auth application-default login --impersonate-service-account=$SA \
  --scopes="https://www.googleapis.com/auth/cloud-platform,https://www.googleapis.com/auth/analytics.readonly"

# 8. Kontrola: zwraca token = ADC działa.
gcloud auth application-default print-access-token > /dev/null && echo "ADC OK"
```

Dalej: sekcja „Konfiguracja” w README konkretnego folderu (kroki specyficzne dla źródła).
