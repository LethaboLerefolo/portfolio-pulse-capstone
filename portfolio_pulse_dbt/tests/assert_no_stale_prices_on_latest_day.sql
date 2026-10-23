{{ config(severity='warn') }}
-- WARN (not fail): on the latest day a position is valued with a carried-forward price,
-- i.e. Yahoo had no fresh close for that ticker. Worth knowing; not worth a red pipeline.
select ticker, position_date
from {{ ref('mart_portfolio_value') }}
where position_date = (select max(position_date) from {{ ref('mart_portfolio_value') }})
  and is_stale_price
