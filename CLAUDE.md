# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.
`AGENTS.md` to symlink do tego pliku (dla Codexa) — edytuj wyłącznie `CLAUDE.md`.

## Czym jest ten projekt

Laboratorium inżynierii danych: pobieranie danych z API (głównie REST) w Pythonie i ładowanie ich
do BigQuery. Każde źródło to osobny, niezależny pipeline we własnym folderze.

Cel: nauka mechanizmów ingestu na realnych i realistycznych źródłach — limity API, paginacja,
uwierzytelnianie, ponowienia, idempotentny zapis. Kod ma działać, a komentarze po polsku mają
tłumaczyć mechanizm i powód decyzji, nie tylko opisywać, co robi linia.

Kierunek: dane analityka internetowego połączone z danymi biznesowymi (lead-to-cash): pogoda z Open-Meteo,
GA4 i Search Console z pmdata.pl (prawdziwe), CRM HubSpot (konto testowe, dane syntetyczne), ERP Odoo (lokalnie w Dockerze,
dane demo), model w dbt. Wybór wynika z przeglądu ogłoszeń DE z dbt z 2026-11-17 (sekcja w `README.md`).
Google Ads API i wątek ad-tech (GAM, SSP, Prebid) — świadomie poza zakresem.
Złączenie GA4 z CRM jest na agregatach `data × źródło` (Data API nie ma użytkowników, strona nie ma formularza);
syntetyczne leady dostają źródło według proporcji źródeł z GA4 i wolumen z kliknięć w kontakt.

## Plan i stan

Źródłem prawdy jest tabela „Połączenia” w `README.md` (etap, system, folder, status, dane i dostęp).
Stan na 2026-11-17: etap 1 (`nbp/`) działa, etapy 2–7 są planowane, ich foldery jeszcze nie istnieją.
Następny krok: etap 2 (`weather/`, Open-Meteo — bez klucza, ten sam wzorzec co NBP), potem etap 3 (`ga4/`,
GA4 Data API dla pmdata.pl; na start: dostęp ADC albo konta usługi do usługi GA4 i property ID od Piotra). Znana luka w `nbp/`: `--lookback-days` nie sprawdza
`MAX(effective_date)`, więc po przerwie dłuższej niż lookback trzeba podać `--start`.

## Struktura

- `README.md` — indeks połączeń, porównanie miejsc uruchamiania (automatyzacja) + wspólne środowisko.
- `<system>/` — jeden folder na źródło, będący pakietem: `__init__.py`, `ingest.py`, `test_ingest.py`, `README.md`.
  Testy importują `from <system>.ingest import ...` — bez `__init__.py` dwa pliki `test_ingest.py`
  w różnych folderach wywracają pytest (`import file mismatch`).
- `<system>/README.md` — przykładowe uruchomienia, źródło i jego sprawdzone zachowanie,
  jak działa jedno uruchomienie (diagram), schemat tabeli docelowej, strategia ładowania i jej uzasadnienie.
- `pyproject.toml` + `uv.lock` — jedno środowisko dla wszystkich folderów (świadomie, bez osobnych projektów).
- `.github/workflows/ci.yml` — `uv sync --frozen` + `uv run pytest`, bez dostępu do GCP.

## Komendy

```bash
uv sync                                                            # zależności
uv run pytest                                                      # wszystkie testy (to samo co CI)
uv run pytest nbp                                                  # testy jednego folderu
uv run python nbp/ingest.py --project api-ingestion-lab-bq --start 2025-01-01   # backfill NBP
uv run python nbp/ingest.py --project api-ingestion-lab-bq --lookback-days 7     # przyrost NBP
```

Zmiana zależności → commit razem z `uv.lock` (CI leci na `--frozen`).

## Środowisko GCP

- Projekt: `api-ingestion-lab-bq`, **sandbox BigQuery bez billingu**. Konsekwencje:
  - brak DML (`MERGE`, `INSERT`, `UPDATE`, `DELETE`) — idempotencję robimy query jobem z tabelą
    docelową i `WRITE_TRUNCATE_DATA` (wzorzec w `nbp/ingest.py`, `load_to_bigquery`);
  - tabele wygasają po 60 dniach — po wygaśnięciu ingest uruchamia się ponownie z pełnym zakresem.
- Poświadczenia: ADC (`gcloud auth application-default login`), quota project ustawiony na
  `api-ingestion-lab-bq`. Błąd 400 „Project ... not found or deleted” = zły quota project w ADC.
- Datasety surowe mają prefiks `raw_` (np. `raw_nbp`).

## Konwencje

- Kod i nazwy po angielsku, komentarze, docstringi i README po polsku.
- Fakty o API (limity, kody błędów, format odpowiedzi) sprawdzaj na żywo albo w dokumentacji
  i zapisuj w README folderu z datą sprawdzenia — nie z pamięci.
- Wzorzec ingestu (z `nbp/`): okna/paginacja → pobranie → spłaszczenie do wierszy → load do
  tabeli `_staging_*` (`WRITE_TRUNCATE`) → idempotentne przepisanie tabeli docelowej.
- Kwoty i kursy: `Decimal` w Pythonie, `NUMERIC` w BigQuery — nigdy float.
- Nowa logika z pętlą/rozgałęzieniem/parserem → mały test pytest w `<system>/test_ingest.py`.
  Testy nie łączą się z siecią ani z GCP.
- Nowy etap = nowy folder + README folderu + aktualizacja wiersza w tabeli „Połączenia”.
- Dane syntetyczne trafiają do prawdziwych systemów (konto testowe HubSpot, lokalne Odoo), a nie do
  atrap — ingest zawsze rozmawia z prawdziwym API. Generator danych ma stały `seed` (powtarzalność).
- Commity po angielsku, tryb rozkazujący, bezpośrednio na `main`.
