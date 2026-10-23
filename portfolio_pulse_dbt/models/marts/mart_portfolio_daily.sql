-- MART: the headline answer - "what is my portfolio worth, in USD and NGN, over time?"
-- Grain: one row per trading day.
with daily as (

    select
        position_date,
        count(*)                                  as positions_held,
        count(*) filter (where is_stale_price)    as positions_with_stale_price,
        sum(market_value_usd)                     as total_market_value_usd,
        sum(cost_basis_usd)                       as total_cost_basis_usd,
        sum(market_value_ngn)                     as total_market_value_ngn,
        sum(cost_basis_ngn)                       as total_cost_basis_ngn,
        max(usd_ngn_rate)                         as usd_ngn_rate,
        max(rate_basis)                           as rate_basis
    from {{ ref('mart_portfolio_value') }}
    group by position_date

)

select
    position_date,
    positions_held,
    positions_with_stale_price,
    total_market_value_usd,
    total_cost_basis_usd,
    total_market_value_usd - total_cost_basis_usd                                   as unrealized_gain_loss_usd,
    round((total_market_value_usd - total_cost_basis_usd)
          / nullif(total_cost_basis_usd, 0) * 100, 2)                               as unrealized_gain_loss_pct,
    usd_ngn_rate,
    rate_basis,
    total_market_value_ngn,
    total_cost_basis_ngn,
    total_market_value_ngn - total_cost_basis_ngn                                   as unrealized_gain_loss_ngn,
    round((total_market_value_ngn - total_cost_basis_ngn)
          / nullif(total_cost_basis_ngn, 0) * 100, 2)                               as unrealized_gain_loss_ngn_pct,
    total_market_value_usd
      - lag(total_market_value_usd) over (order by position_date)                   as day_change_usd
from daily
