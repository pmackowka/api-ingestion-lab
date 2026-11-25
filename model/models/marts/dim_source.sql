with ga4_sources as (
    select distinct source, medium
    from {{ ref('stg_ga4__traffic_daily') }}

    union distinct

    select distinct source, medium
    from {{ ref('stg_ga4__contact_events_daily') }}
),

hubspot_sources as (
    select distinct
        split(lead_source, ' / ')[safe_offset(0)] as source,
        split(lead_source, ' / ')[safe_offset(1)] as medium
    from {{ ref('stg_hubspot__contacts') }}
    where not is_test_lead
),

all_sources as (
    select source, medium from ga4_sources
    union distinct
    select source, medium from hubspot_sources
),

cleaned as (
    select
        all_sources.source,
        all_sources.medium,
        coalesce(aliases.source_clean, all_sources.source) as source_clean
    from all_sources
    left join {{ ref('source_aliases') }} as aliases
        using (source)
)

select
    concat(source, ' / ', medium) as source_medium,
    source,
    medium,
    source_clean,
    case
        when source = '(direct)' and medium = '(none)' then 'Direct'
        when medium in ('cpc', 'ppc', 'paid') then 'Paid Search'
        when medium = 'organic' and source_clean in ('google', 'bing', 'duckduckgo', 'yahoo') then 'Organic Search'
        when medium = 'ai-assistant' or source_clean in ('chatgpt.com', 'perplexity.ai', 'gemini.google.com') then 'AI Assistant'
        when source_clean in ('cv', 'github', 'piotrm.netlify.app') then 'Owned'
        when medium = 'social' or source_clean in ('linkedin', 'facebook', 'instagram', 'x.com', 'twitter') then 'Organic Social'
        when medium = 'referral' then 'Referral'
        else 'Unassigned'
    end as channel
from cleaned
