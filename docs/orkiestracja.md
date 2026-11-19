# Orkiestracja w GitHub Actions — porównanie wariantów

Dotyczy [`.github/workflows/pipeline.yml`](../.github/workflows/pipeline.yml): jak ułożyć codzienny ingest kilku niezależnych źródeł (NBP, pogoda, GA4, Search Console), a potem transformację w dbt, która potrzebuje ich wszystkich. Gdzie w ogóle uruchamiać ingest (GitHub Actions, Cloud Run, Airflow…) — tabela „Automatyzacja” w [głównym README](../README.md#automatyzacja-gdzie-uruchamiać-ingest).

## Warianty

| Wariant | Jak wygląda | Awaria jednego źródła | Ponowienie jednego źródła | Krok po wszystkich (dbt) | Nowe źródło |
|---|---|---|---|---|---|
| **1. Macierz** (`strategy.matrix`) — wybrany | jeden job `ingest`, GitHub tworzy z niego kopię na każde źródło | pozostałe lecą dalej (przy `fail-fast: false`) | „Re-run failed jobs” powtarza tylko nieudane | `needs: ingest` czeka na całą macierz | jeden wpis w `matrix.include` |
| 2. Osobny job na źródło | cztery prawie identyczne joby w jednym pliku | pozostałe lecą dalej | jak wyżej | `needs: [nbp, weather, ga4, search_console]` | kopiowanie ~20 linii YAML |
| 3. Jeden job z krokami | jeden runner, ingesty po kolei jako kroki | kolejne kroki się nie wykonają (chyba że `continue-on-error`) | tylko cały job | kolejny krok w tym samym jobie | jeden krok |
| 4. Osobny workflow na źródło | cztery pliki, każdy z własnym cronem | niezależne | per workflow | trudne: `workflow_run` reaguje na **jeden** z wymienionych workflowów, nie czeka na wszystkie | nowy plik |
| 5. Airflow (Cloud Composer) | DAG: zadania ingestu → `dbt build` | stan `upstream_failed` w zależnych | „Clear” zadania i zależnych | natywnie (zależności w DAG-u) | nowe zadanie w DAG-u |

## Dlaczego macierz

- **Wszystkie ingesty mają ten sam interfejs** (`common/cli.py`: `--project`, `--lookback-days`, …), więc różnią się tylko nazwą modułu i dodatkowymi argumentami (`--property`, `--site`). To dokładnie przypadek, do którego jest macierz: ten sam przepis, inne parametry. Warianty 2 i 4 powielałyby kopie, które z czasem się rozjeżdżają.
- **Izolacja awarii bez dodatkowej logiki.** Timeout API NBP nie zatrzymuje GA4. Domyślnie `fail-fast` jest `true` i anulowałby pozostałe źródła, stąd jawne `false`. W wariancie 3 trzeba by to obchodzić `continue-on-error` na każdym kroku.
- **Ponowienie tylko tego, co padło.** Każde źródło to osobny job, więc `gh run rerun <id> --failed` powtarza jedno źródło; zapis z podmianą zakresu jest idempotentny, więc powtórka jest bezpieczna.
- **Bramka przed dbt.** Job `dbt` (etap 7) dostanie `needs: ingest`. Gdy którekolwiek źródło padnie, dbt zostaje pominięty — model nie liczy się na niepełnych danych. To świadomy wybór: lepiej brak świeżego raportu niż raport z dziurą po jednym źródle.
- **Dlaczego nie Airflow:** daje stan per zadanie, datę logiczną przebiegu i backfill jednym poleceniem, ale wymaga billingu i stale działającego środowiska. Przy czterech skryptach i jednym kroku dbt to przerost; `needs:` + „Re-run failed jobs” wystarczają. Kiedy Airflow się opłaca: wiersz 6 tabeli w [głównym README](../README.md#automatyzacja-gdzie-uruchamiać-ingest).

Koszt macierzy: każdy job osobno instaluje uv i zależności (z cache) i w prywatnym repo jest rozliczany osobno, zaokrąglany w górę do pełnej minuty. Cztery joby po kilkadziesiąt sekund = ok. 4 minuty dziennie zamiast 1–2 w wariancie 3. Przy tej skali bez znaczenia.

## Elementy workflowu i ich powód

| Element | Po co |
|---|---|
| `schedule` 1:41 z `timezone: Europe/Warsaw` | czas polski bez przeliczania na UTC (także po zmianie czasu); noc, bo w dzień runnery są obciążone i przebiegi z harmonogramu bywają opóźnione albo pomijane; minuta inna niż :00, bo szczyt przypada na początek godziny; nie 2:xx, bo przy zmianie czasu ta godzina raz w roku nie istnieje, a raz występuje dwukrotnie |
| `workflow_dispatch` | ręczny przebieg: test po zmianie, nadrobienie dnia |
| `permissions: id-token: write` | job może poprosić GitHuba o token OIDC — bez tego WIF nie zadziała |
| `concurrency` bez anulowania | dwa przebiegi naraz pisałyby do tych samych tabel; drugi czeka |
| `--lookback-days 7` | ostatnie dni pogody, GA4 i Search Console są wstępne; tydzień przerwy nie zostawia luki |
| `google-github-actions/auth` z kontem usługi | Python czyta poświadczenia przez `google.auth.default()` jak lokalnie; GA4 i Search Console widzą znajome konto `ingest-runner` |

Ograniczenia GitHub Actions do pamiętania: przebiegi z harmonogramu bywają opóźnione, a przy dużym obciążeniu część może przepaść; w publicznym repo harmonogram wyłącza się po 60 dniach bez aktywności. Etap 6 (Odoo) działa lokalnie w Dockerze, więc runner GitHuba się do niego nie dostanie — ten ingest zostanie poza macierzą albo pójdzie na self-hosted runner.

Źródła (sprawdzone 2026-11-18): [składnia: `strategy.fail-fast`, `on.schedule`](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax), [zdarzenia: `schedule`, `workflow_run`](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows), [`needs`](https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/use-jobs), [ponowienie nieudanych jobów](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/re-run-workflows-and-jobs), [czas rozliczany per job](https://docs.github.com/en/actions/how-tos/monitor-workflows/view-job-execution-time), [google-github-actions/auth](https://github.com/google-github-actions/auth).
