# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.
`AGENTS.md` to symlink do tego pliku (dla Codexa) — edytuj wyłącznie `CLAUDE.md`.

## Czym jest ten projekt

Laboratorium inżynierii danych: pobieranie danych z API (głównie REST) w Pythonie i ładowanie ich
do BigQuery. Każde źródło to osobny, niezależny pipeline we własnym folderze.

Cel: nauka mechanizmów ingestu na realnych i realistycznych źródłach — limity API, paginacja,
uwierzytelnianie, ponowienia, idempotentny zapis. Kod ma działać, a komentarze po polsku mają
tłumaczyć mechanizm i powód decyzji, nie tylko opisywać, co robi linia.

Kierunek: dane, z którymi pracuje analityk internetowy — ekosystem Google, marketing, reklama.
Etapy 2–6 w `README.md` to pierwsza propozycja (wątek ad-tech: GAM, SSP, Prebid, uzgadnianie przychodów
w etapie 6), nie zobowiązanie. Planowany krok: przegląd ogłoszeń o pracę dla inżynierów danych w Polsce
(z dbt w wymaganiach) i wybór kolejnych źródeł pod typy danych, które się w nich powtarzają.

## Plan i stan

Źródłem prawdy jest tabela „Połączenia” w `README.md` (etap, system, folder, status, dane, sandbox).
Stan na 2026-11-08: etap 1 (`nbp/`) działa, etapy 2–6 są planowane, ich foldery jeszcze nie istnieją.

## Struktura

- `README.md` — indeks połączeń + wspólne środowisko.
- `<system>/` — jeden folder na źródło: `ingest.py`, `test_ingest.py`, `README.md`.
- `<system>/README.md` — konfiguracja krok po kroku: źródło i jego sprawdzone zachowanie,
  jak działa kod, schemat tabeli docelowej, konfiguracja, pułapki.
- `pyproject.toml` + `uv.lock` — jedno środowisko dla wszystkich folderów (świadomie, bez osobnych projektów).
- `.github/workflows/ci.yml` — `uv sync --frozen` + `uv run pytest`, bez dostępu do GCP.

## Komendy

```bash
uv sync                                                            # zależności
uv run pytest                                                      # wszystkie testy (to samo co CI)
uv run pytest nbp                                                  # testy jednego folderu
uv run python nbp/ingest.py --project api-ingestion-lab-bq --start 2025-01-01   # ingest NBP
```

Zmiana zależności → commit razem z `uv.lock` (CI leci na `--frozen`).

## Środowisko GCP

- Projekt: `api-ingestion-lab-bq`, **sandbox BigQuery bez billingu**. Konsekwencje:
  - brak DML (`MERGE`, `INSERT`, `UPDATE`, `DELETE`) — idempotencję robimy query jobem z tabelą
    docelową i `WRITE_TRUNCATE` (wzorzec w `nbp/ingest.py`, `load_to_bigquery`);
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
- Atrapy API (SSP, AppsFlyer) odtwarzają udokumentowany kontrakt prawdziwego API: endpointy,
  uwierzytelnianie, format odpowiedzi, kody błędów. Kod klienta piszemy z oficjalnej dokumentacji.
- Commity po angielsku, tryb rozkazujący, bezpośrednio na `main`.
