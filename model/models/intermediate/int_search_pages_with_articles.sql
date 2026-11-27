with search_pages as (
    select * from {{ ref('stg_search_console__search_pages_daily') }}
),

sitemap_pages as (
    select * from {{ ref('stg_sitemap__pages') }}
),

normalized as (
    select
        *,
        regexp_replace(
            regexp_replace(
                regexp_replace(page, r'^https?://(www\.)?', 'https://'),
                r'^https://pmdata\.pl/blog/', 'https://pmdata.pl/artykuly/'
            ),
            r'([^/])$', r'\1/'
        ) as canonical_page
    from search_pages
)

select
    normalized.report_date,
    normalized.page,
    normalized.canonical_page,
    normalized.clicks,
    normalized.impressions,
    normalized.avg_position,
    sitemap_pages.page is not null as is_in_sitemap,
    sitemap_pages.section,
    sitemap_pages.headline,
    coalesce(sitemap_pages.is_article, false) as is_article,
    sitemap_pages.published_date,
    date_diff(normalized.report_date, sitemap_pages.published_date, day) as days_since_published
from normalized
left join sitemap_pages
    on normalized.canonical_page = sitemap_pages.page
