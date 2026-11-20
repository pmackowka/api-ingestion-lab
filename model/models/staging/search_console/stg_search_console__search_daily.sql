with source as (
    select * from {{ source('search_console', 'search_daily') }}
),

renamed as (
    select
        report_date,
        country,
        device,
        clicks,
        impressions,
        position as avg_position,
        site,
        loaded_at
    from source
)

select * from renamed
