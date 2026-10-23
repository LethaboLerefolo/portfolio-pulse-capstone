-- One row per (ticker, trading day) from the ticker's first purchase onward.
-- Holdings are cumulative buys; a missing close is forward-filled and flagged is_stale_price.
-- A trading day is any date with at least one price, so weekend buys count from the next trading day.
with trading_days as (

    select distinct price_date as position_date
    from {{ ref('stg_stock_prices') }}

),

first_buy as (

    select ticker, min(trade_date) as first_trade_date
    from {{ ref('stg_trades') }}
    group by ticker

),

spine as (

    select d.position_date, f.ticker
    from trading_days d
    join first_buy f
      on d.position_date >= f.first_trade_date

),

joined as (

    -- exact-date price where one exists; null where this ticker has no row that day
    select
        s.position_date,
        s.ticker,
        p.close_price,
        p.price_date,
        -- running count of non-null prices: every row after a real price shares its group number
        count(p.close_price) over (partition by s.ticker order by s.position_date) as fill_group
    from spine s
    left join {{ ref('stg_stock_prices') }} p
           on p.ticker     = s.ticker
          and p.price_date = s.position_date

),

priced as (

    -- forward-fill (carry the last known close) in ONE linear pass: within a fill_group the
    -- only non-null value is the real price on its first row, so max() spreads it down.
    select
        position_date,
        ticker,
        max(close_price) over (partition by ticker, fill_group) as close_price,
        max(price_date)  over (partition by ticker, fill_group) as price_date_used
    from joined

)

select
    pr.position_date,
    pr.ticker,
    sum(t.shares_bought)                     as shares_held,
    sum(t.cost_usd)                          as cost_basis_usd,
    sum(t.cost_ngn)                          as cost_basis_ngn,
    pr.close_price,
    pr.price_date_used,
    (pr.price_date_used < pr.position_date)  as is_stale_price
from priced pr
join {{ ref('int_trades_enriched') }} t
  on t.ticker = pr.ticker
 and t.trade_date <= pr.position_date
group by pr.position_date, pr.ticker, pr.close_price, pr.price_date_used
