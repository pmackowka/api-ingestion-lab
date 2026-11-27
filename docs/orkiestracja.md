# Orkiestracja w GitHub Actions — porównanie wariantów

Dotyczy [`.github/workflows/pipeline.yml`](../.github/workflows/pipeline.yml): jak ułożyć codzienny ingest kilku niezależnych źródeł (NBP, pogoda, GA4, Search Console, HubSpot, święta, sitemapa), a potem transformację w dbt, która potrzebuje ich wszystkich. Gdzie w ogóle uruchamiać ingest (GitHub Actions, Cloud Run, Airflow…) — [ostatnia sekcja](#gdzie-uruchamiać-ingest).

## Warianty

| Wariant | Jak wygląda | Awaria jednego źródła | Ponowienie jednego źródła | Krok po wszystkich (dbt) | Nowe źródło |
|---|---|---|---|---|---|
| **1. Macierz** (`strategy.matrix`) — wybrany | jeden job `ingest`, GitHub tworzy z niego kopię na każde źródło | pozostałe lecą dalej (przy `fail-fast: false`) | „Re-run failed jobs” powtarza tylko nieudane | `needs: ingest` czeka na całą macierz | jeden wpis w `matrix.include` |
| 2. Osobny job na źródło | siedem prawie identycznych jobów w jednym pliku | pozostałe lecą dalej | jak wyżej | `needs: [nbp, weather, ga4, search_console, hubspot, holidays, sitemap]` | kopiowanie ~20 linii YAML |
| 3. Jeden job z krokami | jeden runner, ingesty po kolei jako kroki | kolejne kroki się nie wykonają (chyba że `continue-on-error`) | tylko cały job | kolejny krok w tym samym jobie | jeden krok |
| 4. Osobny workflow na źródło | siedem plików, każdy z własnym cronem | niezależne | per workflow | trudne: `workflow_run` reaguje na **jeden** z wymienionych workflowów, nie czeka na wszystkie | nowy plik |
| 5. Airflow (Cloud Composer) | DAG: zadania ingestu → `dbt build` | stan `upstream_failed` w zależnych | „Clear” zadania i zależnych | natywnie (zależności w DAG-u) | nowe zadanie w DAG-u |

## Dlaczego macierz

- **Wszystkie ingesty mają ten sam interfejs** (`common/cli.py`: `--project`, `--lookback-days`, …), więc różnią się tylko nazwą modułu i dodatkowymi argumentami (`--property`, `--site`). To dokładnie przypadek, do którego jest macierz: ten sam przepis, inne parametry. Warianty 2 i 4 powielałyby kopie, które z czasem się rozjeżdżają.
- **Izolacja awarii bez dodatkowej logiki.** Timeout API NBP nie zatrzymuje GA4. Domyślnie `fail-fast` jest `true` i anulowałby pozostałe źródła, stąd jawne `false`. W wariancie 3 trzeba by to obchodzić `continue-on-error` na każdym kroku.
- **Ponowienie tylko tego, co padło.** Każde źródło to osobny job, więc `gh run rerun <id> --failed` powtarza jedno źródło; zapis z podmianą zakresu jest idempotentny, więc powtórka jest bezpieczna.
- **Bramka przed dbt.** Job `dbt` ma `needs: ingest`. Gdy którekolwiek źródło padnie, dbt zostaje pominięty — model nie liczy się na niepełnych danych. To świadomy wybór: lepiej brak świeżego raportu niż raport z dziurą po jednym źródle.
- **Dlaczego nie Airflow:** daje stan per zadanie, datę logiczną przebiegu i backfill jednym poleceniem, ale wymaga billingu i stale działającego środowiska. Przy siedmiu skryptach i jednym kroku dbt to przerost; `needs:` + „Re-run failed jobs” wystarczają. Kiedy Airflow się opłaca: wiersz 6 tabeli w sekcji [„Gdzie uruchamiać ingest”](#gdzie-uruchamiać-ingest).

Koszt macierzy: każdy job osobno instaluje uv i zależności (z cache) i w prywatnym repo jest rozliczany osobno, zaokrąglany w górę do pełnej minuty. Siedem jobów po kilkadziesiąt sekund = ok. 7 minut dziennie zamiast 1–2 w wariancie 3. Przy tej skali bez znaczenia.

## Elementy workflowu i ich powód

| Element | Po co |
|---|---|
| `schedule` 1:41 z `timezone: Europe/Warsaw` | czas polski bez przeliczania na UTC (także po zmianie czasu); noc, bo w dzień runnery są obciążone i przebiegi z harmonogramu bywają opóźnione albo pomijane; minuta inna niż :00, bo szczyt przypada na początek godziny; nie 2:xx, bo przy zmianie czasu ta godzina raz w roku nie istnieje, a raz występuje dwukrotnie |
| `workflow_dispatch` | ręczny przebieg: test po zmianie, nadrobienie dnia |
| `permissions: id-token: write` | job może poprosić GitHuba o token OIDC — bez tego WIF nie zadziała |
| `concurrency` bez anulowania | dwa przebiegi naraz pisałyby do tych samych tabel; drugi czeka |
| `--lookback-days 7` | ostatnie dni pogody, GA4 i Search Console są wstępne; tydzień przerwy nie zostawia luki |
| job `generate-leads`: `needs: ingest` + `if: ${{ !cancelled() }}` | generator HubSpot (leady i deale z kliknięć GA4) po ingeście, także gdy padło inne źródło — potrzebuje tylko GA4, a upsert jest idempotentny. Ingest HubSpota w macierzy już się wtedy skończył, więc nowe leady i deale trafią do `raw_hubspot` w następnym przebiegu |
| `dbt source freshness` z `if: ${{ !cancelled() }}` | świeżość źródeł sprawdzana także wtedy, gdy `dbt build` padł — stare dane to częsta przyczyna padających testów |
| `google-github-actions/auth` z kontem usługi | Python czyta poświadczenia przez `google.auth.default()` jak lokalnie; GA4 i Search Console widzą znajome konto `ingest-runner` |

Ograniczenia GitHub Actions do pamiętania: przebiegi z harmonogramu bywają opóźnione, a przy dużym obciążeniu część może przepaść; w publicznym repo harmonogram wyłącza się po 60 dniach bez aktywności. Etap 6 (Odoo) działa lokalnie w Dockerze, więc runner GitHuba się do niego nie dostanie — ingest i generator faktur Odoo są poza workflowem i uruchamiane lokalnie; alternatywa to self-hosted runner.

Źródła (sprawdzone 2026-11-18): [składnia: `strategy.fail-fast`, `on.schedule`](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax), [zdarzenia: `schedule`, `workflow_run`](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows), [`needs`](https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/use-jobs), [ponowienie nieudanych jobów](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/re-run-workflows-and-jobs), [czas rozliczany per job](https://docs.github.com/en/actions/how-tos/monitor-workflows/view-job-execution-time), [google-github-actions/auth](https://github.com/google-github-actions/auth).

## Gdzie uruchamiać ingest

Wdrożony jest wiersz 1: [`.github/workflows/pipeline.yml`](../.github/workflows/pipeline.yml), konfiguracja w [`konfiguracja.md`](konfiguracja.md#github-actions); pozostałe są do porównania.

| # | Rozwiązanie | Koszt | Uwierzytelnianie do BigQuery | Kiedy wybrać / ograniczenia |
|:-:|---|---|---|---|
| 1 | **GitHub Actions** (cron) | 0 zł: publiczne repo za darmo, prywatne w limicie GitHub Free | token OIDC → WIF → krótkotrwały token konta usługi, zero kluczy | małe joby, zespół na GitHubie. Cron bywa opóźniony; w publicznym repo wyłącza się po 60 dniach bez aktywności |
| 2 | **Cloud Run job + Cloud Scheduler** | billing; 180 000 vCPU-s miesięcznie i 3 harmonogramy gratis | konto usługi przypięte do joba | standard GCP dla joba wsadowego; brak zależności między jobami |
| 3 | **AWS: ECS Fargate + EventBridge Scheduler** | konto AWS, płacisz za czas zadania | rola IAM → WIF z dostawcą AWS | organizacja na AWS; Lambda tylko do 15 min |
| 4 | **Azure: Container Apps job** | subskrypcja Azure, płacisz za czas | managed identity → WIF z Entra ID | organizacja na Azure; wbudowane ponowienia |
| 5 | **Databricks: Lakeflow Jobs** | workspace Databricks | WIF (dostawca AWS albo Entra ID) | lakehouse na Databricks — tam hurtownią zwykle jest sam Databricks |
| 6 | **Airflow: Cloud Composer** | billing, środowisko płatne także bez uruchomień | konto usługi środowiska | wiele zależnych kroków, backfill zakresu dat, stan całego potoku. Dla kilku skryptów przerost |
