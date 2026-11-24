-- singular: strony liczone są osobno per URL, więc ich dzienne sumy nie mogą być niższe niż sumy usługi
with daily as (
    select
        report_date,
        sum(clicks) as clicks,
        sum(impressions) as impressions
    from {{ ref('stg_search_console__search_daily') }}
    group by report_date
),

pages as (
    select
        report_date,
        sum(clicks) as clicks,
        sum(impressions) as impressions
    from {{ ref('stg_search_console__search_pages_daily') }}
    group by report_date
)

select
    report_date,
    daily.clicks as daily_clicks,
    pages.clicks as pages_clicks,
    daily.impressions as daily_impressions,
    pages.impressions as pages_impressions
from daily
full join pages using (report_date)
where daily.report_date is null
    or pages.report_date is null
    or pages.clicks < daily.clicks
    or pages.impressions < daily.impressions
