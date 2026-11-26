with deals as (
    select * from {{ ref('stg_hubspot__deals') }}
),

invoices as (
    select * from {{ ref('int_invoices_converted_to_pln') }}
    where state = 'posted'
),

payments as (
    select
        invoice_id,
        sum(amount) as paid_amount
    from {{ ref('stg_odoo__payments') }}
    where state in ('paid', 'reconciled')
    group by invoice_id
),

joined as (
    select
        deals.deal_id,
        deals.deal_key,
        deals.contact_id,
        deals.dealstage,
        deals.dealstage = 'closedwon' as is_won,
        deals.amount,
        deals.close_date,
        invoices.invoice_id,
        invoices.invoice_date,
        invoices.amount_untaxed_pln as invoiced_amount_net,
        invoices.amount_total_pln as invoiced_amount_gross,
        coalesce(round(payments.paid_amount * invoices.exchange_rate, 2), 0) as paid_amount
    from deals
    left join invoices on deals.deal_key = invoices.deal_key
    left join payments on invoices.invoice_id = payments.invoice_id
)

select * from joined
