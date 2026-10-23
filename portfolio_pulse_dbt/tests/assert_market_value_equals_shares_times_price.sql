-- Reconciliation: market value must equal shares x close (to the cent).
select position_key, ticker, position_date, market_value_usd, shares_held, close_price
from {{ ref('mart_portfolio_value') }}
where abs(market_value_usd - round(shares_held * close_price, 2)) > 0.01
