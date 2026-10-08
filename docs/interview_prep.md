# Interview prep

Fill every [bracket] from `eval/results/` before using. Do not quote a number a script did not produce.

## Pitch (3 lines)
I built a Text-to-SQL analytics agent over a 9-table Olist e-commerce database that turns English questions into validated,
read-only DuckDB SQL, runs it, and returns a chart plus a grounded explanation. I evaluated it on an 80-question tiered test set with
execution accuracy, going from [X]% zero-shot to [Y]% with schema-aware prompting and self-correction, and defended [34/34] evaluable
offline red-team attacks with 0 false positives on [88] benign queries (measured). CI gates pipeline regressions.

## 2-minute version
Problem (20s) -> design: schema context + glossary, validate-execute-repair, three guardrail layers (40s) -> evaluation: result-set
execution accuracy, ladder, one surprising failure (40s) -> engineering: tests, CI gate, red-team (20s).

## Resume bullets (measured parts only; fill brackets)
- Built a Text-to-SQL agent (DuckDB, sqlglot, [LLM]) with schema-aware prompting, a validate-execute-repair loop and auto-selected charts.
- Designed an 80-question tiered evaluation with result-set execution accuracy; raised accuracy from [X]% to [Y]%.
- Implemented three-layer guardrails (AST allowlist, read-only DB with external access off, timeouts/row caps); 34/34 evaluable offline attacks defended, 0 false positives on 88 benign queries.
- CI gate that fails builds on a broken prompt or an over-blocking validator (verified by tests/test_regression_gate.py).

## 15 questions - answer from your own code
1 DROP TABLE: `validator.py` (AST, single SELECT) + `executor.py` (read_only, external access off, lock_configuration) + limits. `eval/redteam/run_redteam.py` shows which layer caught each attack.
2 Why not regex: comments/case/unicode (obfuscation attacks a29-a32 in the set) and false positives.
3 Execution accuracy: `eval/compare.py`, policy in `docs/eval_policy.md`.
4 Test set: `eval/build_testset.py`, `verify_gold.py` (pandas recomputation, tie check, leakage check). Be upfront: peer check not done.
5 200 tables: `agent/linking.py` (embedding + keyword boost + join-path connectors). Measured on 9 tables: [step 4 result]. Larger synthetic schema is future work.
6 Biggest gain: read from the ladder, do not guess.
7 Fan-out: glossary `revenue` entry, few-shot example "revenue from credit-card orders" uses `IN (subquery)`.
8 Self-correction: fatal vs repairable (`SQLValidationError.fatal`); fails on semantic errors that execute.
9 Wrong-but-runs: offline gold comparison; online show SQL + assumptions, number-grounding check (`explain/check.py`).
10 Prompt injection: enum-value filter, deny-listed free text, `<data>` quoting, validator as backstop.
11 Grounded numbers: `explain/check.py`, metric = % explanations with zero ungrounded numbers [measure it].
12 Plain Python: the loop is `agent/pipeline.py` (~100 lines).
13 Ambiguity: assumptions vs clarification, scored on the ambiguous tier.
14 Production: Postgres read-only role + RLS, semantic layer, cost limits, monitoring.
15 Next: semantic layer, LoRA fine-tune on validated pairs, multi-turn eval.
