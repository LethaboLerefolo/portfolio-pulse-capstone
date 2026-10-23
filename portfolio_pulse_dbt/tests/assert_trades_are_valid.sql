-- Trades must be in the past (not future-dated typos) and have positive size and price.
select trade_id, trade_date, ticker, shares_bought, price_paid_usd
from {{ ref('stg_trades') }}
where trade_date > current_date
   or shares_bought  <= 0
   or price_paid_usd <= 0
