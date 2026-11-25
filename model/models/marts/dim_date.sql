with days as (
    select date_day
    from unnest(generate_date_array(date '2025-01-01', current_date('Europe/Warsaw'))) as date_day
)

select
    date_day,
    extract(year from date_day) as year,
    extract(month from date_day) as month,
    extract(isoweek from date_day) as iso_week,
    cast(format_date('%u', date_day) as int64) as iso_day_of_week,
    cast(format_date('%u', date_day) as int64) >= 6 as is_weekend
from days
