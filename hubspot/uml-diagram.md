# Diagram sekwencji UML: formularz → HubSpot → BigQuery

Diagram sekwencji UML: jak lead i deal powstają w prawdziwej firmie i jak trafiają do hurtowni.
W tym repo kroki 1–9 udaje `generate.py`; kroki 10–11 to `ingest.py` — działa tak samo jak na produkcji.

```mermaid
sequenceDiagram
    autonumber
    actor K as Klient
    participant F as Strona (frontend)
    participant B as Backend
    participant DB as Baza transakcyjna
    participant W as Worker kolejki
    participant H as HubSpot CRM
    participant G as GTM → sGTM (Stape) → GA4
    actor S as Handlowiec
    participant P as Pipeline (ingest)
    participant BQ as BigQuery

    K->>F: wysyła formularz
    F->>B: POST /api/contact
    B->>DB: INSERT lead + zadanie w outbox (jedna transakcja)
    DB-->>B: lead_id
    B-->>F: 201 {lead_id}
    F->>G: dataLayer.push generate_lead {lead_id}
    Note over G,BQ: eksport GA4: zdarzenie z lead_id i źródłem ruchu sesji
    W->>DB: pobiera zadanie z outbox
    W->>H: upsert kontaktu po e-mailu (lead_id we właściwości)
    Note over W,H: błąd / 429 → ponowienie później, lead nie ginie
    S->>H: zakłada deal, zmienia etapy, wygrywa / przegrywa
    P->>H: codziennie: kontakty i deale (paginacja kursorem)
    P->>BQ: raw_hubspot.contacts, raw_hubspot.deals
    Note over BQ: dbt: złączenie GA4 ↔ HubSpot po lead_id → przychód per źródło
```

| Krok | Kto pisze / obsługuje | Po co |
|---|---|---|
| 3 | backend developer | lead i zadanie dla HubSpota zapisują się razem albo wcale (wzorzec outbox) |
| 5–6 | backend + frontend | `lead_id` z bazy trafia do GA4 — jedyny wspólny klucz GA4 i CRM |
| 7–8 | backend developer (worker) | klient nie czeka na HubSpot, a jego awaria nie gubi leada |
| 9 | sprzedaż | etap deala zmienia się w czasie — dlatego ingest robi pełną migawkę |
| 10–11 | data engineer | ten sam wzorzec co `ingest.py` |
