with source as (
    select * from {{ source('search_console', 'search_pages_daily') }}
),

renamed as (
    select
        report_date,
        page,
        clicks,
        impressions,
        position as avg_position,
        site,
        loaded_at
    from source
)

select * from renamed
