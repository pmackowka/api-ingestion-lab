# api-ingestion-lab

Pobieranie danych z API (głównie REST) w Pythonie i ładowanie ich do BigQuery. Projekt do nauki inżynierii danych: każde połączenie to osobny, niezależny pipeline w swoim folderze, z komentarzami po polsku, które tłumaczą mechanizm.

Kierunek: dane, z którymi pracuje analityk internetowy — ekosystem Google, marketing, reklama. Obecne etapy to pierwsza propozycja; kolejne źródła wybierzemy na podstawie ogłoszeń o pracę dla inżynierów danych w Polsce (z dbt w wymaganiach) i typów danych, które w nich się powtarzają.

## Połączenia

Każdy folder ma własny README z konfiguracją krok po kroku. Ta tabela to indeks.

| Etap | System | Folder | Status | Dane i dostęp | Czego uczy&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; |
|:-:|---|---|---|---|---|
| 1 | [API NBP](https://api.nbp.pl/) — kursy walut, tabela A | [`nbp/`](nbp/README.md) | działa | prawdziwe<br>(API otwarte) | • GET i JSON<br>• limit 93 dni → dzielenie zakresu na okna<br>• idempotentny zapis do BigQuery |
| 2 | Atrapa API raportowego SSP (własna, FastAPI) | `ssp_mock/` | planowany | syntetyczne<br>(brak sandboxa) | • uwierzytelnianie tokenem<br>• raport asynchroniczny: zlecenie → status → pobranie<br>• paginacja, 429 i ponowienia<br>• dane w UTC i EUR |
| 3 | [Google Ad Manager API](https://developers.google.com/ad-manager/api/beta/reports) (REST, beta) | `gam/` | planowany | puste<br>(sandbox: sieć testowa) | • OAuth / konto usługi<br>• raporty GAM |
| 4 | [Prebid Server](https://docs.prebid.org/prebid-server/overview/prebid-server-overview.html) + atrapa biddera | `prebid/` | planowany | syntetyczne<br>(open source lokalnie) | • OpenRTB: bid request / bid response<br>• logi aukcji jako źródło danych |
| 5 | [AppsFlyer Pull API](https://dev.appsflyer.com/hc/reference/raw_data_pull_api_tokenv2-overview) (raw data) | `appsflyer/` | planowany | syntetyczne<br>(brak sandboxa) | • bearer token<br>• odpowiedź w CSV<br>• strefa czasowa aplikacji<br>• limit 1 mln wierszy na wywołanie |
| 6 | Model w BigQuery | `model/` | planowany | z etapów 1–5 | • uzgadnianie GAM vs SSP<br>• strefa czasowa, waluta (kurs NBP)<br>• brutto vs netto |

**Dane i dostęp** — co faktycznie trafi do BigQuery i skąd:

- *prawdziwe (API otwarte)* — produkcyjne dane źródła, dostępne dla każdego bez klucza. NBP to produkcyjne API, nie sandbox.
- *puste (sandbox: sieć testowa)* — prawdziwe API, ale darmowa [sieć testowa GAM](https://developers.google.com/ad-manager/api/beta/test-networks) nie serwuje reklam, więc raporty z danymi serwowania mają 0 wierszy.
- *syntetyczne (open source lokalnie)* — prawdziwe oprogramowanie uruchomione u siebie, ruch generuje atrapa.
- *syntetyczne (brak sandboxa)* — API raportowe SSP (Magnite, PubMatic, Index Exchange) i AppsFlyer są dostępne tylko dla klientów platformy. Kod powstaje z oficjalnej dokumentacji, a testuje go lokalna atrapa, która odtwarza udokumentowany kontrakt: endpointy, uwierzytelnianie, format odpowiedzi i kody błędów.

## Automatyzacja: gdzie uruchamiać ingest

Skrypty z tego repo uruchamia się ręcznie. W pracy ten sam kod musi ruszać sam, według harmonogramu, z uprawnieniami do hurtowni i bez kluczy w repo. Tabela zestawia, gdzie go uruchomić, od wariantu darmowego po pełną orkiestrację. Konfiguracji tu nie wdrażamy.

| # | Rozwiązanie | Koszt | Konfiguracja w skrócie&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; | Uwierzytelnianie do hurtowni | Kiedy wybrać / ograniczenia |
|:-:|---|---|---|---|---|
| 1 | **GitHub Actions** (cron) → BigQuery | 0 zł: publiczne repo za darmo, prywatne w ramach limitu GitHub Free ($12 miesięcznie) | 1. Pula Workload Identity Federation (WIF) + dostawca OIDC GitHuba<br>2. Konto usługi z rolami BigQuery Data Editor i Job User<br>3. Workflow z `on: schedule`, krok `google-github-actions/auth@v3`, potem `uv run python nbp/ingest.py` | token OIDC GitHuba → WIF → krótkotrwały token Google; workflow potrzebuje `id-token: write`. Zero kluczy w sekretach | nauka, małe joby, zespół już na GitHubie. Cron co najmniej co 5 min, bywa opóźniony przy obciążeniu; w publicznym repo GitHub wyłącza go po 60 dniach bez aktywności. Działa w sandboxie BigQuery |
| 2 | **Cloud Run job + Cloud Scheduler** (GCP) | wymaga billingu. Job: płacisz za czas życia instancji (min. 1 min), 180 000 vCPU-s miesięcznie gratis; Scheduler: 3 joby gratis na konto rozliczeniowe | 1. `Dockerfile` → obraz w Artifact Registry<br>2. `gcloud run jobs deploy` z dedykowanym kontem usługi<br>3. Wyzwalacz Cloud Scheduler (cron) wołający endpoint `:run` | konto usługi przypięte do joba; biblioteka Google bierze poświadczenia z ADC w kontenerze, bez kluczy | standard GCP dla pojedynczego joba wsadowego. Timeout zadania do 168 h. Brak zależności między jobami — każdy harmonogram osobno |
| 3 | **AWS: ECS Fargate + EventBridge Scheduler** | wymaga konta AWS; płacisz za czas zadania | 1. Obraz w ECR<br>2. Task definition z rolą IAM<br>3. Harmonogram w EventBridge Scheduler (cel: `ECS RunTask`), ponowienia i kolejka DLQ | rola IAM zadania. Do BigQuery: WIF z dostawcą AWS (bez kluczy). Hurtownia po stronie AWS: Redshift | organizacja na AWS. Krótkie joby można odpalać jako Lambda, ale jej limit to 15 min |
| 4 | **Azure: Container Apps job** (typ `Schedule`) | wymaga subskrypcji Azure; płacisz za czas wykonania | 1. Obraz w Azure Container Registry<br>2. `az containerapp job create --trigger-type Schedule --cron-expression "..."` (cron w UTC)<br>3. Managed identity przypisana do joba | managed identity → token Microsoft Entra ID. Do BigQuery: WIF z dostawcą OIDC Entra ID | organizacja na Azure. Wbudowane ponowienia (`replica-retry-limit`) i timeout repliki |
| 5 | **Databricks: Lakeflow Jobs** | wymaga workspace'u Databricks | 1. Plik `.py` w repo albo workspace<br>2. Job z zadaniem typu Python script<br>3. Wyzwalacz czasowy (cron) albo zdarzeniowy (nowe pliki w storage) | dane lądują w tabelach Delta (Unity Catalog). Zapis do BigQuery tylko przez eksperymentalny konektor z kluczem JSON i bucketem GCS — nie polecam | organizacja z lakehouse'em na Databricks; tam hurtownią jest sam Databricks, nie BigQuery |
| 6 | **Airflow: Cloud Composer** (Managed Service for Apache Airflow, GCP) | wymaga billingu; płacisz za zasoby środowiska w trybie ciągłym, także bez uruchomień | 1. Środowisko Composer (Airflow 2 albo 3)<br>2. Plik DAG-a w buckecie środowiska<br>3. Zadania: `CloudRunExecuteJobOperator` odpala ingest z wiersza 2, potem dbt | konto usługi środowiska; ingest działa na koncie usługi Cloud Run joba | wiele zależnych kroków, ponowienia per zadanie, backfill zakresu dat, jeden widok stanu całego potoku. Dla jednego skryptu to przerost. Odpowiednik na AWS: Amazon MWAA |

### Scenariusz dla Airflow (wiersz 6)

Dzienny potok etapu 6: przychody reklamowe w PLN, uzgodnione między źródłami. Jeden DAG, harmonogram codziennie rano:

1. **Równolegle trzy ingesty** jako Cloud Run joby (`CloudRunExecuteJobOperator`): kursy NBP, raport SSP i raport GAM. Każdy z lookbackiem kilku dni i idempotentnym zapisem, więc ponowienie zadania jest bezpieczne.
2. **Czekanie na raport SSP.** API raportowe działa asynchronicznie (zlecenie → status → pobranie), więc ingest SSP sam odpytuje status, a Airflow pilnuje timeoutu i ponowień.
3. **`dbt build`** dopiero gdy wszystkie trzy ingesty się powiodą: modele przeliczają EUR na PLN kursem NBP, wyrównują strefy czasowe i porównują GAM z SSP.
4. **Testy dbt** jako bramka: rozjazd przychodów powyżej progu zatrzymuje potok przed publikacją.
5. **Alert przy porażce** dowolnego zadania; reszta potoku czeka, a nie liczy się na niepełnych danych.

Czego nie da się zrobić samym cronem z wierszy 1–4: zależności między zadaniami (dbt czeka na trzy ingesty), ponowienia tylko nieudanego kroku i backfill zakresu dat jednym poleceniem (`airflow dags backfill`).

Źródła: [GitHub Actions – schedule](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows), [GitHub Actions – rozliczenia](https://docs.github.com/en/billing/concepts/product-billing/github-actions), [Cloud Run jobs](https://docs.cloud.google.com/run/docs/create-jobs), [Cloud Run – ceny](https://cloud.google.com/run/pricing), [Cloud Scheduler – ceny](https://cloud.google.com/scheduler/pricing), [WIF z AWS i Azure](https://docs.cloud.google.com/iam/docs/workload-identity-federation-with-other-clouds), [EventBridge Scheduler + ECS](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/tasks-scheduled-eventbridge-scheduler.html), [Lambda – timeout](https://docs.aws.amazon.com/lambda/latest/dg/configuration-timeout.html), [Container Apps jobs](https://learn.microsoft.com/en-us/azure/container-apps/jobs), [Lakeflow Jobs](https://docs.databricks.com/aws/en/jobs/), [Databricks → BigQuery](https://docs.databricks.com/aws/en/connect/external-systems/bigquery), [Composer – ceny](https://cloud.google.com/composer/pricing), [CloudRunExecuteJobOperator](https://airflow.apache.org/docs/apache-airflow-providers-google/stable/operators/cloud/cloud_run.html), [Amazon MWAA](https://docs.aws.amazon.com/mwaa/latest/userguide/what-is-mwaa.html).

## Wspólne środowisko

Foldery są niezależne od siebie, ale dzielą jedno środowisko Pythona (`pyproject.toml` w katalogu głównym).

1. `uv sync` — instaluje zależności do `.venv/`.
2. `gcloud auth application-default login` — poświadczenia dla bibliotek Google (ADC).
3. `gcloud auth application-default set-quota-project <projekt-gcp>` — projekt, który biblioteki podają jako rozliczeniowy. Musi istnieć, inaczej każde wywołanie BigQuery kończy się błędem 400.
4. Dalej według README konkretnego folderu.
