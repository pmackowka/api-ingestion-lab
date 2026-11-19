# Diagram sekwencji UML: jedno uruchomienie ingestu GA4

Kto wywołuje kogo w jednym przebiegu `ga4/ingest.py`. Wspólny zapis do BigQuery (staging → podmiana zakresu): [README główne](../README.md).

```mermaid
sequenceDiagram
    autonumber
    participant GH as GitHub Actions (pipeline.yml)
    participant I as ga4/ingest.py
    participant AUTH as ADC (WIF → ingest-runner)
    participant API as GA4 Data API
    participant BQ as BigQuery raw_ga4

    GH->>I: --property, --lookback-days 7 (cron 1:41)
    I->>AUTH: token z zakresem analytics.readonly
    AUTH-->>I: krótkotrwały token konta usługi
    loop dwa raporty: traffic_daily, contact_events_daily
        loop strony (paginacja offsetem)
            I->>API: POST properties/{id}:runReport (limit, offset)
            Note over I,API: 429 albo 5xx → urllib3 Retry (2 s, 4 s, 8 s)
            API-->>I: rows + rowCount
        end
        Note over I: offset ≥ rowCount → koniec raportu, pusty raport → bez zapisu
        I->>I: to_rows: dimensionValues + metricValues → kolumny
        I->>BQ: load do _staging_{tabela} (WRITE_TRUNCATE)
        I->>BQ: zapytanie: tabela bez [start, end] + staging → {tabela} (WRITE_TRUNCATE_DATA)
    end
```

| Krok | Po co |
|---|---|
| 2–3 | bez klucza JSON: lokalnie impersonacja, w Actions Workload Identity Federation |
| 4–5 | `rowCount` mówi, ile wierszy ma cały raport — pętla wie, kiedy skończyć |
| 7–8 | podmiana zakresu jednym zapytaniem: powtórne uruchomienie nie dubluje wierszy |
