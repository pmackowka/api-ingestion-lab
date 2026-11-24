-- singular: wpłaty za fakturę nie przekraczają jej kwoty brutto i nie wyprzedzają daty wystawienia
with payments_per_invoice as (
    select
        invoice_id,
        sum(amount) as paid_amount,
        min(payment_date) as first_payment_date
    from {{ ref('stg_odoo__payments') }}
    where invoice_id is not null
    group by invoice_id
)

select
    invoices.invoice_id,
    invoices.invoice_date,
    payments_per_invoice.first_payment_date,
    invoices.amount_total,
    payments_per_invoice.paid_amount
from payments_per_invoice
inner join {{ ref('stg_odoo__invoices') }} as invoices
    using (invoice_id)
where payments_per_invoice.paid_amount > invoices.amount_total
    or payments_per_invoice.first_payment_date < invoices.invoice_date
