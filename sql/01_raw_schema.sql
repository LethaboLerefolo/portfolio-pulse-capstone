-- Raw layer contract: the columns dbt expects. Not needed in production, since
-- stock_prices comes from ingest_stock_prices.py and trade_log / exchange_rate from Airbyte.
-- Used by the Python fallbacks and by tests/local_e2e.py.

CREATE TABLE IF NOT EXISTS stock_prices (
    ticker       VARCHAR(12)   NOT NULL,
    price_date   DATE          NOT NULL,
    close_price  NUMERIC(14,4) NOT NULL CHECK (close_price > 0),
    volume       BIGINT,
    loaded_at    TIMESTAMPTZ   NOT NULL DEFAULT now(),
    PRIMARY KEY (ticker, price_date)
);

-- Google Sheets source delivers every cell as text; dbt does the typing.
CREATE TABLE IF NOT EXISTS trade_log (
    _airbyte_raw_id         VARCHAR(36)  NOT NULL,
    _airbyte_extracted_at   TIMESTAMPTZ  NOT NULL,
    _airbyte_meta           JSONB,
    _airbyte_generation_id  BIGINT,
    trade_date              TEXT,
    ticker                  TEXT,
    shares_bought           TEXT,
    price_paid_usd          TEXT
);

-- Column names (incl. camelCase "updatedAt") mirror the NaijaShop exchange_rate table.
CREATE TABLE IF NOT EXISTS exchange_rate (
    _airbyte_raw_id         VARCHAR(36)  NOT NULL,
    _airbyte_extracted_at   TIMESTAMPTZ  NOT NULL,
    _airbyte_meta           JSONB,
    _airbyte_generation_id  BIGINT,
    "from"                  VARCHAR(8),
    "to"                    VARCHAR(8),
    rate                    DOUBLE PRECISION,
    amount                  DOUBLE PRECISION,
    result                  DOUBLE PRECISION,
    success                 BOOLEAN,
    "updatedAt"             TIMESTAMPTZ
);
