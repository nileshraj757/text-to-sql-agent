"""CI regression gate: exit 1 if a metric falls below its threshold. null thresholds are skipped."""
import json, sys
metrics = json.load(open(sys.argv[1]))
thr = json.load(open(sys.argv[2]))
mapping = {"execution_accuracy_min": "execution_accuracy", "valid_sql_min": "valid_sql_rate",
           "refusal_accuracy_min": "refusal_accuracy", "overall_accuracy_min": "overall_accuracy"}
bad = []
for k, m in mapping.items():
    if thr.get(k) is not None and (metrics.get(m) is None or metrics[m] < thr[k]):
        bad.append(f"{m}={metrics.get(m)} < {thr[k]}")
if thr.get("max_false_positive_blocks") is not None and metrics["false_positive_blocks_on_answerable"] > thr["max_false_positive_blocks"]:
    bad.append(f"validator false positives {metrics['false_positive_blocks_on_answerable']} > {thr['max_false_positive_blocks']}")
print("REGRESSION: " + "; ".join(bad) if bad else "thresholds OK")
sys.exit(1 if bad else 0)
