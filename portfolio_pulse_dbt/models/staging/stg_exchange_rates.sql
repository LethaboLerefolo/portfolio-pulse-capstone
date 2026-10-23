-- Staging: clean USD->NGN observations (one row per Airbyte sync).
-- "updatedAt" is camelCase in the Airbyte table, so it must be double-quoted.
-- The ::text / ::timestamptz casts make this model work whether Airbyte typed the
-- column as text or as a timestamp / boolean.
select
    _airbyte_raw_id                                                        as fx_record_id,
    upper("from")                                                          as base_currency,
    upper("to")                                                            as quote_currency,
    rate::numeric(18, 6)                                                   as usd_ngn_rate,
    coalesce("updatedAt"::text::timestamptz, _airbyte_extracted_at)        as rate_timestamp,
    (coalesce("updatedAt"::text::timestamptz, _airbyte_extracted_at)
        at time zone 'UTC')::date                                          as rate_date,
    _airbyte_extracted_at                                                  as loaded_at
from {{ source('raw', 'exchange_rate') }}
where rate is not null
  and rate > 0
  and upper("from") = 'USD'
  and upper("to")   = 'NGN'
  and coalesce(lower(success::text), 'true') in ('true', 't')
