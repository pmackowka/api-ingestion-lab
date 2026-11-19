# Diagram sekwencji UML: wygrane deale → faktury → BigQuery

Kto wywołuje kogo w jednym przebiegu `odoo/generate.py` i `odoo/ingest.py`. Konfiguracja i strategia: [README](README.md).

```mermaid
sequenceDiagram
    autonumber
    actor P as Piotr (lokalnie)
    participant G as odoo/generate.py
    participant BQ as BigQuery
    participant O as Odoo JSON-2 API
    participant I as odoo/ingest.py

    P->>G: --start albo --lookback-days
    G->>BQ: deale closedwon + kontakt (raw_hubspot)
    BQ-->>G: deal_key, kwota, data zamknięcia, e-mail
    G->>O: account.move/search_read (ref in deal_key)
    O-->>G: deale, które mają już fakturę → pomijane
    G->>O: res.partner/search_read + create (klienci po e-mailu)
    G->>O: account.move/create (netto + 23% S, ref = deal_key)
    G->>O: account.move/action_post (numer FV/RRRR/NNNNN)
    P->>I: --lookback-days 7
    loop strony (limit 100, offset)
        I->>O: account.move/search_read (out_invoice, order id)
        O-->>I: faktury
    end
    Note over I: strona krótsza niż limit → koniec
    I->>BQ: raw_odoo.invoices (WRITE_TRUNCATE, pełna migawka)
```

| Krok | Po co |
|---|---|
| 2–3 | faktura powstaje tylko do deala wygranego w CRM — jak w firmie po podpisaniu umowy |
| 4–5 | idempotencja: drugie uruchomienie nie wystawia drugiej faktury |
| 8 | dopiero zaksięgowana faktura ma numer i trafia do księgi |
| 10–12 | pełna migawka: zmiana statusu płatności trafia do BigQuery przy następnym ingeście |
