# Search Console — wyniki wyszukiwania Google → BigQuery

Dzienne kliknięcia, wyświetlenia i pozycje pmdata.pl w Google. W etapie 7 to drugie spojrzenie na ruch `google / organic`: Search Console widzi wyszukiwanie przed kliknięciem, GA4 — wizytę po nim.

Diagram sekwencji UML jednego uruchomienia: [`uml-diagram.md`](uml-diagram.md).

## Konfiguracja

Najpierw [„Wspólne środowisko”](../docs/konfiguracja.md#wspólne-środowisko) — ADC z zakresem `webmasters.readonly`.

```bash
PROJECT=api-ingestion-lab-bq
SITE=sc-domain:pmdata.pl      # usługa domenowa: sc-domain:<domena>; z prefiksem URL: https://<domena>/

# 1. Search Console API w projekcie GCP.
gcloud services enable searchconsole.googleapis.com --project=$PROJECT

# 2. W przeglądarce: Search Console -> Ustawienia -> Użytkownicy i uprawnienia -> Dodaj użytkownika
#    ingest-runner@$PROJECT.iam.gserviceaccount.com, uprawnienia: Ograniczone.

# 3. Backfill (Search Console trzyma 16 miesięcy — starsze dni nie wrócą) i kontrola duplikatów.
uv run python -m search_console.ingest --project $PROJECT --site $SITE --start 2025-01-01
bq query --use_legacy_sql=false "SELECT COUNT(*), COUNT(DISTINCT FORMAT('%t|%s|%s', report_date, country, device)) FROM \`$PROJECT.raw_search_console.search_daily\`"

# 4. Codzienny przyrost: ostatnie dni są wstępne i zmieniają się wstecz.
uv run python -m search_console.ingest --project $PROJECT --site $SITE --lookback-days 7

# 5. Testy (bez sieci i bez GCP).
uv run pytest search_console
```

## Źródło

`POST https://www.googleapis.com/webmasters/v3/sites/{siteUrl}/searchAnalytics/query` ([dokumentacja](https://developers.google.com/webmaster-tools/v1/searchanalytics/query)). Sprawdzone na żywo (2026-11-18):

| Zachowanie | Co robi kod |
|---|---|
| `siteUrl` w ścieżce URL | kodowanie: `sc-domain%3Apmdata.pl` |
| bez wymiaru `page` → sumy usługi (`byProperty`); z `page` → wyświetlenie liczone osobno dla każdej podstrony (`byPage`), suma wyraźnie większa | dwie tabele; tabeli stron nie sumuj jako usługi ([docs](https://developers.google.com/webmaster-tools/v1/how-tos/all-your-data)) |
| wymiar `query`: rzadkie zapytania anonimizowane, widać tylko ułamek wyświetleń | zapytań nie ładujemy |
| `dataState=final` kończy się ok. 2 dni wcześniej niż `all` | `all` + lookback |
| `rowLimit` (maks. 25 000) + `startRow`, bez `rowCount` | koniec = strona krótsza niż limit |
| liczniki jako float (`1.0`) | rzutowanie na `int` |

## Tabele docelowe

`raw_search_console.search_daily`, klucz `(report_date, country, device)` — sumy usługi. `raw_search_console.search_pages_daily`, klucz `(report_date, page)` — per podstrona.

| Kolumna | Typ | Znaczenie |
|---|---|---|
| `report_date` | DATE | dzień w czasie **pacyficznym** ([pomoc Google](https://support.google.com/webmasters/answer/17011259)) |
| `country`, `device` / `page` | STRING | kraj ISO alfa-3 (`pol`), `MOBILE`/`DESKTOP`/`TABLET`, adres podstrony |
| `clicks`, `impressions` | INT64 | kliknięcia i wyświetlenia; CTR licz w SQL |
| `position` | FLOAT64 | średnia pozycja; agreguj ważoną: `SUM(position * impressions) / SUM(impressions)` |
| `site`, `loaded_at` | STRING, TIMESTAMP | skąd i kiedy |

Etap 7: doba PT jest przesunięta o 9 h względem `Europe/Warsaw` (GA4, pogoda) — przy dziennych agregatach akceptowalne, ale porównując dzień do dnia, pamiętaj o tym. Zapis: [podmiana zakresu](../README.md#strategie-ładowania).
