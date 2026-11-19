# Diagram sekwencji UML: jedno uruchomienie ingestu NBP

Kto wywołuje kogo w jednym przebiegu `nbp/ingest.py`. Wspólny zapis do BigQuery (staging → podmiana zakresu): [README główne](../README.md).

```mermaid
sequenceDiagram
    autonumber
    participant GH as GitHub Actions (pipeline.yml)
    participant I as nbp/ingest.py
    participant API as API NBP (tabela A)
    participant BQ as BigQuery raw_nbp

    GH->>I: --lookback-days 7 (cron 1:41)
    I->>I: split_windows: okna po maks. 93 dni
    loop każde okno
        I->>API: GET /exchangerates/tables/A/{start}/{end}/ (Accept: JSON)
        alt 200
            API-->>I: notowania dzień × waluty (kursy jako Decimal)
        else 404
            API-->>I: brak notowań w oknie (weekend, święta) → pusta lista
        else 400 albo 5xx
            API-->>I: błąd → przerwanie, zanim cokolwiek trafi do BigQuery
        end
    end
    I->>I: to_rows: jeden wiersz na dzień × walutę
    Note over I: pusty zakres (sam weekend) → koniec bez zapisu
    I->>BQ: load do _staging_exchange_rates_a (WRITE_TRUNCATE)
    I->>BQ: zapytanie: tabela bez [start, end] + staging → exchange_rates_a (WRITE_TRUNCATE_DATA)
```

| Krok | Po co |
|---|---|
| 2 | API odrzuca zakres dłuższy niż 93 dni, a backfill obejmuje lata |
| 4–6 | 404 to poprawny stan danych, każdy inny błąd chroni tabelę przed dziurawym zakresem |
| 8–9 | podmiana zakresu jednym zapytaniem: powtórne uruchomienie nie dubluje wierszy |
