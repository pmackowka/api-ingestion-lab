# Diagram sekwencji UML: jedno uruchomienie ingestu Search Console

Kto wywołuje kogo w jednym przebiegu `search_console/ingest.py`. Wspólny zapis do BigQuery (staging → podmiana zakresu): [README główne](../README.md).

```mermaid
sequenceDiagram
    autonumber
    participant GH as GitHub Actions (pipeline.yml)
    participant I as search_console/ingest.py
    participant AUTH as ADC (WIF → ingest-runner)
    participant API as Search Console API
    participant BQ as BigQuery raw_search_console

    GH->>I: --site, --lookback-days 7 (cron 1:41)
    I->>AUTH: token z zakresem webmasters.readonly
    AUTH-->>I: krótkotrwały token konta usługi
    loop dwa raporty: search_daily, search_pages_daily
        loop strony (paginacja startRow)
            I->>API: POST sites/{site}/searchAnalytics/query (rowLimit 25 000, startRow, dataState all)
            Note over I,API: 429 albo 5xx → urllib3 Retry (2 s, 4 s, 8 s)
            API-->>I: rows
        end
        Note over I: strona krótsza niż rowLimit → koniec raportu
        I->>I: to_rows: keys → kolumny wymiarów
        I->>BQ: load do _staging_{tabela} (WRITE_TRUNCATE)
        I->>BQ: zapytanie: tabela bez [start, end] + staging → {tabela} (WRITE_TRUNCATE_DATA)
    end
```

| Krok | Po co |
|---|---|
| 2–3 | bez klucza JSON: lokalnie impersonacja, w Actions Workload Identity Federation |
| 4–5 | API nie podaje liczby wierszy — koniec poznajemy po krótszej stronie |
| 4 | `dataState: all` bierze też wstępne dane z ostatnich dni; poprawi je kolejny lookback |
| 7–8 | podmiana zakresu jednym zapytaniem: powtórne uruchomienie nie dubluje wierszy |
