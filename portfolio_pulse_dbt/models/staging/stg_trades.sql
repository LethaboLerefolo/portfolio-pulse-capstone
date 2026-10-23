-- Staging: types and cleans the hand-typed Google Sheet trade log.
--  * Sheets sends text -> cast to date / numeric (stripping $ and thousands commas).
--  * No natural key exists (you can legitimately buy the same lot twice in a day),
--    so trade_id = hash of the row's content + an occurrence counter for exact twins.
with typed as (

    select
        trim(trade_date)                                                         as trade_date_raw,
        upper(trim(ticker))                                                      as ticker,
        nullif(regexp_replace(shares_bought,  '[^0-9.\-]', '', 'g'), '')::numeric as shares_bought,
        nullif(regexp_replace(price_paid_usd, '[^0-9.\-]', '', 'g'), '')::numeric as price_paid_usd,
        _airbyte_raw_id,
        _airbyte_extracted_at
    from {{ source('raw', 'trade_log') }}
    where trade_date is not null
      and trim(trade_date) <> ''
      and ticker is not null
      and trim(ticker) <> ''

),

numbered as (

    select
        *,
        row_number() over (
            partition by trade_date_raw, ticker, shares_bought, price_paid_usd
            order by _airbyte_raw_id
        ) as occurrence
    from typed

)

select
    md5(concat_ws('|', trade_date_raw, ticker, shares_bought::text, price_paid_usd::text, occurrence::text)) as trade_id,
    trade_date_raw::date                       as trade_date,
    ticker,
    shares_bought,
    price_paid_usd,
    round(shares_bought * price_paid_usd, 2)   as cost_usd,
    _airbyte_extracted_at                      as loaded_at
from numbered
