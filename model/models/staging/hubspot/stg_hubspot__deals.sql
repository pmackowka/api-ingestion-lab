with source as (
    select * from {{ source('hubspot', 'deals') }}
),

renamed as (
    select
        deal_id,
        deal_key,
        contact_id,
        dealname,
        pipeline,
        dealstage,
        amount,
        date(closedate, 'Europe/Warsaw') as close_date,
        created_at,
        updated_at,
        loaded_at
    from source
)

select * from renamed
