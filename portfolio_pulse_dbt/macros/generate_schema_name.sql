{#-
  By default dbt names schemas <target_schema>_<custom_schema> (e.g. public_marts).
  We want clean, predictable names - staging / intermediate / marts - because
  Metabase and the read-only role are pointed at them directly.
-#}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}
        {{ target.schema }}
    {%- else -%}
        {{ custom_schema_name | trim }}
    {%- endif -%}
{%- endmacro %}
