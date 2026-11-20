with source as (
    select * from {{ source('nbp', 'exchange_rates_a') }}
),

renamed as (
    select
        effective_date,
        currency_code,
        currency_name,
        mid,
        table_no,
        loaded_at
    from source
)

select * from renamed
