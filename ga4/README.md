# GA4 — ruch i kliknięcia w kontakt (Data API) → BigQuery

Pobiera z GA4 Data API dzienne sesje według źródła ruchu i kliknięcia w kontakt na pmdata.pl, i zapisuje je w BigQuery. W etapie 7 to strona „ruch” w łańcuchu sesje → kontakty → leady → deale → faktury.

## Przykładowe uruchomienia

Wspólny interfejs (`common/cli.py`) + `--property` — identyfikator usługi GA4.

```bash
# Backfill: cała historia od 2025 roku (dni sprzed utworzenia usługi po prostu nie mają wierszy).
uv run python -m ga4.ingest --project api-ingestion-lab-bq --property 539646739 --start 2025-01-01

# Codzienny przyrost: GA4 przetwarza dane do ok. 48 h, więc ostatnie dni zmieniają się wstecz.
uv run python -m ga4.ingest --project api-ingestion-lab-bq --property 539646739 --lookback-days 7
```

## Konfiguracja

Najpierw „Wspólne środowisko” z [głównego README](../README.md#wspólne-środowisko) — konto usługi `ingest-runner` i ADC z zakresem `analytics.readonly`. Potem kroki dla GA4:

```bash
PROJECT=api-ingestion-lab-bq
PROPERTY=539646739            # GA4: Administracja -> Szczegóły usługi -> IDENTYFIKATOR USŁUGI

# 1. Włącz GA4 Data API w projekcie GCP — bez tego każde zapytanie kończy się 403 "API not enabled".
gcloud services enable analyticsdata.googleapis.com --project=$PROJECT

# 2. W przeglądarce (nie da się z gcloud): GA4 -> Administracja -> Zarządzanie dostępem do usługi -> + -> Dodaj użytkowników
#    e-mail: ingest-runner@$PROJECT.iam.gserviceaccount.com, rola: Widz, bez powiadomienia e-mail.
#    Uprawnienia GCP i GA4 to osobne systemy — rola w projekcie GCP nie daje dostępu do danych GA4.

# 3. Backfill i kontrola duplikatów (obie liczby równe).
uv run python -m ga4.ingest --project $PROJECT --property $PROPERTY --start 2025-01-01
bq query --use_legacy_sql=false "SELECT COUNT(*), COUNT(DISTINCT FORMAT('%t|%s|%s', report_date, session_source, session_medium)) FROM \`$PROJECT.raw_ga4.traffic_daily\`"

# 4. Testy (bez sieci i bez GCP).
uv run pytest ga4
```

## Źródło

- Endpoint: `POST https://analyticsdata.googleapis.com/v1beta/properties/{id}:runReport`. [Dokumentacja](https://developers.google.com/analytics/devguides/reporting/data/v1/rest/v1beta/properties/runReport).
- Uwierzytelnianie: token OAuth z zakresem `analytics.readonly`, z ADC. Lokalnie podszywanie się pod konto usługi, w harmonogramie WIF — kod ten sam.

Zachowanie sprawdzone na żywo (2026-11-18):

| Co | Wynik | Co z tego wynika dla kodu |
|---|---|---|
| konto usługi bez dostępu w GA4 | 403 | dostęp w GA4 nadaje się osobno (krok 2 konfiguracji) |
| odpowiedź | `rows[].dimensionValues[]` i `metricValues[]` — listy wartości w kolejności z zapytania | `to_rows` przypisuje nazwy kolumn po kolejności |
| typy | data jako `20261101`, metryki jako tekst `"11"` | konwersja na `2026-11-01` i `int` |
| paginacja | `limit` (domyślnie 10 000, maks. 250 000) + `offset`; `rowCount` = wiersze całego raportu | pętla po offsetach do `rowCount` |
| limity | 1 token z 200 000 dziennie na zapytanie (`returnPropertyQuota`) | przy tej skali bez znaczenia; przy 429 ponowienia |
| strefa i waluta usługi | `Europe/Warsaw`, `PLN` | doba ta sama co w pogodzie |
| zdarzenia kontaktu (90 dni) | `phone_reveal` 9, `linkedin_click` 8, `email_click` 1, `email_reveal` 1 | lista `CONTACT_EVENTS` |
| sesje: suma wierszy dzień x źródło vs suma ogólna | 336 vs 335 | normalne: GA4 liczy sesje [przybliżeniem HyperLogLog++](https://support.google.com/analytics/answer/9191807), sumy wierszy nie muszą się zgadzać |

## Jak działa jedno uruchomienie

1. `make_session` — sesja HTTP z tokenem z ADC i ponowieniami (`urllib3.Retry`) dla 429 i 5xx, wspólna z Search Console ([`common/http.py`](../common/http.py)). Wbudowane w `requests`, więc bez własnej pętli jak w pogodzie.
2. `fetch_report` — `runReport` strona po stronie, aż `offset` dojdzie do `rowCount`. Test sprawdza to na atrapie z 5 wierszami po 2 na stronę, bo prawdziwy raport mieści się w jednej stronie.
3. `to_rows` — listy wartości → wiersze z nazwami kolumn, konwersja daty i liczb.
4. Zapis — `replace_date_range` z [`common/bigquery.py`](../common/bigquery.py), ta sama podmiana zakresu co w NBP i pogodzie.

Dwa raporty, dwie tabele, bo mają różne ziarno. Jeden raport z wymiarem `eventName` rozbiłby sesje na zdarzenia i zawyżył ich sumę.

## Alternatywy: Data Transfer Service i eksport GA4

Ten sam cel — dane GA4 w BigQuery — da się osiągnąć bez kodu. Stan dokumentacji na 2026-11-18:

| | Python + Data API (**ten folder**) | [BigQuery Data Transfer Service, konektor GA4](https://docs.cloud.google.com/bigquery/docs/google-analytics-4-transfer) | [Eksport GA4 do BigQuery](https://support.google.com/analytics/answer/9358801) |
|---|---|---|---|
| Co trafia | wybrane wymiary i metryki (agregaty) | te same agregaty z Data API: 10 gotowych raportów (m.in. TrafficAcquisition: `sessionSource`, `sessionMedium`, `sessions`, `keyEvents`) albo raport własny | surowe zdarzenia (wiersz = zdarzenie, z `user_pseudo_id`) |
| Kod | własny skrypt, testy, harmonogram | brak — konfiguracja w konsoli albo `bq mk --transfer_config` | brak — połączenie w Administracji GA4 |
| Harmonogram i okno | dowolne (`--lookback-days`) | raz dziennie, okno odświeżania domyślnie 4 dni, maks. 30; backfill na żądanie | eksport dzienny (zwykle po południu następnego dnia) albo strumieniowy |
| Koszt | 0 zł (sandbox) | transfer darmowy, płacisz za składowanie i zapytania | eksport dzienny darmowy (limit 1 mln zdarzeń/dzień w usłudze standardowej); strumieniowy płatny |
| Sandbox BigQuery | **działa** | **nie działa** — [sandbox nie obsługuje Data Transfer Service](https://docs.cloud.google.com/bigquery/docs/sandbox) | działa w limitach sandboxa |
| Kiedy | nauka mechaniki API; nietypowe raporty; łączenie z innymi źródłami w jednym potoku | produkcja z billingiem, gdy wystarczą agregaty — domyślny wybór: zero kodu do utrzymania | analizy na poziomie użytkownika i sesji: ścieżki, kohorty, złączenie po identyfikatorze |

Dlaczego tu Python, a nie transfer:
1. Sandbox nie obsługuje Data Transfer Service — w tym projekcie nie ma wyboru.
2. Cel repo to nauka ingestu z API: autoryzacja, paginacja, limity, idempotentny zapis. Transfer ukrywa dokładnie to.
3. Wynik byłby porównywalny: raport TrafficAcquisition to te same sesje według źródła i medium, a kliknięcia w kontakt dałby raport własny z wymiarem `eventName`.

W pracy z billingiem odwróciłbym ten wybór: dla standardowych agregatów GA4 transfer jest prostszy i tańszy w utrzymaniu niż własny kod. Własny ingest broni się, gdy potrzebujesz logiki, której transfer nie ma (np. filtr zdarzeń, wspólny harmonogram z innymi źródłami, testy przed zapisem).

## Tabele docelowe

`<projekt>.raw_ga4.traffic_daily`, klucz: `(report_date, session_source, session_medium)`.

| Kolumna | Typ | Znaczenie |
|---|---|---|
| `report_date` | DATE | dzień w strefie usługi (`Europe/Warsaw`) |
| `session_source`, `session_medium` | STRING | źródło i medium sesji, np. `google` / `organic` |
| `sessions` | INT64 | sesje |
| `total_users` | INT64 | użytkownicy — **nie sumuj** między dniami ani źródłami (ten sam użytkownik w kilku wierszach) |
| `engaged_sessions` | INT64 | sesje z zaangażowaniem |
| `property_id`, `loaded_at` | STRING, TIMESTAMP | skąd i kiedy |

`<projekt>.raw_ga4.contact_events_daily`, klucz: `(report_date, session_source, session_medium, event_name)` — te same wymiary plus `event_name` i `event_count`. Wszystkie kolumny REQUIRED.

## Strategia ładowania

Przepisanie z podmianą zakresu, jak w pozostałych źródłach ([uzasadnienie](../README.md#strategie-ładowania)). Lookback ma tu ten sam powód co w pogodzie: GA4 przetwarza dane do ok. 48 h, więc wartości z ostatnich dni rosną.

Ograniczenie: pusty raport (np. tydzień bez kliknięć w kontakt) nie jest ładowany, więc stare wiersze z tego zakresu zostają. Przy GA4 to rzadkie — zebrane dane nie znikają.
