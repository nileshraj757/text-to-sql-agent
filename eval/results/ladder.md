| # | Configuration | Exec acc. | Valid-SQL | Halluc. schema % | Refusal acc. | p50 latency (s) | Tokens/query | $/query |
|---|---|---|---|---|---|---|---|---|
| 0 | External baseline (Vanna), default settings | | | | | | | |
| 1 | Zero-shot, raw DDL only |  |  |  |  |  |  |  |
| 2 | + descriptions, enum values, glossary |  |  |  |  |  |  |  |
| 3 | + retrieved few-shot |  |  |  |  |  |  |  |
| 4 | + schema pruning/linking |  |  |  |  |  |  |  |
| 5 | + self-correction (max 2 retries) |  |  |  |  |  |  |  |
| 6 | + guardrails (final system) |  |  |  |  |  |  |  |
| 6b | Final system, small open model |  |  |  |  |  |  |  |

| Tier | Step 1 | Step 2 | Step 3 | Step 5 | Step 6 |
|---|---|---|---|---|---|
| single_table |  |  |  |  |  |
| aggregation |  |  |  |  |  |
| join |  |  |  |  |  |
| multi_join |  |  |  |  |  |
| subquery_cte |  |  |  |  |  |
| window |  |  |  |  |  |
| date_logic |  |  |  |  |  |
