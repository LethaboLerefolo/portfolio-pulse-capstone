-- The donut chart must add up to 100% (allowing for per-row rounding).
select round(sum(allocation_pct), 2) as total_allocation_pct
from {{ ref('mart_current_positions') }}
having abs(sum(allocation_pct) - 100) > 0.1
