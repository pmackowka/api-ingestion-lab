-- singular: faktura powstaje po wygraniu deala, najwcześniej w dniu zamknięcia, na kwotę netto deala
select
    invoices.invoice_id,
    invoices.deal_key,
    deals.dealstage,
    deals.close_date,
    invoices.invoice_date,
    deals.amount as deal_amount,
    invoices.amount_untaxed
from {{ ref('stg_odoo__invoices') }} as invoices
inner join {{ ref('stg_hubspot__deals') }} as deals
    using (deal_key)
where deals.dealstage != 'closedwon'
    or invoices.invoice_date < deals.close_date
    or invoices.amount_untaxed != deals.amount
