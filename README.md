# api-ingestion-lab

Pobieranie danych z API (głównie REST) w Pythonie i ładowanie ich do BigQuery. Projekt do nauki inżynierii danych: każdy etap to działający pipeline z komentarzami po polsku, które tłumaczą mechanizm.

Kierunek domenowy: dane reklamowe po stronie wydawcy (sell-side) — rozliczenia z SSP i Google Ad Manager, kursy walut, uzgadnianie źródeł.

## Plan

| Etap | Źródło | Czego uczy | Dostęp |
|---|---|---|---|
| 1 | [API NBP](https://api.nbp.pl/) — kursy walut, tabela A | GET, JSON, limit zakresu dat (93 dni) → dzielenie na okna, idempotentny zapis do BigQuery | publiczne, bez klucza |
| 2 | Atrapa API raportowego SSP (własna, FastAPI) | uwierzytelnianie tokenem, raporty asynchroniczne (zlecenie → status → pobranie), paginacja, 429 i ponowienia, dane w UTC i EUR | lokalnie |
| 3 | [Google Ad Manager API (REST, beta)](https://developers.google.com/ad-manager/api/beta/reports) na sieci testowej | OAuth / konto usługi, raporty GAM | darmowa sieć testowa; raporty z danymi serwowania zwracają 0 wierszy |
| 4 | [Prebid Server](https://docs.prebid.org/prebid-server/overview/prebid-server-overview.html) lokalnie + atrapa biddera | OpenRTB: bid request / bid response, logi aukcji jako źródło danych | lokalnie |
| 5 | [AppsFlyer Pull API](https://dev.appsflyer.com/hc/reference/raw_data_pull_api_tokenv2-overview) (raw data) | bearer token, odpowiedź w CSV, strefa czasowa aplikacji, limit 1 mln wierszy na wywołanie | na sucho: kod z dokumentacji + atrapa odpowiedzi |
| 6 | Model w BigQuery | uzgadnianie GAM vs SSP: strefa czasowa, waluta (kurs NBP), brutto vs netto | — |

Ćwiczenie „na sucho”: prawdziwe API raportowe SSP (Magnite, PubMatic, Index Exchange) i AppsFlyer są dostępne tylko dla klientów platformy — publicznego sandboxa nie ma. Kod powstaje z oficjalnej dokumentacji, a testuje go lokalna atrapa, która odtwarza udokumentowany kontrakt: endpointy, uwierzytelnianie, format odpowiedzi i kody błędów.

## Struktura

Powstaje etapami — katalog na etap.
