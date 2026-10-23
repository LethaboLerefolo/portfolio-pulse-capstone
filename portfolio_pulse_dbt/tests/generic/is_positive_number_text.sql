{#- For raw TEXT columns (Google Sheets delivers everything as text): the value,
    after stripping "$", "," and spaces, must be a number greater than zero.
    CASE guarantees the numeric cast only runs on text that already looks numeric. -#}
{% test is_positive_number_text(model, column_name) %}
select {{ column_name }} as bad_value
from {{ model }}
where {{ column_name }} is not null
  and trim({{ column_name }}) <> ''
  and case
        when regexp_replace({{ column_name }}, '[$,\s]', '', 'g') ~ '^[0-9]*\.?[0-9]+$'
          then regexp_replace({{ column_name }}, '[$,\s]', '', 'g')::numeric <= 0
        else true
      end
{% endtest %}
