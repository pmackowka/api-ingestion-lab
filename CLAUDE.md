# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.
`AGENTS.md` to symlink do tego pliku (dla Codexa) — edytuj wyłącznie `CLAUDE.md`.

## Czym jest ten projekt

Laboratorium inżynierii danych: pobieranie danych z API (głównie REST) w Pythonie i ładowanie ich
do BigQuery. Każde źródło to osobny, niezależny pipeline we własnym folderze.

Cel: nauka mechanizmów ingestu na realnych i realistycznych źródłach — limity API, paginacja,
uwierzytelnianie, ponowienia, idempotentny zapis. Kod bez komentarzy, docstring jednozdaniowy;
mechanizm i powody decyzji opisują README folderów i `docs/`.

Kierunek: dane analityka internetowego połączone z danymi biznesowymi (lead-to-cash): pogoda z Open-Meteo,
GA4 i Search Console z pmdata.pl (prawdziwe), CRM HubSpot (konto testowe, dane syntetyczne), ERP Odoo (lokalnie w Dockerze,
dane syntetyczne), model w dbt. Repo może stać się publiczne:
żadnych odniesień do szukania pracy, ogłoszeń ani nazw firm w plikach repo.
Google Ads API i wątek ad-tech (GAM, SSP, Prebid) — świadomie poza zakresem.
Złączenie GA4 z CRM jest na agregatach `data × źródło` (Data API nie ma użytkowników, strona nie ma formularza);
syntetyczne leady dostają źródło według proporcji źródeł z GA4 i wolumen z kliknięć w kontakt.

## Plan i stan

Źródłem prawdy jest tabela „Połączenia” w `README.md` (etap ze statusem, system z folderem, dane i dostęp, czego uczy).
Stan na 2026-11-19: etapy 1 (`nbp/`), 2 (`weather/`), 3 (`ga4/`, usługa 539646739), 4 (`search_console/`, `sc-domain:pmdata.pl`), 5 (`hubspot/`, konto testowe HubSpot: kontakty i deale) i 6 (`odoo/`, Odoo 20 lokalnie w Dockerze: faktury i płatności) działają; etap 7 jest planowany.
Następny krok: etap 7 (dbt) — model lead-to-cash na `raw_*`. Ingest Odoo działa tylko lokalnie — poza `pipeline.yml`. Znana luka w `nbp/`: `--lookback-days` nie sprawdza
`MAX(effective_date)`, więc po przerwie dłuższej niż lookback trzeba podać `--start`.
Automatyzacja: workflow `.github/workflows/pipeline.yml` (cron 1:41 Europe/Warsaw + `workflow_dispatch`, osobno od `ci.yml`),
ingesty jako `strategy.matrix` z `fail-fast: false`; job `dbt` (`needs: ingest`) robi `dbt build --target prod` i `dbt source freshness`. Uzasadnienie wariantu
w `docs/orkiestracja.md` (matrix / osobny job na źródło / jeden job z krokami / osobny workflow na źródło / Airflow). Warunek matrix: każdy `<system>/ingest.py`
ma wspólny interfejs CLI z `common/cli.py` (`--project`, `--start`/`--lookback-days`, `--end`, `--dataset`).

Sprzątanie po zakończeniu projektu (konto HubSpot jest tymczasowe) — przypomnij Piotrowi:
1. `npm uninstall -g @hubspot/cli` i usunięcie `~/.hscli/` (osobisty klucz dostępu CLI).
2. Usunięcie `.env` z tokenem, sekretu `HUBSPOT_ACCESS_TOKEN` w GitHub, konta testowego, projektu aplikacji i klucza osobistego w HubSpot.
3. Usunięcie reguły `Bash(uv run --env-file .env python -m hubspot.*)` z `.claude/settings.local.json` — przywraca blokadę
   uruchamiania przez Claude Code kodu, który czyta tokeny z `.env`.
4. Odoo: `docker compose -p odoo down -v` (tylko projekt `odoo`, n8n w Dockerze zostaje), usunięcie `ODOO_API_KEY` z `.env`
   i reguły `Bash(uv run --env-file .env python -m odoo.*)` z `.claude/settings.local.json`.

## Struktura

- `README.md` — indeks połączeń, wspólny przepływ zapisu (diagram, strategie ładowania), tabela wariantów automatyzacji.
  Zasada: to, co dotyczy wszystkich źródeł, idzie do głównego README; to, co specyficzne dla źródła — do README folderu.
- `<system>/` — jeden folder na źródło, będący pakietem: `__init__.py`, `ingest.py`, `test_ingest.py`, `README.md`.
  Testy importują `from <system>.ingest import ...` — bez `__init__.py` dwa pliki `test_ingest.py`
  w różnych folderach wywracają pytest (`import file mismatch`).
- `<system>/README.md` — przykładowe uruchomienia, źródło i jego sprawdzone zachowanie,
  jak działa jedno uruchomienie (diagram), schemat tabeli docelowej, strategia ładowania i jej uzasadnienie.
- `common/` — kod wspólny dla źródeł: `bigquery.py` (zapis z podmianą zakresu), `cli.py` (interfejs CLI),
  `http.py` (sesja z tokenem z ADC i ponowieniami dla API Google).
  Wydzielony przy trzecim źródle. Dlatego skrypty uruchamia się jako moduły: `python -m <system>.ingest`
  (`python <system>/ingest.py` nie widzi pakietu `common`).
- `.github/workflows/pipeline.yml` — codzienny ingest wszystkich źródeł; poświadczenia przez Workload Identity Federation
  (pula `github`, dostawca `api-ingestion-lab` wpuszcza tylko to repo) → konto `ingest-runner`. Konfiguracja w `docs/konfiguracja.md`.
- `docs/` — dokumenty przekrojowe: `konfiguracja.md` (wspólne środowisko GCP i WIF dla GitHub Actions), `orkiestracja.md` (porównanie wariantów orkiestracji).
- `pyproject.toml` + `uv.lock` — jedno środowisko dla wszystkich folderów (świadomie, bez osobnych projektów).
- `.github/workflows/ci.yml` — job `tests`: `uv sync --frozen` + `uv run pytest`, bez dostępu do GCP; job `dbt-unit-tests`: WIF jak w `pipeline.yml`, `dbt deps` + unit testy dbt (`--select "test_type:unit"`), bo wykonują się w BigQuery.

## Komendy

```bash
uv sync                                                            # zależności
uv run pytest                                                      # wszystkie testy (to samo co CI)
uv run pytest nbp                                                  # testy jednego folderu
uv run python -m nbp.ingest --project api-ingestion-lab-bq --start 2025-01-01   # backfill NBP
uv run python -m nbp.ingest --project api-ingestion-lab-bq --lookback-days 7     # przyrost NBP
uv run python -m weather.ingest --project api-ingestion-lab-bq --lookback-days 7 # przyrost pogody
```

Zmiana zależności → commit razem z `uv.lock` (CI leci na `--frozen`).

## Środowisko GCP

- Projekt: `api-ingestion-lab-bq`, **sandbox BigQuery bez billingu**. Konsekwencje:
  - brak DML (`MERGE`, `INSERT`, `UPDATE`, `DELETE`) — idempotencję robimy query jobem z tabelą
    docelową i `WRITE_TRUNCATE_DATA` (`common/bigquery.py`, `replace_date_range`, używany przez wszystkie źródła);
  - tabele wygasają po 60 dniach — po wygaśnięciu ingest uruchamia się ponownie z pełnym zakresem.
- Poświadczenia: ADC z podszywaniem się pod konto usługi `ingest-runner` (bez pliku z kluczem), zakresy
  `cloud-platform` + `analytics.readonly` + `webmasters.readonly`; konfiguracja w `docs/konfiguracja.md`.
  Konto usługi ma w projekcie tylko `bigquery.dataEditor`, `bigquery.jobUser` i `bigquery.readSessionUser` (dbt v2), w GA4 rolę Widz, w Search Console uprawnienie Ograniczone.
- Datasety surowe mają prefiks `raw_` (np. `raw_nbp`) i lokalizację **EU** (`LOCATION` w `common/bigquery.py`) — polityka
  prywatności pmdata.pl obiecuje przechowywanie w UE. Lokalizacji nie da się zmienić: zła = usunąć dataset i backfill.

## Konwencje

- Kod i nazwy po angielsku, docstringi (jedno zdanie) i README po polsku. Bez komentarzy w kodzie i YAML — wyjątek: każdy test dbt ma jedną linię komentarza z typem testu (generic wbudowany, generic z paczki, singular, unit); własne testy generic — z paczki (`dbt_utils`), nie z własnych makr.
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

## Tryb pracy krok po kroku

1. Jeden krok = jedna logiczna zmiana (model, jego testy, poprawka generatora). Proponuj tylko jeden następny krok.
2. Zmianę zapisuj od razu w plikach i zostaw niezacommitowaną — Piotr przegląda ją w Cursorze jako „Modified”.
   Kod commitowany przed przeglądem znika z widoku zmian w Cursorze.
3. W terminalu podsumowanie: co i dlaczego, wynik `dbt build`/`pytest` i weryfikacja „na czerwono”
   (na chwilę psujesz model albo kod, pokazujesz padający test, przywracasz). Bez wklejania kodu.
4. „Dalej” = Piotr przejrzał zmianę. Najpierw commit + push tej jednej zmiany, potem następny krok. Nie zbieraj
   kilku zmian w jeden push.
5. Przed commitem: grep staged diffu po `~/.config/git/forbidden-patterns.txt`; autor
   `git -c user.name=Piotr -c user.email=pmackowka@gmail.com`; bez stopek Claude'a.
6. Komentarze do nauki: na prośbę Piotra dopisz w kodzie komentarz po polsku pod każdą linią (wyjaśnienie
   dla dewelopera Pythona/SQL). To wyjątek od zakazu komentarzy, tylko do czytania w Cursorze: nigdy ich nie
   commituj. Przed commitem innej zmiany w tym samym pliku usuń je (`git diff` bez linii z komentarzami).
