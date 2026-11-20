with source as (
    select * from {{ source('weather', 'daily_weather') }}
),

renamed as (
    select
        weather_date,
        location_id,
        temperature_2m_mean,
        precipitation_sum,
        weather_code,
        timezone,
        loaded_at
    from source
)

select * from renamed
