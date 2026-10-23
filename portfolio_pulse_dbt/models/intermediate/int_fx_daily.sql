-- One USD->NGN rate for every calendar day from the first trade until today.
-- rate_basis: observed (own rate that day), carried_forward (latest earlier rate),
-- backfilled (before the first observation, so the earliest rate is used).
with observed as (

    select
        rate_date,
        (array_agg(usd_ngn_rate order by rate_timestamp desc))[1] as usd_ngn_rate
    from {{ ref('stg_exchange_rates') }}
    group by rate_date

),

calendar as (

    select d::date as date_day
    from generate_series(
        (select min(trade_date) from {{ ref('stg_trades') }}),
        current_date,
        interval '1 day'
    ) as d

)

select
    c.date_day,
    coalesce(prior.usd_ngn_rate, first_obs.usd_ngn_rate)   as usd_ngn_rate,
    coalesce(prior.rate_date,    first_obs.rate_date)      as rate_as_of_date,
    case
        when o.rate_date     is not null then 'observed'
        when prior.rate_date is not null then 'carried_forward'
        else 'backfilled'
    end                                                    as rate_basis
from calendar c
left join observed o
       on o.rate_date = c.date_day
left join lateral (
        select rate_date, usd_ngn_rate
        from observed
        where rate_date <= c.date_day
        order by rate_date desc
        limit 1
    ) prior on true
left join lateral (
        select rate_date, usd_ngn_rate
        from observed
        order by rate_date asc
        limit 1
    ) first_obs on true
