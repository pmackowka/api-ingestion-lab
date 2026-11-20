with source as (
    select * from {{ source('hubspot', 'contacts') }}
),

renamed as (
    select
        contact_id,
        email,
        lead_source,
        lead_event,
        lead_date,
        lead_source is null
            or starts_with(lead_source, 'tagassistant.google.com') as is_test_lead,
        created_at,
        updated_at,
        loaded_at
    from source
)

select * from renamed
