-- Read-only role for Metabase and the course facilitator.
-- Run once in the Neon SQL editor as the project owner. Replace the password and do NOT commit the real one.

CREATE ROLE portfolio_reader LOGIN PASSWORD 'CHANGE_ME_before_running';

GRANT CONNECT ON DATABASE neondb TO portfolio_reader;   -- replace neondb with your database name

GRANT USAGE ON SCHEMA public, staging, intermediate, marts TO portfolio_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA public, staging, intermediate, marts TO portfolio_reader;

-- Tables dbt creates in future runs are readable too (dbt drops/recreates relations).
-- Run as the SAME role that dbt connects as:
ALTER DEFAULT PRIVILEGES IN SCHEMA staging, intermediate, marts GRANT SELECT ON TABLES TO portfolio_reader;

-- Sanity check from the reader's session: this must succeed ...
--   SELECT count(*) FROM marts.mart_portfolio_daily;
-- ... and this must FAIL with "permission denied":
--   DELETE FROM public.stock_prices;
