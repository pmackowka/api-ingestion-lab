with days as (
    select date_day
    from unnest(generate_date_array(date '2025-01-01', current_date('Europe/Warsaw'))) as date_day
),

weather as (
    select
        weather_date,
        avg(temperature_2m_mean) as avg_temperature,
        countif(precipitation_sum >= 1) as rainy_cities
    from {{ ref('stg_weather__daily_weather') }}
    group by weather_date
),

holidays as (
    select holiday_date
    from {{ ref('stg_holidays__public_holidays') }}
)

select
    days.date_day,
    extract(year from days.date_day) as year,
    extract(month from days.date_day) as month,
    extract(isoweek from days.date_day) as iso_week,
    cast(format_date('%u', days.date_day) as int64) as iso_day_of_week,
    cast(format_date('%u', days.date_day) as int64) >= 6 as is_weekend,
    holidays.holiday_date is not null as is_holiday,
    weather.rainy_cities >= 3 as is_rainy_day,
    case
        when weather.avg_temperature < 0 then 'freezing'
        when weather.avg_temperature < 15 then 'cold'
        when weather.avg_temperature < 25 then 'warm'
        when weather.avg_temperature >= 25 then 'hot'
    end as temperature_band
from days
left join weather
    on days.date_day = weather.weather_date
left join holidays
    on days.date_day = holidays.holiday_date
