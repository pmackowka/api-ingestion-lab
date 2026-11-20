with source as (
    select * from {{ source('ga4', 'traffic_daily') }}
),

renamed as (
    select
        report_date,
        session_source as source,
        session_medium as medium,
        concat(session_source, ' / ', session_medium) as source_medium,
        sessions,
        total_users as users,
        engaged_sessions,
        loaded_at
    from source
    where session_source != 'tagassistant.google.com'
)

select * from renamed
