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

## Wspólne środowisko

Foldery są niezależne od siebie, ale dzielą jedno środowisko Pythona (`pyproject.toml` w katalogu głównym).

1. `uv sync` — instaluje zależności do `.venv/`.
2. `gcloud auth application-default login` — poświadczenia dla bibliotek Google (ADC).
3. `gcloud auth application-default set-quota-project <projekt-gcp>` — projekt, który biblioteki podają jako rozliczeniowy. Musi istnieć, inaczej każde wywołanie BigQuery kończy się błędem 400.
4. Dalej według README konkretnego folderu.
