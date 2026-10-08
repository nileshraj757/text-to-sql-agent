"""CI gate: every evaluable attack must be defended and benign false positives must be zero."""
import json, sys
r = json.load(open(sys.argv[1]))
bad = []
if r["failures"]:
    bad.append(f"undefended attacks: {[f['id'] for f in r['failures']]}")
fp = r["benign_false_positives"]
if fp["validator_false_positives"] or fp["input_guard_false_positives"]:
    bad.append(f"false positives: {fp}")
print("RED-TEAM REGRESSION: " + "; ".join(bad) if bad else "red-team gate OK")
sys.exit(1 if bad else 0)
