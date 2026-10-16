# Product specification v1

Status: accepted development target; implementation pending. Date: 2026-10-16.

## Outcome

A local knowledge base for people and code agents: find applicable evidence across Java repositories and project documents, preserve reviewed conclusions, reuse them across sessions, and revisit them when their support changes. Independent document directories and Markdown vaults are first-class sources. First production deployment is one owner with concurrent local clients, not a remote team service.

The four explicit capabilities remain mandatory: Claude/Codex/ZCode/DSH integration, model-free manual CLI/UI search, trusted AGENTS/SOUL customization, and explainable document aging. Human knowledge must survive graph rebuilds and export/restore. Unknown capabilities are visible rather than simulated.

## Normative requirements

The complete requirement registry is [requirements.json](requirements.json); executable acceptance descriptions are [acceptance.json](acceptance.json), and current completion state is [progress.json](progress.json). R01–R12 and F1–F4 retain the scope of the [roadmap](../docs/roadmap.md). R13 makes development traceable; R14 makes the comparison requirement a final gate.

1. Identity and scope are not inferred from display names, local absolute paths or branch names alone. Separate logical identity, source content version and applicability.
2. An externally returned evidence ID is backed by a readable immutable excerpt before publication. Current source cannot impersonate unavailable history.
3. A requirement, static implementation, runtime observation, human decision and inference are different claim types. Accepted inference does not become extracted fact.
4. Atomic generation publication preserves the last complete snapshot. Acknowledged knowledge writes are transactional, idempotent and conflict-aware under the declared local failure model.
5. Machine-derived data and authoritative knowledge/review records are separate. Rebuilds do not destroy human data or pinned support.
6. Query semantics, scope, freshness and error states are shared by CLI/MCP/UI. Work and output budgets are separately bounded.
7. Source families, validity, support and conflicts precede temporal ranking. Copying, touching, indexing or reading does not renew verification.
8. Normal documents cannot grant permissions or become trusted instructions. Registered roots, bounded parsing and safe local UI apply at every entry point.
9. Claims of support require direct tests for the actual format/construction/client/platform/version. Generic MCP or a mocked client does not complete four native integrations.
10. Every requirement has acceptance cases and every verified case has current, inspectable evidence. Missing means incomplete.
11. Final comparative quality is mandatory under [benchmark.md](benchmark.md): all three primary metrics strictly exceed each baseline with the registered confidence checks. No current comparative result is claimed.
12. Preserve user-authorized scope. Performance adjustments, private data policy and support changes are explicit; completion cannot be redefined around easier tests.

## Out of initial production scope

Remote multi-user service/ACL, universal language semantics, OCR/audio/video, a new agent runtime and unrestricted autonomous knowledge acceptance are separate future requirements. This does not remove any explicit client, manual search, persona or aging requirement.

## Change control

Routine implementation choices can be recorded in a task spec without asking the user again. A change to explicit user scope, comparison competitors, primary metrics, strict-win criterion or final acceptance denominator requires the user's explicit change of requirement; the agent cannot approve its own relaxation. Correcting a defective gold label invalidates and versions the evaluation for all systems, rather than improving one system's score in place.
