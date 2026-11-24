-- singular: każde kliknięcie w kontakt należy do sesji, więc ma wiersz ruchu o tym samym dniu, source i medium
select
    contact_events.report_date,
    contact_events.source,
    contact_events.medium
from {{ ref('stg_ga4__contact_events_daily') }} as contact_events
left join {{ ref('stg_ga4__traffic_daily') }} as traffic
    using (report_date, source, medium)
where traffic.report_date is null
