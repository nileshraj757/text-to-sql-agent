# Devlog

## Build session (week 1-7 scaffolding, one sitting)
- **Data:** Kaggle needs a login, so `scripts/download_data.sh` pulls the 9 CSVs from a public Hugging Face mirror
  (`MafiaAzulBr/olistcsv`). Row counts match the known Olist figures (99,441 orders; 96,096 unique customers; 625 canceled).
  Check the Kaggle license (CC BY-NC-SA 4.0) before publishing a DB derived from it.
- **Bug:** YAML parsed `(1 order : many items)` as a mapping, which broke the linker's join graph. Fixed the wording; `tests` catch non-string joins.
- **Bug:** DuckDB shares one instance per file per process, so a second `make_connection` hit the locked config. Made it idempotent.
- **Security finding:** enum sample values go into the prompt, so a poisoned `order_status` value is a prompt-injection channel.
  Added a token-only regex filter (`schema_context._SAFE_ENUM`) and a red-team check for it. Free-text columns are deny-listed.
- **Design:** PII is blocked by rule (row-level listing of customer identifiers without aggregation). Trade-off: "list 5 customers in SP" is blocked.
- **False positives:** validator and input guard reject 0 of 88 benign SQL statements and 0 of 72 benign questions.
- **Not done / blocked:** no LLM key or reachable model in the build environment (Ollama cloud model returned Unauthorized),
  so the ladder, ablations, LLM judge, small-model row, Vanna baseline, Spider slice and error analysis are **unrun**. Docker image,
  public deployment and demo video were not built/recorded either. Everything is wired; see README "What's left".
