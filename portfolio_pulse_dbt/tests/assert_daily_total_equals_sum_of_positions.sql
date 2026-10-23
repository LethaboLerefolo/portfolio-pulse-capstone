-- Reconciliation: the headline daily total (USD and NGN) must equal the sum of its positions.
with from_positions as (
    select position_date,
           sum(market_value_usd) as usd,
           sum(market_value_ngn) as ngn
    from {{ ref('mart_portfolio_value') }}
    group by position_date
)
select d.position_date, d.total_market_value_usd, p.usd, d.total_market_value_ngn, p.ngn
from {{ ref('mart_portfolio_daily') }} d
join from_positions p using (position_date)
where abs(d.total_market_value_usd - p.usd) > 0.01
   or abs(d.total_market_value_ngn - p.ngn) > 0.01
