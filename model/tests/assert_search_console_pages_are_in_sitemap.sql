-- singular: w ostatnich 7 dniach danych Google wyświetla tylko adresy z sitemapy; inny wariant (http, bez końcowego /, stara ścieżka) oznacza brak przekierowania 301 albo stronę spoza sitemapy
with pages as (
    select * from {{ ref('stg_search_console__search_pages_daily') }}
),

last_days as (
    select *
    from pages
    where report_date > (select date_sub(max(report_date), interval 7 day) from pages)
)

select
    last_days.page,
    min(last_days.report_date) as first_seen,
    max(last_days.report_date) as last_seen,
    sum(last_days.impressions) as impressions
from last_days
left join {{ ref('stg_sitemap__pages') }} as sitemap
    using (page)
where sitemap.page is null
group by last_days.page
