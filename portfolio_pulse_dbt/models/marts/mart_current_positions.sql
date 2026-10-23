-- MART: the latest snapshot per position - feeds the allocation donut and the
-- gain/loss-by-position bar chart.
with latest as (

    select *
    from {{ ref('mart_portfolio_value') }}
    where position_date = (select max(position_date) from {{ ref('mart_portfolio_value') }})

)

select
    ticker,
    position_date                                                   as as_of_date,
    shares_held,
    round(cost_basis_usd / nullif(shares_held, 0), 2)               as avg_cost_usd,
    close_price,
    market_value_usd,
    cost_basis_usd,
    unrealized_gain_loss_usd,
    unrealized_gain_loss_pct,
    market_value_ngn,
    cost_basis_ngn,
    unrealized_gain_loss_ngn,
    usd_ngn_rate,
    round(market_value_usd / sum(market_value_usd) over () * 100, 2) as allocation_pct
from latest
