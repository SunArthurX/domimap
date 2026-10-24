import json, sys
r = json.load(open("out/benchmark/report.json"))
gates = r.get("gate_reasons", [])
ok = ("below absolute floor" in " ".join(gates)) and \
     not any("strict paired" in g for g in gates) and \
     r["metrics"]["domimap"]["negative_accuracy"] >= 0.99
print("终验行为断言:", "PASS" if ok else "FAIL", "| gate_reasons:", gates)
sys.exit(0 if ok else 1)
