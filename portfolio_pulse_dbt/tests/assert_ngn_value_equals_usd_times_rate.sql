-- Reconciliation: NGN value = USD value x that day's rate (rounding tolerance 1 kobo).
select position_key, market_value_usd, usd_ngn_rate, market_value_ngn
from {{ ref('mart_portfolio_value') }}
where abs(market_value_ngn - round(market_value_usd * usd_ngn_rate, 2)) > 0.01
