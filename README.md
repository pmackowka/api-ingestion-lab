# api-ingestion-lab

Pobieranie danych z API (głównie REST) w Pythonie i ładowanie ich do BigQuery. Projekt do nauki inżynierii danych: każde połączenie to osobny, niezależny pipeline w swoim folderze, z komentarzami po polsku, które tłumaczą mechanizm.

Kierunek domenowy: dane reklamowe po stronie wydawcy (sell-side) — rozliczenia z SSP i Google Ad Manager, kursy walut, uzgadnianie źródeł.

## Połączenia

Każdy folder ma własny README z konfiguracją krok po kroku. Ta tabela to indeks.

| Etap | System | Folder | Status | Dostęp | Czego uczy |
|---|---|---|---|---|---|
| 1 | [API NBP](https://api.nbp.pl/) — kursy walut, tabela A | [`nbp/`](nbp/README.md) | działa | publiczne, bez klucza | GET, JSON, limit zakresu dat (93 dni) → dzielenie na okna, idempotentny zapis do BigQuery |
| 2 | Atrapa API raportowego SSP (własna, FastAPI) | `ssp_mock/` | planowany | lokalnie | uwierzytelnianie tokenem, raporty asynchroniczne (zlecenie → status → pobranie), paginacja, 429 i ponowienia, dane w UTC i EUR |
| 3 | [Google Ad Manager API (REST, beta)](https://developers.google.com/ad-manager/api/beta/reports) na sieci testowej | `gam/` | planowany | darmowa sieć testowa; raporty z danymi serwowania zwracają 0 wierszy | OAuth / konto usługi, raporty GAM |
| 4 | [Prebid Server](https://docs.prebid.org/prebid-server/overview/prebid-server-overview.html) lokalnie + atrapa biddera | `prebid/` | planowany | lokalnie | OpenRTB: bid request / bid response, logi aukcji jako źródło danych |
| 5 | [AppsFlyer Pull API](https://dev.appsflyer.com/hc/reference/raw_data_pull_api_tokenv2-overview) (raw data) | `appsflyer/` | planowany | na sucho: kod z dokumentacji + atrapa odpowiedzi | bearer token, odpowiedź w CSV, strefa czasowa aplikacji, limit 1 mln wierszy na wywołanie |
| 6 | Model w BigQuery | `model/` | planowany | — | uzgadnianie GAM vs SSP: strefa czasowa, waluta (kurs NBP), brutto vs netto |

Ćwiczenie „na sucho”: prawdziwe API raportowe SSP (Magnite, PubMatic, Index Exchange) i AppsFlyer są dostępne tylko dla klientów platformy — publicznego sandboxa nie ma. Kod powstaje z oficjalnej dokumentacji, a testuje go lokalna atrapa, która odtwarza udokumentowany kontrakt: endpointy, uwierzytelnianie, format odpowiedzi i kody błędów.

## Wspólne środowisko

Foldery są niezależne od siebie, ale dzielą jedno środowisko Pythona (`pyproject.toml` w katalogu głównym).

1. `uv sync` — instaluje zależności do `.venv/`.
2. `gcloud auth application-default login` — poświadczenia dla bibliotek Google (ADC).
3. `gcloud auth application-default set-quota-project <projekt-gcp>` — projekt, który biblioteki podają jako rozliczeniowy. Musi istnieć, inaczej każde wywołanie BigQuery kończy się błędem 400.
4. Dalej według README konkretnego folderu.
