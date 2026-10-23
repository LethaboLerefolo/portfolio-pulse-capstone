-- Each trade with its cost in NGN at the exchange rate on the day it was made.
-- Cost basis in NGN must use the purchase-date rate (not today's), otherwise
-- NGN gain/loss would hide the currency effect - the whole point of reporting in NGN.
select
    t.trade_id,
    t.trade_date,
    t.ticker,
    t.shares_bought,
    t.price_paid_usd,
    t.cost_usd,
    fx.usd_ngn_rate                              as usd_ngn_rate_at_trade,
    round(t.cost_usd * fx.usd_ngn_rate, 2)       as cost_ngn
from {{ ref('stg_trades') }} t
left join {{ ref('int_fx_daily') }} fx
       on fx.date_day = t.trade_date
