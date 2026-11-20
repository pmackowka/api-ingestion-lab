with source as (
    select * from {{ source('ga4', 'contact_events_daily') }}
),

renamed as (
    select
        report_date,
        session_source as source,
        session_medium as medium,
        concat(session_source, ' / ', session_medium) as source_medium,
        event_name,
        event_count,
        loaded_at
    from source
    where session_source != 'tagassistant.google.com'
)

select * from renamed
