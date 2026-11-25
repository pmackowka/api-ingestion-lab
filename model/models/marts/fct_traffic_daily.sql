with contact_clicks as (
    select
        report_date,
        source_medium,
        sum(event_count) as contact_clicks
    from {{ ref('stg_ga4__contact_events_daily') }}
    group by report_date, source_medium
)

select
    traffic.report_date as date_day,
    traffic.source_medium,
    traffic.sessions,
    traffic.engaged_sessions,
    coalesce(contact_clicks.contact_clicks, 0) as contact_clicks
from {{ ref('stg_ga4__traffic_daily') }} as traffic
left join contact_clicks
    using (report_date, source_medium)
