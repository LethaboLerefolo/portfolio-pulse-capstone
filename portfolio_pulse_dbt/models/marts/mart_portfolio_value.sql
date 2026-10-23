-- MART (fact): value and unrealised gain/loss of every position on every trading day,
-- in USD and NGN. This is the atomic table the other marts and the dashboard build on.
with positions as (

    select
        p.*,
        round(p.shares_held * p.close_price, 2) as market_value_usd
    from {{ ref('int_daily_positions') }} p

)

select
    md5(pos.ticker || '|' || pos.position_date::text)                       as position_key,
    pos.position_date,
    pos.ticker,
    pos.shares_held,
    pos.close_price,
    pos.market_value_usd,
    pos.cost_basis_usd,
    pos.market_value_usd - pos.cost_basis_usd                               as unrealized_gain_loss_usd,
    round((pos.market_value_usd - pos.cost_basis_usd)
          / nullif(pos.cost_basis_usd, 0) * 100, 2)                         as unrealized_gain_loss_pct,
    fx.usd_ngn_rate,
    fx.rate_basis,
    round(pos.market_value_usd * fx.usd_ngn_rate, 2)                        as market_value_ngn,
    pos.cost_basis_ngn,
    round(pos.market_value_usd * fx.usd_ngn_rate, 2) - pos.cost_basis_ngn   as unrealized_gain_loss_ngn,
    pos.is_stale_price
from positions pos
left join {{ ref('int_fx_daily') }} fx
       on fx.date_day = pos.position_date
