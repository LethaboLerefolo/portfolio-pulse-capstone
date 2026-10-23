-- Staging: 1:1 clean copy of raw.stock_prices. Rename, type, filter junk. No business logic.
select
    md5(upper(trim(ticker)) || '|' || price_date::text)   as price_key,
    upper(trim(ticker))                                   as ticker,
    price_date::date                                      as price_date,
    close_price::numeric(14, 4)                           as close_price,
    volume,
    loaded_at
from {{ source('raw', 'stock_prices') }}
where close_price is not null
  and close_price > 0
