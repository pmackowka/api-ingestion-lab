# Diagram sekwencji UML: jedno uruchomienie ingestu pogody

Kto wywołuje kogo w jednym przebiegu `weather/ingest.py`. Wspólny zapis do BigQuery (staging → podmiana zakresu): [README główne](../README.md).

```mermaid
sequenceDiagram
    autonumber
    participant GH as GitHub Actions (pipeline.yml)
    participant I as weather/ingest.py
    participant API as Open-Meteo Archive API
    participant BQ as BigQuery raw_weather

    GH->>I: --lookback-days 7 (cron 1:41)
    I->>API: GET /v1/archive — wszystkie lokalizacje jednym zapytaniem
    alt sieć, timeout albo 5xx
        API-->>I: błąd przejściowy → ponowienie po 2 s, potem 4 s (maks. 3 próby)
    else 4xx
        API-->>I: błąd z polem reason → przerwanie bez ponowień
    end
    API-->>I: dane kolumnowe na lokalizację (null dla dni jeszcze niepoliczonych)
    I->>I: to_rows: lokalizacja × dzień, kontrola liczby lokalizacji
    I->>BQ: load do _staging_daily_weather (WRITE_TRUNCATE)
    I->>BQ: zapytanie: tabela bez [start, end] + staging → daily_weather (WRITE_TRUNCATE_DATA)
```

| Krok | Po co |
|---|---|
| 1 | ostatnie dni są wstępne, więc tydzień wstecz jest przeliczany przy każdym uruchomieniu |
| 2 | pięć miast jednym GET-em zamiast pięciu |
| 3–4 | ponawiamy tylko to, co może się udać za chwilę |
| 7–8 | podmiana zakresu jednym zapytaniem: powtórne uruchomienie nie dubluje wierszy |
