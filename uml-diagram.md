# Diagram klas UML: klucze łączące źródła

Tabele `raw_*` i klucze, którymi się łączą. CRM i ERP łączą się kluczami rekordów (krotności 1:N i 1:1), a GA4, Search Console, pogoda i NBP z resztą — tylko wspólnymi wymiarami `dim_date` i `dim_source` (modele dbt). Objaśnienia: [README główne](README.md#klucze-łączące-źródła).

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
    }
    class dim_date {
        <<wymiar dbt>>
        date PK
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
```

| Linia | Znaczenie |
|---|---|
| ciągła, z krotnością | klucz rekordu: łączy konkretne wiersze |
| przerywana | wspólny wymiar: łączy agregaty `data × źródło`, bez użytkowników |
