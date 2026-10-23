-- Idempotent bootstrap used by .github/workflows/bootstrap.yml. Run: psql -v pw="$READER_PASSWORD" -f this
CREATE SCHEMA IF NOT EXISTS staging;
CREATE SCHEMA IF NOT EXISTS intermediate;
CREATE SCHEMA IF NOT EXISTS marts;

SELECT format('CREATE ROLE portfolio_reader LOGIN PASSWORD %L', :'pw')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'portfolio_reader') \gexec
SELECT format('ALTER ROLE portfolio_reader PASSWORD %L', :'pw') \gexec

SELECT format('GRANT CONNECT ON DATABASE %I TO portfolio_reader', current_database()) \gexec
GRANT USAGE ON SCHEMA public, staging, intermediate, marts TO portfolio_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA public, staging, intermediate, marts TO portfolio_reader;
ALTER DEFAULT PRIVILEGES IN SCHEMA public, staging, intermediate, marts GRANT SELECT ON TABLES TO portfolio_reader;
