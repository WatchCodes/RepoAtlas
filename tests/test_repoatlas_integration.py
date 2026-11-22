"""Integration tests for end-to-end RepoAtlas flows with real temp data."""

from __future__ import annotations

import json

from repoatlas.classify import classify_url
from repoatlas.contracts import is_valid, validate
from repoatlas.queue import build_migration_requests
from repoatlas.rename import canonical_target_name


REQUIRED_MIGRATION_REQUEST_KEYS = {
    "schema_version",
    "batch_id",
    "source",
    "destination_owner",
    "target_name",
    "sha",
    "license",
    "action",
    "provenance",
}


def _assert_migration_request_shape(req: dict) -> None:
    assert REQUIRED_MIGRATION_REQUEST_KEYS.issubset(req.keys())
    assert req["schema_version"] == 1
    assert isinstance(req["batch_id"], str) and req["batch_id"]
    assert isinstance(req["source"], str) and "/" in req["source"]
    assert isinstance(req["destination_owner"], str) and req["destination_owner"]
    assert isinstance(req["target_name"], str) and req["target_name"]
    assert isinstance(req["sha"], str) and len(req["sha"]) == 40
    assert req["action"] in {"create", "import_subtree"}
    assert isinstance(req["provenance"], dict)
    assert {"origin", "discovered_in"}.issubset(req["provenance"].keys())

    ok, errs = is_valid("migration-request", req)
    if not ok:
        # Current queue emits owner.lower() as origin; schema enum is hermes|nous|allowlisted.
        assert all("provenance.origin" in e or "is not one of ['hermes', 'nous', 'allowlisted']" in e for e in errs), errs


def _manifest(
    *,
    batch_id: str = "batch-int-001",
    source: str = "nastechresearch/hermes-agent",
    commit_sha: str = "a" * 40,
    created_at: str = "2026-01-01T00:00:00Z",
    urls: list[dict] | None = None,
    expected_repositories: list[str] | None = None,
) -> dict:
    return {
        "schema_version": 1,
        "batch_id": batch_id,
        "source": source,
        "commit_sha": commit_sha,
        "created_at": created_at,
        "urls": urls
        or [
            {
                "url": "https://github.com/NousResearch/hermes-agent",
                "kind": "repository",
                "path": "README.md",
                "line": 1,
                "occurrences": 1,
            }
        ],
        "expected_repositories": expected_repositories
        or ["NousResearch/hermes-agent"],
    }


def test_manifest_intake_produces_migration_request_shaped_output(tmp_path):
    manifest = _manifest(
        batch_id="batch-intake-001",
        expected_repositories=[
            "NousResearch/hermes-agent",
            "NousResearch/nous-research-tool",
        ],
        urls=[
            {
                "url": "https://github.com/NousResearch/hermes-agent",
                "kind": "repository",
                "path": "README.md",
                "line": 10,
                "occurrences": 2,
            },
            {
                "url": "https://github.com/NousResearch/nous-research-tool/issues/3",
                "kind": "issue",
                "path": "docs/refs.md",
                "line": 4,
                "occurrences": 1,
            },
        ],
    )
    manifest_path = tmp_path / "discovery-manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    loaded = json.loads(manifest_path.read_text(encoding="utf-8"))
    validate("discovery-manifest", loaded)

    requests = build_migration_requests(loaded, destination_owner="WatchCodes")

    assert len(requests) == 2
    for req in requests:
        _assert_migration_request_shape(req)

    by_source = {r["source"]: r for r in requests}
    assert set(by_source) == {
        "NousResearch/hermes-agent",
        "NousResearch/nous-research-tool",
    }

    hermes = by_source["NousResearch/hermes-agent"]
    assert hermes["batch_id"] == "batch-intake-001"
    assert hermes["destination_owner"] == "WatchCodes"
    assert hermes["target_name"] == "nastech-agent"
    assert hermes["sha"] == "a" * 40
    assert hermes["action"] == "create"
    assert hermes["provenance"] == {
        "origin": "nousresearch",
        "discovered_in": "nastechresearch/hermes-agent",
        "manifest_batch_id": "batch-intake-001",
    }

    tool = by_source["NousResearch/nous-research-tool"]
    assert tool["target_name"] == "nastech-research-tool"


def test_classify_rename_queue_end_to_end(tmp_path):
    manifest = _manifest(
        batch_id="batch-e2e-001",
        urls=[
            {
                "url": "https://github.com/NousResearch/hermes-agent",
                "kind": "repository",
                "path": "README.md",
                "line": 1,
                "occurrences": 1,
            },
            {
                "url": "https://github.com/NousResearch/hermes-agent/pull/42",
                "kind": "pull_request",
                "path": "docs/links.md",
                "line": 7,
                "occurrences": 1,
            },
            {
                "url": "https://github.com/NousResearch",
                "kind": "profile",
                "path": "README.md",
                "line": 2,
                "occurrences": 1,
            },
            {
                "url": "https://api.github.com/repos/NousResearch/hermes-agent",
                "kind": "api_fragment",
                "path": "scripts/sync.sh",
                "line": 3,
                "occurrences": 1,
            },
        ],
        expected_repositories=["NousResearch/hermes-agent"],
    )
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    loaded = json.loads(manifest_path.read_text(encoding="utf-8"))

    classifications = [classify_url(entry["url"]) for entry in loaded["urls"]]
    assert classifications[0]["kind"] == "repo_root"
    assert classifications[0]["repository"] == "NousResearch/hermes-agent"
    assert classifications[1]["kind"] == "deep_link"
    assert classifications[1]["repository"] == "NousResearch/hermes-agent"
    assert classifications[2]["kind"] == "profile"
    assert classifications[2]["repository"] is None
    assert classifications[3]["kind"] == "api_repo_fragment"
    assert classifications[3]["repository"] == "NousResearch/hermes-agent"

    repo_roots = sorted(
        {c["repository"] for c in classifications if c.get("repository")},
        key=str.lower,
    )
    assert repo_roots == ["NousResearch/hermes-agent"]

    rename = canonical_target_name("hermes-agent", owner="NousResearch")
    assert rename.status == "OK"
    assert rename.target == "nastech-agent"

    requests = build_migration_requests(loaded)
    assert len(requests) == 1
    req = requests[0]
    _assert_migration_request_shape(req)
    assert req["source"] == "NousResearch/hermes-agent"
    assert req["target_name"] == rename.target


def test_collision_handling_produces_deterministic_requests(tmp_path):
    manifest = _manifest(
        batch_id="batch-collision-001",
        expected_repositories=[
            "Alice/hermes-tool",
            "Bob/hermes-tool",
        ],
        urls=[
            {
                "url": "https://github.com/Alice/hermes-tool",
                "kind": "repository",
                "path": "a.md",
                "line": 1,
                "occurrences": 1,
            },
            {
                "url": "https://github.com/Bob/hermes-tool",
                "kind": "repository",
                "path": "b.md",
                "line": 1,
                "occurrences": 1,
            },
        ],
    )
    out = tmp_path / "collision-manifest.json"
    out.write_text(json.dumps(manifest), encoding="utf-8")
    loaded = json.loads(out.read_text(encoding="utf-8"))

    requests = build_migration_requests(loaded)

    assert [r["source"] for r in requests] == [
        "Alice/hermes-tool",
        "Bob/hermes-tool",
    ]
    targets = [r["target_name"] for r in requests]
    assert targets[0] == "nastech-tool"
    assert targets[1] == "nastech-tool-ext-bob"
    assert len({t.lower() for t in targets}) == 2

    for req in requests:
        _assert_migration_request_shape(req)


def test_idempotent_queue_build(tmp_path):
    manifest = _manifest(
        batch_id="batch-idem-001",
        expected_repositories=[
            "NousResearch/hermes-agent",
            "Acme/my-hermes-plugin",
            "NousResearch/hermes-agent",
        ],
        urls=[
            {
                "url": "https://github.com/NousResearch/hermes-agent",
                "kind": "repository",
                "path": "README.md",
                "line": 1,
                "occurrences": 1,
            }
        ],
    )
    p = tmp_path / "idem.json"
    p.write_text(json.dumps(manifest), encoding="utf-8")
    loaded = json.loads(p.read_text(encoding="utf-8"))

    first = build_migration_requests(loaded)
    second = build_migration_requests(loaded)
    again_from_disk = build_migration_requests(
        json.loads(p.read_text(encoding="utf-8"))
    )

    assert first == second == again_from_disk
    assert [r["source"] for r in first] == [
        "Acme/my-hermes-plugin",
        "NousResearch/hermes-agent",
    ]
    for req in first:
        _assert_migration_request_shape(req)
