-- singular: NBP nie publikuje tabeli A w święta państwowe, więc kurs w dniu święta oznacza błąd w jednym ze źródeł
select
    rates.effective_date,
    holidays.holiday_name,
    count(*) as currencies
from {{ ref('stg_nbp__exchange_rates_a') }} as rates
inner join {{ ref('stg_holidays__public_holidays') }} as holidays
    on rates.effective_date = holidays.holiday_date
group by rates.effective_date, holidays.holiday_name
