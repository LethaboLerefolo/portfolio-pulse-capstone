{#- Fails for any non-null value that is not strictly YYYY-MM-DD.
    Why: Postgres reads '03/04/2025' as 4 March (MDY) - a silent, wrong date.
    We would rather the pipeline go red than value a trade on the wrong day. -#}
{% test is_iso_date(model, column_name) %}
select {{ column_name }} as bad_value
from {{ model }}
where {{ column_name }} is not null
  and trim({{ column_name }}) <> ''
  and trim({{ column_name }}) !~ '^\d{4}-\d{2}-\d{2}$'
{% endtest %}
