with invoices as (
    select * from {{ ref('stg_odoo__invoices') }}
),

rates as (
    select * from {{ ref('stg_nbp__exchange_rates_a') }}
),

invoice_rates as (
    select
        invoices.invoice_id,
        array_agg(
            struct(rates.effective_date, rates.mid)
            order by rates.effective_date desc
            limit 1
        )[safe_offset(0)] as rate
    from invoices
    inner join rates
        on invoices.currency = rates.currency_code
        and rates.effective_date < invoices.invoice_date
    group by invoices.invoice_id
),

with_rate as (
    select
        invoices.*,
        if(invoices.currency = 'PLN', 1, invoice_rates.rate.mid) as exchange_rate,
        invoice_rates.rate.effective_date as exchange_rate_date
    from invoices
    left join invoice_rates
        using (invoice_id)
),

converted as (
    select
        *,
        round(amount_untaxed * exchange_rate, 2) as amount_untaxed_pln,
        round(amount_tax * exchange_rate, 2) as amount_tax_pln
    from with_rate
)

select
    *,
    amount_untaxed_pln + amount_tax_pln as amount_total_pln
from converted
