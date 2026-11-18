"""Compares two char_failures.py outputs: rows (every classifier's reading of each error) and the consumers' constants."""
import json, sys

a, b = (json.load(open(p)) for p in sys.argv[1:3])
rows = [(x["error"][:60], k, x[k], y[k]) for x, y in zip(a["rows"], b["rows"]) for k in x if x[k] != y[k]]
consts = [k for k in a["consts"] if a["consts"][k] != b["consts"].get(k)]
print(f"rows: {len(a['rows'])} vs {len(b['rows'])}, differing readings: {len(rows)}; constants: {len(a['consts'])}, differing: {len(consts)} {consts}")
for r in rows[:20]: print("  ", r)
sys.exit(1 if rows or consts or len(a["rows"]) != len(b["rows"]) else 0)
