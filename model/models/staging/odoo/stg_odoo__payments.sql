with source as (
    select * from {{ source('odoo', 'payments') }}
),

renamed as (
    select
        payment_id,
        payment_number,
        invoice_id,
        payment_date,
        amount,
        currency,
        state,
        created_at,
        updated_at,
        loaded_at
    from source
)

select * from renamed
