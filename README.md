# RepoAtlas

**Role:** discovery records, URL validation, and the ordered migration queue.

This repository is the durable specification and memory for the RepoAtlas role in the
WatchCodes factory. Read this file before doing anything here.

---

## Responsibility

RepoAtlas turns raw discovery output into a **validated, deduplicated, ordered queue of
migration jobs**. It is the only component allowed to decide *what* a URL means and
*what the destination should be called*.

1. Receive a `DiscoveryManifest` from `NastechResearch/100Ways`.
2. Classify every URL occurrence:
   - repository root
   - user / organisation profile (record only, never a repository)
   - issue, pull request, release, docs deep link (resolve to the parent repository)
   - API fragment (`api.github.com/repos/<owner>`, `search/repositories`)
   - test fixture (excluded unconditionally)
   - invalid or unavailable (`REQUIRES_REVIEW`)
3. Resolve to a repository root and normalise identity **case-insensitively** for
   comparison while preserving the original spelling for display.
4. Apply the one canonical rename algorithm, exactly once, here:
   1. name already starts with `nastech-` or equals `nastech` → keep
   2. replace `hermes` / `nous` case-insensitively with `nastech`; collapse `nastech-nastech`
   3. keep the rest of the identity (`my-hermes-plugin` → `my-nastech-plugin`)
   4. sanitise to `[A-Za-z0-9._-]`, max 100 characters, no leading dot
   5. empty result → `nastech-<owner>-<name>`
   6. collision → **hard failure** (`REQUIRES_REVIEW`); never append `-2`
   7. the upstream URL is always recorded in `repository-mappings.json`
5. Order the queue deterministically and emit one `MigrationRequest` per source repository.

## What it never does

- Never creates, clones, brands or verifies a repository.
- Never publishes or merges anything.
- Never decides ownership. `NousResearch/*` stays in the NastechResearch lineage and is
  never routed to WatchCodes.
- Never makes a decision by guessing. No detectable licence, ambiguous identity or a
  collision all end in `REQUIRES_REVIEW`.

## Contracts

| Direction | Contract | Minimum fields |
|---|---|---|
| consumes | `DiscoveryManifest` | `batch_id`, `source`, `commit_sha`, `created_at`, `urls[{url, kind, path, line, occurrences}]`, `expected_repositories` |
| produces | `MigrationRequest` | `batch_id`, `source`, `destination_owner`, `target_name`, `sha`, `license`, `action` (`create` / `import_subtree`), `subtree_path`, `provenance` |

The JSON schema is the contract. Prose in a report is never the contract.

## Status it owns

`DISCOVERED → QUEUED`

It may only set `REQUIRES_REVIEW`. It never sets `CREATED`, `VERIFIED`, `GATED` or `READY`
— those belong to CodeFoundry and NastechBridge.

## Input scope

Hermes/Nous plus a curated allowlist, and nothing else. Measured over the 100Ways tree:
4 Nous lineage, 7 owned, 12 real external Hermes candidates, 7 API fragments that are not
repositories, 7 fixtures. Every other root (React, Python, `plastic-labs/honcho`,
`BurntSushi/ripgrep`) has no Nastech relationship and must not enter the queue.

## Related repositories

- `WatchCodes/CodeFoundry` — consumes this queue; creates, brands and verifies
- `WatchCodes/SourceSentinel` — monitors a verified destination's upstream afterwards
- `WatchCodes/CodeLineage` — records the source→destination identity
- `WatchCodes/NastechBridge` — the durable report waitlist
- `NastechResearch/100Ways` — discovers and brands `nastech-agent` only; never creates repos
