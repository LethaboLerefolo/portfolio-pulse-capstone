-- Every ticker in the trade log must exist in stock_prices.
-- Catches a typo in the Google Sheet (e.g. "APPL") that would otherwise make the
-- position silently disappear from the portfolio.
select distinct t.ticker
from {{ ref('stg_trades') }} t
left join (select distinct ticker from {{ ref('stg_stock_prices') }}) p
       on p.ticker = t.ticker
where p.ticker is null
