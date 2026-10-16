# Benchmark tools

Normative methodology: [comparison specification](../specs/benchmark.md). The checked-in [protocol](protocol.json) fixes four baseline identities, three metrics and minimum confirmation requirements. No competitor results or real held-out dataset are included.

`evaluate.py` scores **independently adjudicated** paired records. It is not a product installer, runtime adapter, gold annotator or proof of honest data collection. Those components and real runs remain M0/M2/M5 work.

## Bundle shape

The input JSON has:

- `kind`: synthetic or confirmation. Synthetic is always diagnostic_only.
- `source_fingerprint`: required for confirmation; current value from `scripts/check_specs.py --fingerprint`.
- `common`: model, model_version, host_version, query_prompt_sha256, budget_sha256, dataset_sha256, gold_sha256.
- `systems`: exactly domimap, claude_obsidian, codebase_memory_mcp, codegraph, graphify. For confirmation each has immutable 40-character revision, config_sha256, health=ok and the same common settings.
- `cases`: id, cluster, category, answerable, gold_fact_ids, optional allowed_extra_fact_ids, evidence_groups (OR within a group, AND across groups for complete support), gold_disposition.
- `records`: one per system/case/registered seed, with status, ranked_evidence_ids, support_evidence_ids, fact_ids, disposition, scope_correct, unsupported_material_claim and unsupported_fact_ids (empty by default). Unsupported fact IDs must be a subset of predicted fact IDs and agree with the flag; they lose TP and incur FP. Confirmation also references raw_artifact_id and judgment_artifact_id.
- `artifacts`: an ID-to-record map; each record has role, project-independent bundle-relative path and sha256. Required provenance roles are in protocol.json; per-run raw_output and judgment roles are mandatory too.

Example single record structure (not a real result):

```json
{
  "system": "domimap", "case_id": "task-001", "seed": 11,
  "status": "ok", "ranked_evidence_ids": ["canonical-source-version-span"],
  "support_evidence_ids": ["canonical-source-version-span"],
  "fact_ids": ["independently-adjudicated-fact"],
  "disposition": "answer", "scope_correct": true,
  "unsupported_material_claim": false,
  "raw_artifact_id": "raw-001", "judgment_artifact_id": "judgment-001"
}
```

Canonical IDs come from blinded source/claim mapping, not from the evaluated agent reading gold. IDs containing a correct name as a substring do not count. Cases must contain known categories; every expected pairing is present, even runtime failures.

```bash
python3 -B benchmarks/evaluate.py --bundle out/benchmark/bundle.json
python3 -B benchmarks/evaluate.py --bundle out/benchmark/bundle.json --output out/benchmark/report.json --release
make release-check
```

CLI exits: 0 = diagnostic scoring succeeded, or real comparison passed; with --release, diagnostic_only is nonzero. 1 = quality gate unproven/failed. 2 = missing/invalid/incomplete input. Always inspect status and kind; a diagnostic command's exit 0 does not mean a product release passed.

The release entry point also checks every product acceptance case. Running only this scorer cannot establish production reliability or complete client/platform support.
