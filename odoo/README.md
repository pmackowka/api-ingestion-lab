# Odoo ERP — faktury do wygranych deali → BigQuery

Dwa skrypty. `generate.py` wystawia w Odoo fakturę do każdego wygranego deala z HubSpota (`raw_hubspot.deals`): kwota deala netto + 23% VAT, data = zamknięcie deala, `deal_key` w polu `ref`. `ingest.py` pobiera faktury z powrotem przez JSON-2 API do BigQuery. W etapie 7 to „faktury” w łańcuchu sesje → kontakty → leady → deale → faktury.

Diagram sekwencji UML jednego uruchomienia: [`uml-diagram.md`](uml-diagram.md).

## Konfiguracja

Najpierw [„Wspólne środowisko”](../docs/konfiguracja.md#wspólne-środowisko) i etap [HubSpot](../hubspot/README.md) — generator czyta `raw_hubspot.deals` i `contacts`.

```bash
PROJECT=api-ingestion-lab-bq

# 1. Odoo 20 + PostgreSQL 17 w osobnym projekcie compose (sieć i wolumeny odoo_*; inne kontenery nietknięte).
docker compose -f odoo/docker-compose.yml up -d

# 2. Baza "lab": polska firma (plan kont l10n_pl, PLN), potem moduł Faktury (account).
docker compose -f odoo/docker-compose.yml exec web odoo db --db_host db -r odoo -w odoo init lab --country pl --language pl_PL
docker compose -f odoo/docker-compose.yml exec web odoo --db_host db -r odoo -w odoo -d lab -i account --stop-after-init --no-http

# 3. Przeglądarka: http://localhost:8069, admin / admin -> awatar -> Preferencje -> Bezpieczeństwo konta -> Nowy klucz API.
#    Kopiuj przyciskiem przy kluczu (nie przykład kodu obok), potem dopisz do .env — token HubSpota zostaje:
printf 'ODOO_API_KEY=%s\n' "$(pbpaste)" >> .env

# 4. Faktury za całą historię, potem migawka do BigQuery. Drugie uruchomienie generatora nie dubluje.
uv run --env-file .env python -m odoo.generate --project $PROJECT --start 2025-01-01
uv run --env-file .env python -m odoo.ingest --project $PROJECT --lookback-days 7

# 5. Testy (bez sieci i bez GCP).
uv run pytest odoo

# Usunięcie całego Odoo (tylko ten projekt compose):
# docker compose -p odoo down -v
```

## Źródło

Odoo 20.0 Community (obraz `odoo:20.0-20261112`), [JSON-2 API](https://www.odoo.com/documentation/19.0/developer/reference/external_api.html): `POST /json/2/<model>/<metoda>`, klucz API w `Authorization: bearer`, baza w `X-Odoo-Database`. Sprawdzone 2026-11-19:

| Zachowanie | Co robi kod |
|---|---|
| XML-RPC i JSON-RPC wycofane od 19.0, usunięcie w Odoo 22 ([źródło](https://www.odoo.com/documentation/19.0/developer/reference/external_rpc_api.html)) | tylko JSON-2 |
| argumenty wyłącznie nazwane (`domain=`, `fields=`, `vals_list=`) | `OdooClient.call(model, metoda, **params)` |
| relacja w odpowiedzi to `[id, nazwa]`, pusta wartość to `False` | `_many2one` → dwie kolumny albo NULL |
| plan kont l10n_pl ma dwa podatki 23% sprzedaży: „23% G” i „23% S” | szukany po nazwie „23% S” (usługi) |
| numer faktury (FV/2026/00001) nadawany przy księgowaniu, kolejno | deale księgowane od najstarszej daty |
| `search_read` nie podaje liczby rekordów ani kursora | strona krótsza niż `limit` = koniec |
| Odoo słucha tylko na 127.0.0.1 | ingest poza `pipeline.yml` — runner GitHuba go nie widzi; uruchamiany ręcznie |

## Tabela docelowa i strategia

`raw_odoo.invoices`, klucz `invoice_id`: `invoice_number`, `deal_key` (złączenie z `raw_hubspot.deals`), `partner_id`, `partner_name`, `invoice_date`, `due_date`, `currency`, `amount_untaxed`, `amount_tax`, `amount_total` (`NUMERIC`), `state`, `payment_state`, `created_at`, `updated_at`, `loaded_at`.

**Pełne przeładowanie** (`replace_table`), jak w HubSpocie: faktura zmienia `payment_state` tygodnie po wystawieniu, więc data wystawienia nie wyznacza zakresu do podmiany.

| Wariant | Kiedy | Dlaczego nie tutaj |
|---|---|---|
| pełna migawka (wybrany) | setki–tysiące rekordów, sandbox bez DML | — |
| przyrost po `write_date` + `MERGE` po `invoice_id` | duży ERP, billing w BigQuery | sandbox nie ma `MERGE`; usunięcia trzeba łapać osobno |
| CDC z PostgreSQL (Datastream, Debezium) | wiele tabel, opóźnienie minut | infrastruktura ponad potrzebę kilku faktur dziennie |

Idempotencja generatora: faktura z `ref = deal_key` już istnieje → deal pominięty. Ograniczenie: płatności nie są jeszcze generowane, więc każda faktura ma `payment_state = not_paid`.
