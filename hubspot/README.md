# HubSpot CRM — syntetyczne leady i deale → BigQuery

Dwa skrypty. `generate.py` zamienia kliknięcia w kontakt z GA4 w syntetyczne leady w HubSpot: lead dziedziczy źródło i medium kliknięcia, więc proporcje źródeł zgadzają się z GA4. Część leadów dostaje deal powiązany z kontaktem. `ingest.py` pobiera kontakty i deale z powrotem przez CRM API do BigQuery — tak jak z każdego CRM. W etapie 7 to „leady” w łańcuchu sesje → kontakty → leady → deale.

## Konfiguracja

Najpierw [„Wspólne środowisko”](../docs/konfiguracja.md#wspólne-środowisko) i backfill [GA4](../ga4/README.md) — generator czyta `raw_ga4.contact_events_daily`.

```bash
PROJECT=api-ingestion-lab-bq

# 1. HubSpot: zwykłe (darmowe) konto -> Rozwój -> Testowanie -> Konta testowe -> Utwórz konto testowe programisty.
#    Huby: Darmowe. Potem w koncie testowym: Ustawienia -> Ustawienia domyślne konta -> strefa Europe/Warsaw, waluta PLN.

# 2. HubSpot CLI: aplikacje z tokenem tworzy się już tylko przez projekt (stare „prywatne aplikacje” wyłączono).
npm install -g @hubspot/cli
hs account auth --account <id-zwykłego-konta> --name main --default   # w osobnym terminalu: prosi o osobisty klucz

# 3. Wgranie aplikacji z hubspot/app/ (uprawnienia w src/app/app-hsmeta.json).
(cd hubspot/app && hs project upload --force)

# 4. Przeglądarka: Rozwój -> Projekty -> api-ingestion-lab -> api_ingestion_lab_app -> Rozkład ->
#    Dodaj instalacje testowe -> konto testowe -> Zainstaluj. Przy koncie kliknij „Kopiuj” obok tokenu.

# 5. Token ze schowka do .env (w .gitignore) — nie przechodzi przez ekran ani historię powłoki.
printf 'HUBSPOT_ACCESS_TOKEN=%s\n' "$(pbpaste)" > .env && chmod 600 .env && head -c 25 .env   # ma pokazać ...=pat-

# 6. Token jako sekret repo dla pipeline.yml (też ze schowka).
pbpaste | gh secret set HUBSPOT_ACCESS_TOKEN

# 7. Leady i deale za całą historię GA4, potem migawka kontaktów i deali do BigQuery. Drugie uruchomienie generatora nie dubluje.
uv run --env-file .env python -m hubspot.generate --project $PROJECT --start 2025-01-01
uv run --env-file .env python -m hubspot.ingest --project $PROJECT --lookback-days 7

# 8. Testy (bez sieci i bez GCP).
uv run pytest hubspot
```

## Źródło

HubSpot CRM API w wersji `2026-09` (ścieżki `/crm/objects/2026-09/...`), token statyczny aplikacji z dystrybucją `private`. Sprawdzone 2026-11-18 ([kontakty](https://developers.hubspot.com/docs/api-reference/latest/crm/objects/contacts/guide), [limity](https://developers.hubspot.com/docs/developer-tooling/platform/usage-guidelines)):

| Zachowanie | Co robi kod |
|---|---|
| nowych „legacy private apps” nie da się utworzyć | aplikacja jako projekt w `hubspot/app/`, token z instalacji w koncie testowym |
| konto testowe wygasa po 90 dniach bez wywołań API | codzienny `pipeline.yml` je podtrzymuje |
| `hs_analytics_source` tylko do odczytu (liczy go skrypt HubSpota na stronie) | własne właściwości `lead_source`, `lead_event`, `lead_date`; 409 przy ponownym tworzeniu = już są |
| batch: maks. 100 rekordów; `batch/upsert` z `idProperty: email` | paczki po 100, e-mail deterministyczny → bez duplikatów |
| lista: maks. 100 na stronę, kursor `paging.next.after` | pętla do braku `paging` |
| 429 po przekroczeniu limitu (100 zapytań / 10 s na aplikację) | `urllib3.Retry` czeka zgodnie z `Retry-After` |
| nowe konto ma 2 przykładowe kontakty HubSpota | w tabeli z `lead_source` = NULL |
| deal nie ma wbudowanego unikalnego klucza (kontakt ma `email`) | własna właściwość `deal_key` z `hasUniqueValue: true` (nie do zmiany po utworzeniu); wystarczył scope `crm.schemas.contacts.write`, choć dokumentacja wymienia też `crm.schemas.deals.write` |
| odpowiedź `batch/upsert` zawiera `id` i tylko wysłane właściwości | klucz (`email`, `deal_key`) wysyłany w `properties` → mapa klucz → ID bez dodatkowych zapytań |
| `batch/upsert` nie przyjmuje `associations` | osobno `POST /crm/associations/2026-09/deal/contact/batch/associate/default`; ponowienie nie dubluje powiązań |
| etap deala to wewnętrzne ID lejka, nie etykieta | `appointmentscheduled`…`contractsent`, `closedwon`, `closedlost` z `GET /crm/pipelines/2026-09/deals` |

## Tabela docelowa i strategia

`raw_hubspot.contacts`, klucz `contact_id`: `email`, `firstname`, `lastname`, `lead_source` („źródło / medium” z GA4), `lead_event`, `lead_date` (doba GA4, `Europe/Warsaw`), `created_at`, `updated_at`, `loaded_at`.

`raw_hubspot.deals`, klucz `deal_id`: `deal_key`, `dealname`, `pipeline`, `dealstage`, `amount` (`NUMERIC`, PLN), `closedate`, `contact_id` (najmniejsze ID powiązanego kontaktu → złączenie z `contacts`), `created_at`, `updated_at`, `loaded_at`.

**Pełne przeładowanie** (`replace_table` w [`common/bigquery.py`](../common/bigquery.py)), nie podmiana zakresu dat jak w pozostałych źródłach. Kontakt to rekord zmienialny: poprawiony dziś kontakt sprzed roku nie ma jednej daty, po której dałoby się podmienić zakres. Typowy wybór to przyrost po `lastmodifieddate` (search API) + `MERGE` po `contact_id` — sandbox nie ma DML, a przy setkach kontaktów migawka jest tania i łapie też usunięcia. Z billingiem i dużym CRM: przyrost + `MERGE`; uwaga, search API zwraca maks. 10 000 wyników na zapytanie, więc przyrost trzeba dzielić na okna czasu.

Generator: kliknięcie → lead z prawdopodobieństwem `LEAD_RATE` (0,5), generator losowy na dzień (`SEED` + data), więc przeliczenie tygodnia daje te same leady co pełny backfill. Ograniczenie: gdy GA4 dopisze kliknięcie wstecz, numeracja leadów tego dnia się przesuwa — upsert nadpisuje właściwości, nie tworzy duplikatów.

Deale: lead → deal z prawdopodobieństwem `DEAL_RATE` (0,4), generator losowy na lead (`SEED` + e-mail). Zamknięcie po 7–45 dniach (`SALES_CYCLE_DAYS`): przed tą datą deal jest na otwartym etapie, po niej wygrany (`WIN_RATE` 0,35) albo przegrany. Etap zależy od dnia uruchomienia, wylosowane wartości — nie, więc deal zmienia etap jak w prawdziwym CRM. Dlatego generator przelicza okno poszerzone o 45 dni wstecz: inaczej deal leada sprzed tygodnia zostałby na zawsze otwarty.
