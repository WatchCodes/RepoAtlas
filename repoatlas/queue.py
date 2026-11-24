"""DiscoveryManifest -> MigrationRequest queue."""
from __future__ import annotations

import hashlib
import re
from typing import Any

from .classify import KIND_TEST_FIXTURE, classify_url
from .contracts import validate
from .rename import canonical_target_name, ext_collision_name

_REPO_REF_RE = re.compile(r"^[A-Za-z0-9-]+/[A-Za-z0-9._-]{1,100}$")
_DEST_OWNER_RE = re.compile(r"^[A-Za-z0-9-]+$")
_BATCH_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")

# Discovery-scope classification. common.definitions.json permits only these
# three origin values; a raw owner.lower() is not a valid provenance.origin.
# Precedence: Nous lineage (owner) wins over a 'hermes' token in the repo name,
# because README states NousResearch/* stays in the Nous lineage.
_NOUS_OWNERS = frozenset({"nousresearch"})
# Roots explicitly documented in README as having no Nastech relationship.
# Keep the current fail-closed behaviour: they must not enter the queue.
_OUT_OF_SCOPE_ROOTS = frozenset({"plastic-labs/honcho", "burntsushi/ripgrep"})


def _fixture_only_repo_keys(manifest: dict[str, Any]) -> set[str]:
    """Repositories whose every URL occurrence is an excluded test fixture.

    Suppress an expected repository only when there is positive fixture
    evidence for that exact repository and no other URL evidence for it. A repo
    with no matching URL keeps its existing queue behaviour, so this never
    invents an exclusion from silence.
    """
    by_repo: dict[str, set[str]] = {}
    for item in manifest.get("urls", []):
        result = classify_url(item["url"])
        repo = result.get("repository")
        if not isinstance(repo, str) or not repo:
            continue
        by_repo.setdefault(repo.lower(), set()).add(str(result.get("kind")))
    return {
        key for key, kinds in by_repo.items()
        if kinds and all(kind == KIND_TEST_FIXTURE for kind in kinds)
    }


def _origin_for(repo: str) -> str:
    """Map an owner/repo to a valid provenance.origin enum value.

    Everything not explicitly Nous or Hermes is 'allowlisted' (the curated
    in-scope set), never the raw owner name. Out-of-scope roots are filtered by
    build_migration_requests before this is called.
    """
    owner, name = repo.split("/", 1)
    owner_l = owner.lower()
    name_l = name.lower()
    if owner_l in _NOUS_OWNERS or "nous" in owner_l:
        return "nous"
    if "hermes" in owner_l or "hermes" in name_l:
        return "hermes"
    if "nous" in name_l:
        return "nous"
    return "allowlisted"


class QueueValidationError(ValueError):
    """Raised when queue inputs fail closed validation."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise QueueValidationError(message)


def _normalize_repo_ref(value: Any) -> str:
    _require(isinstance(value, str), "repository ref must be a string")
    ref = value.strip()
    _require(bool(ref), "repository ref must not be empty")
    _require("/" in ref, f"invalid repository ref: {value!r}")
    owner, name = ref.split("/", 1)
    _require(bool(owner) and bool(name), f"invalid repository ref: {value!r}")
    _require(_REPO_REF_RE.match(ref) is not None, f"invalid repository ref: {value!r}")
    return ref


def _dedupe_repo_refs(values: Any) -> list[str]:
    _require(isinstance(values, list), "expected_repositories must be a list")
    chosen: dict[str, str] = {}
    for raw in values:
        ref = _normalize_repo_ref(raw)
        key = ref.lower()
        if key not in chosen:
            chosen[key] = ref
    return sorted(chosen.values(), key=lambda s: s.lower())


def _stable_disambiguator(repo_ref: str) -> str:
    digest = hashlib.sha256(repo_ref.lower().encode("utf-8")).hexdigest()[:8]
    return digest


def _resolve_collision_target(base_target: str, *, owner: str, repo_ref: str, seen_targets: dict[str, str]) -> str:
    owner_ext = owner
    candidates = [
        ext_collision_name(base_target, owner_ext),
        ext_collision_name(base_target, f"{owner_ext}-{repo_ref.split('/', 1)[1]}"),
        ext_collision_name(base_target, f"{owner_ext}-{_stable_disambiguator(repo_ref)}"),
    ]
    base_lower = base_target.lower()
    for candidate in candidates:
        key = candidate.lower()
        if key == base_lower:
            continue
        if key not in seen_targets:
            return candidate
        if seen_targets[key] == repo_ref.lower():
            return candidate

    # Deterministic last resort: keep extending with stable hash material, never "-2".
    for i in range(1, 10):
        candidate = ext_collision_name(base_target, f"{owner_ext}-{_stable_disambiguator(repo_ref + ':' + str(i))}")
        key = candidate.lower()
        if key not in seen_targets or seen_targets[key] == repo_ref.lower():
            return candidate
    raise QueueValidationError(f"unable to resolve target collision deterministically for {repo_ref!r}")


def build_migration_requests(manifest: dict[str, Any], *, destination_owner: str = "WatchCodes") -> list[dict[str, Any]]:
    _require(isinstance(manifest, dict), "manifest must be an object")
    validate("discovery-manifest", manifest)

    batch_id = manifest["batch_id"]
    source = manifest["source"]
    commit_sha = manifest["commit_sha"]
    _require(isinstance(batch_id, str) and _BATCH_ID_RE.match(batch_id) is not None, "invalid batch_id")
    _require(isinstance(source, str) and _REPO_REF_RE.match(source) is not None, "invalid manifest source")
    _require(isinstance(commit_sha, str) and _SHA_RE.match(commit_sha) is not None, "invalid commit_sha")
    _require(isinstance(destination_owner, str) and _DEST_OWNER_RE.match(destination_owner) is not None, "invalid destination_owner")

    repos = _dedupe_repo_refs(manifest.get("expected_repositories", []))
    fixture_only = _fixture_only_repo_keys(manifest)

    seen_targets: dict[str, str] = {}
    requests: list[dict[str, Any]] = []
    for repo in repos:
        if repo.lower() in fixture_only:
            continue
        if repo.lower() in _OUT_OF_SCOPE_ROOTS:
            continue
        owner, name = repo.split("/", 1)
        rn = canonical_target_name(name, owner=owner)
        _require(isinstance(rn.target, str) and bool(rn.target), f"invalid rename target for {repo!r}")
        # The rename engine already refused this name; emitting it as an
        # approved create request would bypass that human-review decision.
        if rn.status == "REQUIRES_REVIEW":
            raise QueueValidationError(
                f"target for {repo!r} requires review: {rn.reason or 'unspecified'}"
            )
        target = rn.target

        target_key = target.lower()
        repo_key = repo.lower()
        if target_key in seen_targets and seen_targets[target_key] != repo_key:
            target = _resolve_collision_target(target, owner=owner, repo_ref=repo, seen_targets=seen_targets)
            rn.reason = "collision"
            rn.status = "REQUIRES_REVIEW"

        final_key = target.lower()
        _require(final_key not in seen_targets or seen_targets[final_key] == repo_key, f"unresolved target collision for {repo!r}")
        seen_targets[final_key] = repo_key

        req = {
            "schema_version": 1,
            "batch_id": batch_id,
            "source": repo,
            "destination_owner": destination_owner,
            "target_name": target,
            "sha": commit_sha,
            "license": "NOASSERTION",
            "action": "create",
            "provenance": {
                "origin": _origin_for(repo),
                "discovered_in": source,
                "manifest_batch_id": batch_id,
            },
        }
        requests.append(req)
    return requests
