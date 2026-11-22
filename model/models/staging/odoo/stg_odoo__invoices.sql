with source as (
    select * from {{ source('odoo', 'invoices') }}
),

renamed as (
    select
        invoice_id,
        invoice_number,
        deal_key,
        partner_id,
        partner_name,
        invoice_date,
        due_date,
        currency,
        amount_untaxed,
        amount_tax,
        amount_total,
        state,
        payment_state,
        created_at,
        updated_at,
        loaded_at
    from source
)

select * from renamed
