# Diagram klas UML: model danych i klucze łączące źródła

Tabele `raw_*`, modele dbt w warstwie gold i klucze, którymi się łączą. CRM i ERP łączą się kluczami rekordów (krotności 1:N i 1:1), a GA4, Search Console, pogoda i NBP z resztą — tylko wspólnymi wymiarami `dim_date` i `dim_source` (modele dbt). Objaśnienia: [README główne](README.md#klucze-łączące-źródła).

```mermaid
classDiagram
    direction LR

    class contacts["raw_hubspot.contacts"] {
        contact_id PK
        email
        lead_source
        lead_date
    }
    class deals["raw_hubspot.deals"] {
        deal_id PK
        deal_key UQ
        contact_id FK
        dealstage
        amount
        closedate
    }
    class invoices["raw_odoo.invoices"] {
        invoice_id PK
        deal_key UQ, pole ref
        partner_id
        invoice_date
        amount_total
        currency
    }
    class payments["raw_odoo.payments"] {
        payment_id PK
        invoice_id FK
        payment_date
        amount
    }

    class dim_source {
        <<wymiar dbt>>
        source_medium PK
        source_clean
        channel
    }
    class dim_date {
        <<wymiar dbt>>
        date_day PK
    }
    class fct_traffic_daily {
        <<fakt dbt>>
        date_day FK
        source_medium FK
        sessions
        engaged_sessions
        contact_clicks
    }
    class int_deal_revenue {
        <<model pośredni dbt>>
        deal_id PK
        contact_id
        is_won
        amount
        invoiced_amount_net
        invoiced_amount_gross
        paid_amount
    }
    class fct_leads {
        <<fakt dbt>>
        contact_id PK
        lead_date FK
        source_medium FK
        is_test_lead
        deals
        won_deals
        won_amount
        invoiced_amount_net
        invoiced_amount_gross
        paid_amount
    }

    class ga4["raw_ga4.traffic_daily, contact_events_daily"] {
        report_date
        session_source
        session_medium
    }
    class search_console["raw_search_console.search_daily, search_pages_daily"] {
        report_date
    }
    class weather["raw_weather.daily_weather"] {
        weather_date
        location_id
    }
    class nbp["raw_nbp.exchange_rates_a"] {
        effective_date
        currency_code
    }

    contacts "1" <-- "0..*" deals : contact_id
    deals "1" <-- "0..1" invoices : deal_key
    invoices "1" <-- "0..*" payments : invoice_id

    contacts ..> dim_source : lead_source
    ga4 ..> dim_source : session_source / session_medium
    contacts ..> dim_date : lead_date
    deals ..> dim_date : closedate
    invoices ..> dim_date : invoice_date
    payments ..> dim_date : payment_date
    ga4 ..> dim_date : report_date
    search_console ..> dim_date : report_date
    weather ..> dim_date : weather_date
    nbp ..> dim_date : effective_date

    dim_date "1" <-- "0..*" fct_traffic_daily : date_day
    dim_source "1" <-- "0..*" fct_traffic_daily : source_medium
    ga4 ..> fct_traffic_daily : dzień × source / medium

    deals ..> int_deal_revenue : deal + faktura + suma wpłat
    dim_date "1" <-- "0..*" fct_leads : lead_date
    dim_source "1" <-- "0..*" fct_leads : source_medium
    contacts ..> fct_leads : kontakt = lead
    int_deal_revenue ..> fct_leads : suma po contact_id
```

| Linia | Znaczenie |
|---|---|
| ciągła, z krotnością | klucz rekordu: łączy konkretne wiersze |
| przerywana | wspólny wymiar: łączy agregaty `data × źródło`, bez użytkowników |

# Diagram sekwencji UML: od API do raportu (bronze → silver → gold)

Kolejność w jednym nocnym przebiegu na przykładzie ruchu z GA4. Kroki 1–5 działają (`ga4/ingest.py`); kroki 6–11 to etap 7 (dbt), w budowie.

```mermaid
sequenceDiagram
    autonumber
    participant GH as GitHub Actions (pipeline.yml)
    participant I as ga4/ingest.py
    participant API as GA4 Data API
    box transparent Bronze — dane surowe (raw_*)
        participant S as raw_ga4._staging_traffic_daily
        participant R as raw_ga4.traffic_daily
    end
    participant D as dbt build
    box transparent Silver — dw_prod: widoki stg_*, int_*
        participant STG as dw_prod.stg_ga4__traffic_daily
        participant INT as dw_prod.int_deal_revenue (złączenia)
    end
    box transparent Gold — dw_prod: tabele dim_*, fct_*
        participant M as dw_prod.dim_date, dw_prod.dim_source, dw_prod.fct_traffic_daily, dw_prod.fct_leads
    end
    actor A as Analityk / dashboard

    GH->>I: cron 1:41, --lookback-days 7
    I->>API: runReport (7 dni)
    API-->>I: wiersze dzień × source × medium
    I->>S: load ostatnich 7 dni (WRITE_TRUNCATE)
    I->>R: tabela bez 7 dni + schowek (WRITE_TRUNCATE_DATA)
    Note over S: schowek tylko dla ingestu — dbt go nie czyta
    GH->>D: job dbt po ingeście (needs: ingest)
    D->>STG: widok na raw_ga4.traffic_daily: nazwy, typy, strefa czasowa
    D->>INT: widok ze złączeń modeli stg_*
    D->>M: tabele wymiarów i faktów z int_* i stg_*
    A->>M: SELECT … GROUP BY dzień, źródło
```

| Krok | Po co |
|---|---|
| 4–5 | bronze: kopia źródła 1:1, cała historia; schowek `_staging_*` służy tylko do podmiany zakresu |
| 8 | silver: jeden model `stg_*` na jedną tabelę `raw_*`, bez złączeń i agregacji; wszystkie modele dbt w jednym datasecie `dw_prod` (lokalnie `dw_dev`), warstwę wskazuje prefiks |
| 9 | silver: złączenia między źródłami, np. faktura → deal → kontakt |
| 10 | gold: gwiazda Kimballa — wymiary wspólne dla wszystkich faktów |
| 11 | raporty czytają tylko gold, nigdy `raw_*` |

Kiedy powstaje dziura: `--lookback-days 7` pobiera ostatnie 7 dni od dziś, więc przerwa w harmonogramie dłuższa niż 7 dni zostawia w `raw_*` dni bez danych — trzeba wtedy uruchomić ingest ręcznie z `--start`. dbt tej dziury nie załata: modele czytają tylko to, co jest w `raw_*`.
