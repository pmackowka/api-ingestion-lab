with contacts as (
    select * from {{ ref('stg_hubspot__contacts') }}
),

deals as (
    select
        contact_id,
        count(*) as deals,
        countif(is_won) as won_deals,
        sum(if(is_won, amount, 0)) as won_amount,
        sum(invoiced_amount_net) as invoiced_amount_net,
        sum(invoiced_amount_gross) as invoiced_amount_gross,
        sum(paid_amount) as paid_amount
    from {{ ref('int_deal_revenue') }}
    group by contact_id
)

select
    contacts.contact_id,
    contacts.lead_date,
    contacts.lead_source as source_medium,
    contacts.lead_event,
    contacts.is_test_lead,
    coalesce(deals.deals, 0) as deals,
    coalesce(deals.won_deals, 0) as won_deals,
    coalesce(deals.won_amount, 0) as won_amount,
    coalesce(deals.invoiced_amount_net, 0) as invoiced_amount_net,
    coalesce(deals.invoiced_amount_gross, 0) as invoiced_amount_gross,
    coalesce(deals.paid_amount, 0) as paid_amount
from contacts
left join deals
    using (contact_id)
