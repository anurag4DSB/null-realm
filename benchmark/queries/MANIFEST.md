# null-realm Benchmark — Queries Manifest

Auto-updated by `/nullrealm-capture` on save. One row per query. Use this file to skim the benchmark dataset without opening individual query files.

| Query ID | Archetype | Difficulty | Split | Source | Topic (one-line) | Required / Useful chunks | Date |
|---|---|---|---|---|---|---|---|
| q0001 | architecture-exploration | medium | unassigned | slack:engineer | S3C split-network: does `data_host` default lead to management-IP pinning? | 6 / 1 | 2026-04-21 |

## Schema

- **Query ID** — `qNNNN` format, sequentially assigned on capture. Never reused.
- **Archetype** — one of: cross-repo-regression, single-repo-bug, config-bug, impact-analysis, root-cause-investigation, architecture-exploration, constraint-identification, alternative-pattern-lookup.
- **Difficulty** — easy | medium | hard. Initial label assigned at capture by annotator judgment; empirically re-calibrated after first full benchmark sweep.
- **Split** — `unassigned` at capture time. Stratified assignment (dev/test/heldout 20/60/20) happens at benchmark-freeze time.
- **Source** — `jira:<ID>` / `github:<url>` / `slack:<role>` / `meeting:<ctx>` / `email:<role>` / `synthesized:<topic>`. ≥70% real-origin target for paper defensibility.
- **Topic** — one-line human-readable summary of the query, not the full text.
- **Required / Useful chunks** — count of chunks in each criticality tier.

## Notes

- Don't edit individual rows by hand unless re-annotating. The `/nullrealm-capture` skill appends on save.
- When a query is re-annotated (e.g., schema version bump), update the existing row rather than appending a new one.
