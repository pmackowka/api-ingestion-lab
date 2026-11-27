# Sitemapa — artykuły pmdata.pl z datami publikacji → BigQuery

Lista adresów pmdata.pl z tytułem i datą publikacji artykułu: wymiar strony dla `search_pages_daily` z Search Console (złączenie po URL) — wyświetlenia i kliknięcia w dniach od publikacji.

## Przykładowe uruchomienia

```bash
# Pełna migawka: zakres dat z CLI jest ignorowany, każde uruchomienie pobiera całą sitemapę.
uv run python -m sitemap.ingest --project api-ingestion-lab-bq

# To samo wywołanie co w pipeline.yml (wspólny interfejs CLI).
uv run python -m sitemap.ingest --project api-ingestion-lab-bq --lookback-days 7
```

## Konfiguracja

Najpierw [„Wspólne środowisko”](../docs/konfiguracja.md#wspólne-środowisko). Sitemapa i strony są publiczne, bez klucza:

```bash
PROJECT=api-ingestion-lab-bq

# 1. Ładowanie: dataset raw_sitemap i tabela powstają same.
uv run python -m sitemap.ingest --project $PROJECT

# 2. Kontrola duplikatów: obie liczby równe (klucz: adres).
bq query --use_legacy_sql=false "SELECT COUNT(*), COUNT(DISTINCT url) FROM \`$PROJECT.raw_sitemap.pages\`"

# 3. Testy (bez sieci i bez GCP).
uv run pytest sitemap
```

## Źródło

`GET https://pmdata.pl/sitemap-index.xml` ([protokół Sitemaps](https://www.sitemaps.org/protocol.html)) → sitemapy z indeksu → `GET` każdej strony po JSON-LD. Sprawdzone na żywo (2026-11-27):

| Zachowanie | Co robi kod |
|---|---|
| indeks wskazuje jedną sitemapę (`sitemap-0.xml`), ale protokół dopuszcza wiele | `parse_index` zwraca listę, `main` czyta każdą |
| XML z domyślną przestrzenią nazw `http://www.sitemaps.org/schemas/sitemap/0.9` | `findall` z mapą `NS` — bez niej zwraca pustą listę |
| 59 adresów; 5 bez `lastmod` (strona główna, kalkulatory, polityka prywatności) | `lastmod` NULLABLE |
| `lastmod` artykułu to `dateModified`, a bez niej `datePublished` (37 z 37) — nie data publikacji | daty z JSON-LD `BlogPosting` strony (`parse_article`) |
| 37 artykułów ma JSON-LD `BlogPosting`, 33 z nich `dateModified` | strona bez artykułu → puste `headline` i daty |
| 17 adresów w `/artykuly/` to listy i tagi (`/artykuly/tag/…`) bez `BlogPosting` | artykuł rozpoznaje `date_published`, nie ścieżka |

Ingest robi 1 + 1 + 59 zapytań — bez ponowień i równoległości, bo źródło jest małe i własne.

## Tabela docelowa

`raw_sitemap.pages`, klucz `url`.

| Kolumna | Typ | Znaczenie |
|---|---|---|
| `url` | STRING | adres z sitemapy, z końcowym `/` |
| `section` | STRING | pierwszy segment ścieżki (`artykuly`, `kalkulatory`); strona główna → `NULL` |
| `lastmod` | TIMESTAMP | ostatnia zmiana według sitemapy |
| `headline` | STRING | tytuł artykułu z JSON-LD |
| `date_published`, `date_modified` | TIMESTAMP | daty z JSON-LD; `NULL` dla stron bez artykułu |
| `loaded_at` | TIMESTAMP | czas zapisu (UTC) |

Strategia: pełne przeładowanie (`replace_table` w [`common/bigquery.py`](../common/bigquery.py), `WRITE_TRUNCATE`), bo adresy znikają ze strony, a cała sitemapa to kilkadziesiąt wierszy — podmiana zakresu dat nie ma tu klucza czasu. Porównanie strategii: [główne README](../README.md#strategie-ładowania).
