-- PortfolioPulse dashboard: paste each query into Metabase (New > SQL query), save, add to dashboard.
-- Connect Metabase with the READ-ONLY role (sql/02_readonly_metabase_user.sql), schema: marts.

-- 1. Portfolio value over time (line chart: x=position_date, y=USD and NGN as two series/cards)
select position_date,
       total_market_value_usd,
       total_market_value_ngn,
       total_cost_basis_usd
from marts.mart_portfolio_daily
order by position_date;

-- 2. Current allocation by ticker (pie / bar: dimension=ticker, metric=market_value_usd)
select ticker, market_value_usd, allocation_pct
from marts.mart_current_positions
order by market_value_usd desc;

-- 3. Unrealised gain/loss per ticker, USD (bar chart, one bar per ticker)
select ticker, unrealized_gain_loss_usd, unrealized_gain_loss_pct
from marts.mart_current_positions
order by unrealized_gain_loss_usd desc;

-- 4. USD/NGN exchange rate over time (line chart) - shows rate_basis so carried-forward days are visible
select position_date, usd_ngn_rate, rate_basis
from marts.mart_portfolio_daily
order by position_date;

-- Bonus KPI tiles (number cards)
select total_market_value_usd, total_market_value_ngn, unrealized_gain_loss_usd, unrealized_gain_loss_pct, day_change_usd
from marts.mart_portfolio_daily
order by position_date desc
limit 1;
