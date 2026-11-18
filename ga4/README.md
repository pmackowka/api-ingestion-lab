# GA4 — ruch i kliknięcia w kontakt (Data API) → BigQuery

Dzienne sesje według źródła ruchu i kliknięcia w kontakt na pmdata.pl. W etapie 7 to „ruch” w łańcuchu sesje → kontakty → leady → deale → faktury.

## Konfiguracja

Najpierw [„Wspólne środowisko”](../docs/konfiguracja.md#wspólne-środowisko) — ADC z zakresem `analytics.readonly`.

```bash
PROJECT=api-ingestion-lab-bq
PROPERTY=<id-usługi>          # GA4: Administracja -> Szczegóły usługi -> IDENTYFIKATOR USŁUGI

# 1. GA4 Data API w projekcie GCP — bez tego 403 "API not enabled".
gcloud services enable analyticsdata.googleapis.com --project=$PROJECT

# 2. W przeglądarce: GA4 -> Administracja -> Zarządzanie dostępem do usługi -> Dodaj użytkowników
#    ingest-runner@$PROJECT.iam.gserviceaccount.com, rola: Widz. Rola w GCP nie daje dostępu do GA4.

# 3. Backfill i kontrola duplikatów (obie liczby równe).
uv run python -m ga4.ingest --project $PROJECT --property $PROPERTY --start 2025-01-01
bq query --use_legacy_sql=false "SELECT COUNT(*), COUNT(DISTINCT FORMAT('%t|%s|%s', report_date, session_source, session_medium)) FROM \`$PROJECT.raw_ga4.traffic_daily\`"

# 4. Codzienny przyrost: GA4 przetwarza dane do ok. 48 h, więc ostatnie dni rosną.
uv run python -m ga4.ingest --project $PROJECT --property $PROPERTY --lookback-days 7

# 5. Testy (bez sieci i bez GCP).
uv run pytest ga4
```

## Źródło

`POST https://analyticsdata.googleapis.com/v1beta/properties/{id}:runReport` ([dokumentacja](https://developers.google.com/analytics/devguides/reporting/data/v1/rest/v1beta/properties/runReport)), REST przez `AuthorizedSession` z [`common/http.py`](../common/http.py) (ponowienia 429/5xx). Sprawdzone na żywo (2026-11-18):

| Zachowanie | Co robi kod |
|---|---|
| `rows[].dimensionValues[]` i `metricValues[]` w kolejności z zapytania | `to_rows` nadaje nazwy po kolejności |
| data `20261101`, metryki jako tekst | konwersja na `2026-11-01` i `int` |
| `limit` (maks. 250 000) + `offset`; `rowCount` = wiersze całego raportu | pętla po offsetach do `rowCount` |
| strefa usługi `Europe/Warsaw` | doba ta sama co w pogodzie |
| suma sesji z wierszy ≠ suma ogólna | normalne: [HyperLogLog++](https://support.google.com/analytics/answer/9191807) |

Dwa raporty, dwie tabele, bo mają różne ziarno: wymiar `eventName` w raporcie ruchu rozbiłby sesje na zdarzenia i zawyżył sumę.

## Alternatywy: Data Transfer Service i eksport GA4

| | Python + Data API (**ten folder**) | [Data Transfer Service, konektor GA4](https://docs.cloud.google.com/bigquery/docs/google-analytics-4-transfer) | [Eksport GA4](https://support.google.com/analytics/answer/9358801) |
|---|---|---|---|
| Co trafia | wybrane agregaty | agregaty z Data API: gotowe raporty albo własny | surowe zdarzenia z `user_pseudo_id` |
| Kod i harmonogram | własny, dowolne okno | brak; raz dziennie, odświeżanie do 30 dni | brak; dziennie albo strumieniowo |
| Sandbox BigQuery | **działa** | **[nie działa](https://docs.cloud.google.com/bigquery/docs/sandbox)** | działa |
| Kiedy | nauka API, nietypowe raporty, wspólny potok | produkcja z billingiem, standardowe agregaty | analizy na poziomie użytkownika i sesji |

Tu Python, bo sandbox nie obsługuje transferu, a cel repo to mechanika API. Z billingiem dla standardowych agregatów wybrałbym transfer — mniej kodu do utrzymania.

## Tabele docelowe

`raw_ga4.traffic_daily`, klucz `(report_date, session_source, session_medium)`: `sessions`, `total_users` (**nie sumuj** między dniami i źródłami), `engaged_sessions`. `raw_ga4.contact_events_daily`: te same wymiary + `event_name`, `event_count` dla zdarzeń z `CONTACT_EVENTS`. Obie mają `property_id` i `loaded_at`, wszystkie kolumny REQUIRED.

Zapis: [podmiana zakresu](../README.md#strategie-ładowania). Pusty raport (tydzień bez kontaktów) nie jest ładowany, więc stare wiersze z zakresu zostają — przy GA4 rzadkie.
