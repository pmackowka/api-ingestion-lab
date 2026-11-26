with source as (
    select * from {{ source('holidays', 'public_holidays') }}
),

renamed as (
    select
        holiday_date,
        country_code,
        name as holiday_name,
        is_national,
        loaded_at
    from source
)

select * from renamed
