with source as (
    select * from {{ source('sitemap', 'pages') }}
),

renamed as (
    select
        url as page,
        section,
        headline,
        date_published is not null as is_article,
        date(date_published, 'Europe/Warsaw') as published_date,
        date(date_modified, 'Europe/Warsaw') as modified_date,
        date(lastmod, 'Europe/Warsaw') as lastmod_date,
        loaded_at
    from source
)

select * from renamed
