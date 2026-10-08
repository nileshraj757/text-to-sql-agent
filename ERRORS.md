# Error analysis

No model has been run against the test set yet (no LLM key was available when this repo was built), so there are **no
categorized failures to report**. Writing any here would be fabrication.

How to fill this in:

1. `python eval/run_ladder.py --run --split dev` (needs `GROQ_API_KEY`, see `.env.example`).
2. `python eval/error_analysis.py eval/results/step6_guardrails_dev.csv` prints the failure distribution and worked examples.
3. Confirm/override the auto-label (`error_label` column; valid labels in `eval/error_analysis.py`), then paste the table and 2-3 examples
   per category (question, gold, predicted, why it failed, what fixed it) below. Target: 20+ categorized failures.

Root-cause order (label the FIRST that applies): test-set error -> syntax/dialect or hallucinated schema -> wrong join ->
wrong aggregation (fan-out!) -> wrong filter/date -> business-logic misunderstanding -> ambiguity -> evaluator artifact.

## Things the test set was designed to catch (predictions, not results)
- `customer_id` vs `customer_unique_id` (q044, q056, q011-style questions)
- payments x items fan-out when computing revenue by payment type (few-shot pool has the safe pattern)
- canceled/unavailable orders in revenue; Portuguese vs English category names
- date_diff whole-day semantics (see docs/eval_policy.md)
