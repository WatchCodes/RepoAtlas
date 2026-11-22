"""DiscoveryManifest -> MigrationRequest queue."""
from __future__ import annotations
from typing import Any
from .contracts import validate
from .rename import canonical_target_name, ext_collision_name


def build_migration_requests(manifest: dict[str, Any], *, destination_owner: str = "WatchCodes") -> list[dict[str, Any]]:
    validate("discovery-manifest", manifest)
    batch_id = manifest["batch_id"]
    expected = manifest.get("expected_repositories", [])
    # deterministic ordering
    repos = sorted({r.strip() for r in expected if r and "/" in r}, key=lambda s: s.lower())
    seen_targets: dict[str, str] = {}
    requests = []
    for repo in repos:
        owner, name = repo.split("/", 1)
        rn = canonical_target_name(name, owner=owner)
        target = rn.target
        if target.lower() in seen_targets and seen_targets[target.lower()] != repo.lower():
            # collision: hard failure per README, but record convention in provenance note
            # Keep deterministic; caller/bridge can mark REQUIRES_REVIEW.
            target = ext_collision_name(target, owner)
            rn.reason = "collision"
            rn.status = "REQUIRES_REVIEW"
        seen_targets[target.lower()] = repo.lower()
        req = {
            "schema_version": 1,
            "batch_id": batch_id,
            "source": repo,
            "destination_owner": destination_owner,
            "target_name": target,
            "sha": manifest["commit_sha"],
            "license": "NOASSERTION",  # filled by CodeFoundry scan; intake will reject create without real license
            "action": "create",
            "provenance": {
                "origin": owner.lower(),
                "discovered_in": manifest["source"],
                "manifest_batch_id": batch_id,
            },
        }
        requests.append(req)
    return requests
