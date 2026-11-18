# Search Console — wyniki wyszukiwania Google → BigQuery

Pobiera z Search Console API dzienne kliknięcia, wyświetlenia i pozycje pmdata.pl w wyszukiwarce Google. W etapie 7 to drugie spojrzenie na ruch `google / organic` z GA4: Search Console widzi wyszukiwanie przed kliknięciem, GA4 — wizytę po nim.

## Przykładowe uruchomienia

Wspólny interfejs (`common/cli.py`) + `--site` — usługa Search Console.

```bash
# Backfill: cała dostępna historia (Search Console przechowuje 16 miesięcy — starsze dni nie wrócą, warto je mieć w BigQuery).
uv run python -m search_console.ingest --project api-ingestion-lab-bq --site sc-domain:pmdata.pl --start 2025-01-01

# Codzienny przyrost: ostatnie dni są wstępne (dataState=all) i zmieniają się wstecz.
uv run python -m search_console.ingest --project api-ingestion-lab-bq --site sc-domain:pmdata.pl --lookback-days 7
```

## Konfiguracja

Najpierw „Wspólne środowisko” z [głównego README](../README.md#wspólne-środowisko) — ADC musi mieć zakres `webmasters.readonly`. Potem:

```bash
PROJECT=api-ingestion-lab-bq
SITE=sc-domain:pmdata.pl      # usługa domenowa: sc-domain:<domena>; z prefiksem URL: https://<domena>/

# 1. Włącz Search Console API w projekcie GCP.
gcloud services enable searchconsole.googleapis.com --project=$PROJECT

# 2. W przeglądarce: Search Console -> Ustawienia -> Użytkownicy i uprawnienia -> Dodaj użytkownika
#    e-mail: ingest-runner@$PROJECT.iam.gserviceaccount.com, uprawnienia: Ograniczone (tylko odczyt).

# 3. Backfill i kontrola duplikatów (obie liczby równe).
uv run python -m search_console.ingest --project $PROJECT --site $SITE --start 2025-01-01
bq query --use_legacy_sql=false "SELECT COUNT(*), COUNT(DISTINCT FORMAT('%t|%s|%s', report_date, country, device)) FROM \`$PROJECT.raw_search_console.search_daily\`"

# 4. Testy (bez sieci i bez GCP).
uv run pytest search_console
```

## Źródło

- Endpoint: `POST https://www.googleapis.com/webmasters/v3/sites/{siteUrl}/searchAnalytics/query`, zakres `webmasters.readonly`. [Dokumentacja](https://developers.google.com/webmaster-tools/v1/searchanalytics/query).
- `siteUrl` idzie w ścieżce URL, więc `sc-domain:pmdata.pl` trzeba zakodować (`sc-domain%3Apmdata.pl`).

Zachowanie sprawdzone na żywo (2026-11-18, dane 2025-01-01..2026-11-18):

| Zapytanie | Wynik | Co z tego wynika dla kodu |
|---|---|---|
| wymiary `date` / `date, country` / `date, device` | 37 kliknięć, 679 wyświetleń, agregacja `byProperty` | sumy usługi → tabela `search_daily` |
| wymiary `date, page` | 37 kliknięć, **1089** wyświetleń, agregacja `byPage` | jedno wyświetlenie liczy się dla każdej podstrony w wyniku → osobna tabela, nie sumuj jej jako usługi ([docs](https://developers.google.com/webmaster-tools/v1/how-tos/all-your-data)) |
| wymiar `query` | 38 z 679 wyświetleń | rzadkie zapytania są anonimizowane → zapytań nie ładujemy |
| `dataState=final` vs `all` | `final` kończy się na 16.11, `all` ma też 17.11 | `all` + lookback: wstępne dane poprawią się przy kolejnych uruchomieniach |
| paginacja | `rowLimit` (maks. 25 000) + `startRow`, **bez** `rowCount` | koniec = strona krótsza niż limit |
| liczniki | `clicks: 1.0`, `impressions: 3.0` (float) | rzutowanie na `int` |

## Jak działa jedno uruchomienie

Wspólny przepływ i diagram: [główne README](../README.md#jak-dane-trafiają-do-bigquery). Specyficzne dla Search Console:

1. Sesja HTTP z tokenem i ponowieniami — wspólna z GA4 ([`common/http.py`](../common/http.py)).
2. `fetch_report` — strony po 25 000 wierszy przez `startRow`, aż przyjdzie strona krótsza niż limit. Inaczej niż w GA4, które podaje `rowCount`: ten sam cel, inny sygnał końca.
3. `to_rows` — `keys` (wartości wymiarów w kolejności z zapytania) → kolumny, liczniki → `int`.

## Tabele docelowe

`<projekt>.raw_search_console.search_daily`, klucz: `(report_date, country, device)` — sumy usługi.

`<projekt>.raw_search_console.search_pages_daily`, klucz: `(report_date, page)` — liczone per podstrona.

| Kolumna | Typ | Znaczenie |
|---|---|---|
| `report_date` | DATE | dzień w czasie **pacyficznym** (PT), nie polskim ([pomoc Google](https://support.google.com/webmasters/answer/17011259)) |
| `country` / `device` albo `page` | STRING | kod kraju ISO 3166-1 alfa-3 (`pol`), urządzenie (`MOBILE`, `DESKTOP`, `TABLET`), adres podstrony |
| `clicks`, `impressions` | INT64 | kliknięcia i wyświetlenia w wynikach Google |
| `position` | FLOAT64 | średnia pozycja w wierszu — agreguj średnią ważoną: `SUM(position * impressions) / SUM(impressions)` |
| `site`, `loaded_at` | STRING, TIMESTAMP | skąd i kiedy |

CTR nie jest zapisany — to `clicks / impressions`, liczony w SQL. Wszystkie kolumny REQUIRED.

Uwaga na etap 7: doba Search Console (PT, UTC−8 zimą) jest przesunięta o 9 h względem doby GA4 i pogody (`Europe/Warsaw`). Złączenie po dacie łączy więc nie do końca te same godziny — przy dziennych agregatach to akceptowalne, ale trzeba o tym wiedzieć, porównując dzień do dnia.

## Strategia ładowania

Przepisanie z podmianą zakresu, jak w pozostałych źródłach ([uzasadnienie](../README.md#strategie-ładowania)). Lookback ma tu ten sam powód co w pogodzie i GA4: ostatnie dni są wstępne.
