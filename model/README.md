# model — dbt na BigQuery

Model lead-to-cash na tabelach `raw_*`: ruch z GA4 → lead w HubSpot → deal → faktura w Odoo → wpłata, z kontekstem dnia (pogoda, święta) i przeliczeniem walut (kurs NBP). Obok wyniki stron z Search Console z artykułem z sitemapy pmdata.pl. Warstwy i datasety: [`README.md`](../README.md#warstwy-danych), klucze łączące źródła i diagram klas: [`uml-diagram.md`](../uml-diagram.md).

## Uruchomienie

Wersje: dbt 2.0.11, `dbt_utils` 1.4.1 (`package-lock.yml`). Poświadczenia z ADC (`method: oauth` w `profiles.yml`), jak w ingestach — konfiguracja w [`docs/konfiguracja.md`](../docs/konfiguracja.md).

```bash
cd model
uv run --group dbt dbt deps                              # dbt_utils
uv run --group dbt dbt build                             # modele + testy, target dev → dw_dev
uv run --group dbt dbt build --select int_deal_revenue+  # model i wszystko, co z niego korzysta
uv run --group dbt dbt test --select "test_type:unit"    # tylko unit testy (to samo co CI)
uv run --group dbt dbt show --select fct_leads           # podgląd wyniku bez zapisu
```

| Target | Dataset | Kto uruchamia |
|---|---|---|
| `dev` (domyślny) | `dw_dev` | lokalnie |
| `prod` | `dw_prod` | job `dbt` w [`pipeline.yml`](../.github/workflows/pipeline.yml) po ingestach: `dbt build --target prod` + `dbt source freshness` |

## Modele

| Model | Warstwa | Jeden wiersz | Co robi |
|---|---|---|---|
| `stg_<system>__<tabela>` | staging (widok) | jak w `raw_*` | nazwy, typy, strefa czasowa `Europe/Warsaw`, flagi; bez złączeń |
| `int_invoices_converted_to_pln` | intermediate (widok) | faktura | kwoty w PLN po kursie NBP |
| `int_deal_revenue` | intermediate (widok) | deal | deal + zaksięgowana faktura + suma nieanulowanych wpłat, w PLN |
| `int_search_pages_with_articles` | intermediate (widok) | dzień × strona | wynik strony z Search Console + artykuł z sitemapy (tytuł, sekcja, dni od publikacji) |
| `dim_date` | mart (tabela) | dzień od 2025-01-01 | kalendarz ISO + pogoda i święta jako atrybuty dnia |
| `dim_source` | mart (tabela) | para `source / medium` | źródło ujednolicone seedem `source_aliases` i kanał |
| `fct_traffic_daily` | mart (tabela) | dzień × `source / medium` | sesje i kliknięcia w kontakt z GA4 |
| `fct_leads` | mart (tabela) | kontakt (lead) | lead z sumą deali, wygranych, faktur i wpłat |

## Decyzje

- **Pogoda w `dim_date` jako kategorie, nie liczby.** `raw_weather` ma ziarno dzień × miasto, a GA4 nie ma miasta — łączy je tylko data. Średnia z 5 miast daje `is_rainy_day` (deszcz ≥ 1 mm w co najmniej 3 miastach) i `temperature_band`; liczba w wymiarze zsumowałaby się po złączeniu z faktem.
- **Kurs faktury z ostatniego dnia notowań przed datą faktury** (art. 31a ustawy o VAT): złączenie `effective_date < invoice_date` i `ARRAY_AGG … LIMIT 1`, bo NBP nie publikuje kursów w weekendy i święta, a BigQuery odrzuca podzapytania skorelowane z inną tabelą. PLN ma kurs 1 (tabela A go nie zawiera).
- **Wpłaty w walucie obcej po kursie faktury**, nie z dnia wpłaty — suma wpłat zgadza się z brutto; różnic kursowych model nie liczy.
- **Odoo nie jest źródłem kwot w PLN:** baza nie ma kursów EUR, więc `amount_untaxed_signed` w Odoo równa się kwocie w EUR.
- **Search Console łączy się z sitemapą po adresie kanonicznym** (`canonical_page`): `https` bez `www`, stare `/blog/` → `/artykuly/`, końcowy `/` — tak jak przekierowania 301 strony. Ziarno zostaje dzień × `page` z Search Console, więc pozycji nie trzeba uśredniać między wariantami adresu.
- **Leady testowe zostają w `fct_leads` z flagą `is_test_lead`** (źródło Tag Assistant). Bramką jest generator deali (`hubspot/generate.py`), hurtownia tylko oznacza; `dim_source` i ruch z GA4 pomijają wejścia testowe.

## Testy

Każdy test ma w YAML jedną linię komentarza z typem.

| Typ | Gdzie | Przykład |
|---|---|---|
| generic wbudowany | `_<warstwa>__models.yml` | `unique`, `not_null`, `relationships`, `accepted_values` |
| generic z paczki | `_<warstwa>__models.yml` | `dbt_utils.equal_rowcount` (złączenie nie gubi ani nie mnoży wierszy), `dbt_utils.expression_is_true` |
| singular | `tests/` | faktura = kwota deala przeliczona kursem faktury (± pół centa), wpłaty ≤ brutto, Google pokazuje tylko adresy z sitemapy |
| unit | `_<warstwa>__unit_tests.yml` | kurs z dnia przed fakturą, suma wpłat, flaga leada testowego |

Unit testy wykonują się w BigQuery, więc w CI mają osobny job `dbt-unit-tests` z WIF ([`ci.yml`](../.github/workflows/ci.yml)). W `dbt build` unit test modelu biegnie przed jego budową, testy danych po niej; błąd pomija modele zależne (`SKIP`), a tabela z poprzedniego przebiegu zostaje.

## Ograniczenia

- `raw_odoo` ładuje się tylko lokalnie (`odoo.ingest`), poza `pipeline.yml` — w sandboxie wygasa po 60 dniach bez przeładowania.
- Job `dbt` czeka na wszystkie ingesty (`needs: ingest`): awaria jednego źródła wstrzymuje cały build tego dnia.
- Sitemapa to migawka (SCD 1): dzisiejszy tytuł i data zmiany artykułu trafiają też do wcześniejszych dni. Historia zmian wymagałaby `dbt snapshot`, który aktualizuje wiersze (DML) — sandbox go odrzuca.
- `generate-leads` i `dbt` biegną równolegle, więc nowe leady z HubSpota trafiają do `fct_leads` dzień później.
