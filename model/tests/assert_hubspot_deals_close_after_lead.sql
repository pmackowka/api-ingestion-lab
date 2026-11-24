-- singular: deal zamyka się najwcześniej w dniu, w którym jego kontakt stał się leadem
select
    deals.deal_id,
    deals.close_date,
    contacts.lead_date
from {{ ref('stg_hubspot__deals') }} as deals
inner join {{ ref('stg_hubspot__contacts') }} as contacts
    using (contact_id)
where deals.close_date < contacts.lead_date
