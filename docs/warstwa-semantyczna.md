# Warstwa semantyczna: dbt Semantic Layer a Apache Ossie

To nie są konkurenci. dbt Semantic Layer to format definicji metryk i silnik, który je **liczy** (MetricFlow generuje SQL). Apache Ossie, dawniej Open Semantic Interchange (OSI), to otwarty format do **przenoszenia** definicji metryk między platformami: sam niczego nie liczy, a konwertery tłumaczą go na format docelowego narzędzia. Stan sprawdzony 2026-11-28.

| | dbt Semantic Layer | Apache Ossie |
|---|---|---|
| Co to jest | specyfikacja YAML w dbt + silnik MetricFlow (SQL z definicji) + płatny serwis z API | otwarta specyfikacja YAML do wymiany modeli semantycznych, bez silnika |
| Kto stoi za projektem | dbt Labs; MetricFlow pochodzi z firmy Transform (przejęta w lutym 2023), od października 2025 na licencji Apache 2.0 | koalicja ponad 50 firm (m.in. Snowflake, Salesforce, Databricks, dbt Labs); w Apache Incubator od połowy 2026 |
| Czy liczy metryki | tak: `mf query` lokalnie, API w planie Starter i wyżej | nie; liczy platforma, do której trafi przekonwertowany model |
| Narzędzia | dbt + hurtownia (BigQuery, Snowflake, Databricks…); Power BI, Tableau, Google Sheets przez API; agenci AI przez `dbt-mcp` | konwertery m.in.: dbt MetricFlow, Power BI (TMSL/TMDL), Tableau (`.tds`), Salesforce/Tableau Next, Snowflake Cortex Analyst; w repo 29 projektów konwerterów |
| Kontekst dla AI | `description`, `label` | osobny blok `ai_context` z instrukcjami dla LLM |
| Dojrzałość | produkcyjnie od 2023 | wersja `0.3.0.dev0`, projekt w inkubacji |
| Kiedy wybrać | transformacje w dbt i jedna definicja metryk dla narzędzi i zapytań | kilka platform (np. Snowflake, Tableau, Power BI): metryki definiujesz raz, a każda platforma liczy je u siebie |
| W tym repo | działa: metryki w `model/models/marts/_marts__models.yml`, zapytania przez `mf` | tylko jako eksport: `dbt parse` → `ossie-dbt msi-to-ossie` → konwerter docelowego narzędzia |

Źródła:
- [architektura dbt Semantic Layer](https://github.com/dbt-labs/docs.getdbt.com/blob/current/website/docs/docs/use-dbt-semantic-layer/sl-architecture.md)
- [przejęcie Transform](https://www.getdbt.com/blog/dbt-labs-signs-definitive-agreement-to-acquire-transform-accelerating-development-of-the-dbt-semantic-layer)
- [MetricFlow na Apache 2.0](https://www.getdbt.com/blog/dbt-labs-affirms-commitment-to-open-semantic-interchange-by-open-sourcing-metricflow)
- [Apache Ossie](https://ossie.apache.org/)
- [Ossie w Apache Incubator](https://ossie.apache.org/updates/ossie-enters-apache-incubator/)
- [konwertery Ossie](https://github.com/apache/ossie-converters)
