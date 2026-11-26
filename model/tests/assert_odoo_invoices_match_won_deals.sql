-- singular: faktura powstaje po wygraniu deala, najwcześniej w dniu zamknięcia, na kwotę netto deala przeliczoną kursem faktury (z dokładnością do zaokrąglenia do grosza albo centa)
select
    invoices.invoice_id,
    invoices.deal_key,
    deals.dealstage,
    deals.close_date,
    invoices.invoice_date,
    deals.amount as deal_amount,
    invoices.currency,
    invoices.exchange_rate,
    invoices.amount_untaxed
from {{ ref('int_invoices_converted_to_pln') }} as invoices
inner join {{ ref('stg_hubspot__deals') }} as deals
    using (deal_key)
where deals.dealstage != 'closedwon'
    or invoices.invoice_date < deals.close_date
    or abs(invoices.amount_untaxed - deals.amount / invoices.exchange_rate) > 0.005
